"""OAuth endpoints — GitHub and Google sign-in, token refresh, user profile."""

import secrets
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import (
    build_github_authorize_url,
    create_jwt_token,
    exchange_code_for_token,
    fetch_github_user,
    get_current_user,
)
from app.config import get_settings
from app.models.database import CloudCredential, get_db

logger = structlog.get_logger()
settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])

# Google OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


@router.get("/github/login")
async def github_login(redirect_url: str | None = None):
    """Initiate GitHub OAuth flow.

    Returns the GitHub authorization URL. The frontend redirects the user there
    to sign in and grant repository access.

    Query params:
        redirect_url: Where to redirect after successful auth (default: frontend)
    """
    result = build_github_authorize_url()

    # Store the intended redirect in state (in production, use Redis)
    return {
        "authorize_url": result["url"],
        "state": result["state"],
        "message": "Redirect the user to authorize_url to begin GitHub sign-in",
    }


@router.get("/github/callback")
async def github_callback(
    code: str = Query(..., description="GitHub OAuth authorization code"),
    state: str = Query("", description="CSRF state parameter"),
    db: AsyncSession = Depends(get_db),
):
    """GitHub OAuth callback — handles both sign-in and connect flows.

    If state contains encrypted user data → this is a "connect" flow (link GitHub to existing account).
    Otherwise → this is a normal sign-in flow (create JWT).
    """
    frontend_url = settings.effective_frontend_url

    try:
        # 1. Exchange authorization code for GitHub access token
        token_data = await exchange_code_for_token(code)
        github_access_token = token_data["access_token"]
        granted_scopes = token_data.get("scope", "")

        logger.info("GitHub OAuth token obtained", scopes=granted_scopes)

        # 2. Check if this is a "connect" flow (link to existing account)
        connect_user_id = None
        try:
            import json

            from app.utils.encryption import decrypt as decrypt_text
            state_data = json.loads(decrypt_text(state))
            if state_data.get("flow") == "connect":
                connect_user_id = state_data["user_id"]
        except Exception:
            pass  # Not a connect flow — normal sign-in

        # 3. Fetch user profile
        user_data = await fetch_github_user(github_access_token)

        logger.info(
            "GitHub user authenticated",
            login=user_data["login"],
            repos=len(user_data.get("repos", [])),
            flow="connect" if connect_user_id else "sign-in",
        )

        if connect_user_id:
            # ─── Connect Flow: store GitHub token for existing user ───
            from app.utils.encryption import encrypt

            encrypted_token = encrypt(github_access_token)

            result = await db.execute(
                select(CloudCredential).where(
                    CloudCredential.user_id == connect_user_id,
                    CloudCredential.provider == "github",
                )
            )
            cred = result.scalar_one_or_none()

            if cred:
                cred.encrypted_refresh_token = encrypted_token
                cred.email = user_data.get("email")
                cred.project_id = user_data["login"]
                cred.is_active = True
            else:
                cred = CloudCredential(
                    user_id=connect_user_id,
                    provider="github",
                    project_id=user_data["login"],
                    email=user_data.get("email"),
                    encrypted_refresh_token=encrypted_token,
                    scopes=granted_scopes,
                    is_active=True,
                )
                db.add(cred)

            await db.commit()
            logger.info("GitHub linked to existing account", user=connect_user_id, github=user_data["login"])

            # Redirect back to dashboard — user's JWT is still in localStorage
            return RedirectResponse(url=f"{frontend_url}/?github=connected")

        else:
            # ─── Sign-in Flow: create JWT ───
            jwt_token = create_jwt_token(user_data, github_access_token)
            return RedirectResponse(url=f"{frontend_url}/?token={jwt_token}")

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error("GitHub OAuth callback failed", error=str(e), traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get the current authenticated user's profile."""
    return {
        "login": user.get("login"),
        "name": user.get("name"),
        "email": user.get("email"),
        "avatar_url": user.get("avatar_url"),
        "role": user.get("role", "engineer"),
    }


@router.post("/github/pat")
async def save_github_pat(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a GitHub Personal Access Token for the user.

    Validates the token by calling GitHub API, then stores it encrypted.
    """
    import base64

    body = await request.json()
    raw_token = body.get("token", "").strip()
    if not raw_token:
        raise HTTPException(status_code=400, detail="Token is required")
    try:
        pat = base64.b64decode(raw_token).decode("utf-8")
    except Exception:
        pat = raw_token  # fallback if not base64-encoded

    # Validate the token by calling GitHub
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=10,
        )

    if resp.status_code == 401:
        raise HTTPException(status_code=400, detail="Invalid token — GitHub returned 401 Unauthorized")
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Token validation failed: HTTP {resp.status_code}")

    github_user = resp.json()
    github_login = github_user.get("login", "")
    github_email = github_user.get("email", "")

    # Encrypt and store
    from app.utils.encryption import encrypt

    user_id = user.get("sub", user.get("login", ""))
    encrypted_token = encrypt(pat)

    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "github",
        )
    )
    cred = result.scalar_one_or_none()

    if cred:
        cred.encrypted_refresh_token = encrypted_token
        cred.email = github_email
        cred.project_id = github_login
        cred.scopes = "pat"
        cred.is_active = True
    else:
        cred = CloudCredential(
            user_id=user_id,
            provider="github",
            project_id=github_login,
            email=github_email,
            encrypted_refresh_token=encrypted_token,
            scopes="pat",
            is_active=True,
        )
        db.add(cred)

    await db.commit()

    logger.info("GitHub PAT saved", user=user_id, github_login=github_login)

    return {
        "status": "connected",
        "login": github_login,
        "email": github_email,
        "source": "pat",
    }


async def _get_github_token(user: dict, db: AsyncSession) -> str:
    """Get GitHub token from JWT or DB. Raises if not found."""
    token = user.get("github_token")
    if token:
        return token

    # Fall back to DB (for Google-signed-in users who linked GitHub)
    from app.utils.encryption import decrypt as decrypt_text
    user_id = user.get("sub", user.get("login", ""))
    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "github",
            CloudCredential.is_active == True,
        )
    )
    cred = result.scalar_one_or_none()
    if cred:
        return decrypt_text(cred.encrypted_refresh_token)

    raise HTTPException(status_code=403, detail="No GitHub token available. Please connect GitHub in Settings.")


@router.get("/repos")
async def get_user_repos(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the authenticated user's accessible repositories."""
    import httpx

    github_token = await _get_github_token(user, db)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user/repos",
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            params={"per_page": 100, "sort": "updated", "type": "all"},
            timeout=15,
        )

        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="GitHub token expired. Please re-authenticate.")

        resp.raise_for_status()
        repos = resp.json()

        return {
            "total": len(repos),
            "repos": [
                {
                    "full_name": r["full_name"],
                    "name": r["name"],
                    "private": r["private"],
                    "language": r.get("language"),
                    "description": r.get("description"),
                    "default_branch": r.get("default_branch", "main"),
                    "updated_at": r.get("updated_at"),
                    "url": r["html_url"],
                    "owner": r["owner"]["login"],
                    "permissions": r.get("permissions", {}),
                }
                for r in repos
            ],
        }


@router.get("/orgs")
async def get_user_orgs(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the authenticated user's GitHub organizations."""
    import httpx

    github_token = await _get_github_token(user, db)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user/orgs",
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=10,
        )
        resp.raise_for_status()

        return {
            "orgs": [
                {
                    "login": o["login"],
                    "avatar_url": o.get("avatar_url"),
                    "description": o.get("description"),
                }
                for o in resp.json()
            ]
        }


# ─── GitHub Connect (Link GitHub to existing account) ──────────────────────


@router.get("/github/connect")
async def github_connect_start(user: dict = Depends(get_current_user)):
    """Start GitHub OAuth to link GitHub to an already-signed-in user.

    Encodes the user's identity in the state parameter so the callback
    can identify the user without requiring auth headers (browser redirect).
    """
    import json

    from app.utils.encryption import encrypt

    user_id = user.get("sub", user.get("login", ""))

    # Encode user_id in state so callback can identify the user
    state_data = json.dumps({"user_id": user_id, "flow": "connect"})
    encrypted_state = encrypt(state_data)

    result = build_github_authorize_url(state=encrypted_state)

    return {
        "authorize_url": result["url"],
        "state": encrypted_state,
    }


@router.get("/github/status")
async def github_status(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if the user has linked their GitHub account."""
    user_id = user.get("sub", user.get("login", ""))

    # Check JWT first (if signed in via GitHub)
    if user.get("github_token"):
        return {
            "connected": True,
            "login": user.get("login"),
            "source": "jwt",
        }

    # Check DB (if linked after Google sign-in)
    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "github",
            CloudCredential.is_active == True,
        )
    )
    cred = result.scalar_one_or_none()
    if cred:
        return {
            "connected": True,
            "login": cred.project_id,
            "email": cred.email,
            "source": "pat" if cred.scopes == "pat" else "linked",
        }

    return {"connected": False}


@router.post("/github/disconnect")
async def github_disconnect(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unlink GitHub from the user's account."""
    user_id = user.get("sub", user.get("login", ""))
    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "github",
        )
    )
    cred = result.scalar_one_or_none()
    if cred:
        await db.delete(cred)
        await db.commit()
    return {"status": "disconnected"}


# ─── Google OAuth Sign-In ──────────────────────────────────────────────────


@router.get("/google/login")
async def google_login():
    """Initiate Google OAuth sign-in flow.

    Returns the Google authorization URL for sign-in + cloud access.
    """
    if not settings.gcp_oauth_client_id:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    state = secrets.token_urlsafe(32)

    # Request sign-in scopes + cloud read-only scopes
    scopes = (
        "openid email profile "
        "https://www.googleapis.com/auth/cloud-platform.read-only "
        "https://www.googleapis.com/auth/logging.read "
        "https://www.googleapis.com/auth/monitoring.read"
    )

    params = {
        "client_id": settings.gcp_oauth_client_id,
        "redirect_uri": settings.google_signin_redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": f"signin_{state}",
        "include_granted_scopes": "true",
    }

    authorize_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    return {
        "authorize_url": authorize_url,
        "state": state,
    }


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(""),
):
    """Google OAuth callback — exchanges code for token and returns JWT.

    Signs the user in with Google and also stores their GCP credentials
    for cloud access.
    """
    if not settings.gcp_oauth_client_id:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    try:
        # 1. Exchange code for tokens
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.gcp_oauth_client_id,
                    "client_secret": settings.gcp_oauth_client_secret,
                    "redirect_uri": settings.google_signin_redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=15,
            )

        if token_resp.status_code != 200:
            logger.error("Google token exchange failed", body=token_resp.text)
            raise HTTPException(status_code=400, detail="Failed to exchange Google authorization code")

        tokens = token_resp.json()
        access_token = tokens["access_token"]
        refresh_token = tokens.get("refresh_token")

        # 2. Fetch Google user profile
        async with httpx.AsyncClient() as client:
            userinfo_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
        if userinfo_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Google user profile")

        google_user = userinfo_resp.json()
        google_email = google_user.get("email", "")
        google_name = google_user.get("name", google_email.split("@")[0])
        google_id = google_user.get("id", "")
        google_avatar = google_user.get("picture", "")

        logger.info("Google user authenticated", email=google_email, name=google_name)

        # 3. Create JWT (same format as GitHub, so the rest of the app works)
        user_data = {
            "github_id": f"google_{google_id}",
            "login": google_email.split("@")[0],
            "name": google_name,
            "email": google_email,
            "avatar_url": google_avatar,
            "repos": [],
            "orgs": [],
        }

        # Use empty string for github_token since this is Google sign-in
        jwt_token = create_jwt_token(user_data, github_access_token="")

        # 4. If we got a refresh_token, store encrypted GCP credentials
        if refresh_token:
            try:
                from sqlalchemy import select

                from app.models.database import CloudCredential, async_session
                from app.utils.encryption import encrypt

                encrypted_token = encrypt(refresh_token)

                # List GCP projects
                projects = []
                async with httpx.AsyncClient() as client:
                    projects_resp = await client.get(
                        "https://cloudresourcemanager.googleapis.com/v1/projects",
                        headers={"Authorization": f"Bearer {access_token}"},
                        params={"filter": "lifecycleState:ACTIVE"},
                        timeout=10,
                    )
                if projects_resp.status_code == 200:
                    projects = [p["projectId"] for p in projects_resp.json().get("projects", [])]

                # Store credentials
                async with async_session() as db:
                    user_id = f"google_{google_id}"
                    result = await db.execute(
                        select(CloudCredential).where(
                            CloudCredential.user_id == user_id,
                            CloudCredential.provider == "gcp",
                        )
                    )
                    cred = result.scalar_one_or_none()

                    if cred:
                        cred.encrypted_refresh_token = encrypted_token
                        cred.email = google_email
                        cred.is_active = True
                        if projects and not cred.project_id:
                            cred.project_id = projects[0]
                    else:
                        cred = CloudCredential(
                            user_id=user_id,
                            provider="gcp",
                            project_id=projects[0] if projects else None,
                            email=google_email,
                            encrypted_refresh_token=encrypted_token,
                            scopes=tokens.get("scope", ""),
                            is_active=True,
                        )
                        db.add(cred)

                    await db.commit()

                logger.info("GCP credentials stored for Google sign-in user", email=google_email, projects=len(projects))
            except Exception as e:
                logger.warning("Failed to store GCP credentials during sign-in", error=str(e))

        # 5. Redirect to frontend
        frontend_url = settings.effective_frontend_url
        redirect_url = f"{frontend_url}/?token={jwt_token}"

        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Google OAuth callback failed", error=str(e))
        raise HTTPException(status_code=500, detail="Google authentication failed")
