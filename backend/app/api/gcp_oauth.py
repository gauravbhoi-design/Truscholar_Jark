"""GCP OAuth2 endpoints — Lets users connect their own GCP project securely."""

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.config import get_settings
from app.models.database import CloudCredential, get_db
from app.utils.encryption import decrypt, encrypt

logger = structlog.get_logger()
settings = get_settings()
router = APIRouter(prefix="/auth/gcp", tags=["gcp-auth"])

# Google OAuth2 endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_PROJECTS_URL = "https://cloudresourcemanager.googleapis.com/v1/projects"


@router.get("/login")
async def gcp_login(user: dict = Depends(get_current_user)):
    """Generate GCP OAuth2 authorization URL for the user."""
    import json

    from app.utils.encryption import encrypt as enc

    if not settings.gcp_oauth_client_id:
        raise HTTPException(
            status_code=503,
            detail="GCP OAuth is not configured. Set GCP_OAUTH_CLIENT_ID and GCP_OAUTH_CLIENT_SECRET.",
        )

    # Encode user_id in state so callback can identify the user (browser redirect has no JWT)
    user_id = user.get("sub", user.get("login", ""))
    state = enc(json.dumps({"user_id": user_id, "flow": "gcp_connect"}))

    params = {
        "client_id": settings.gcp_oauth_client_id,
        "redirect_uri": settings.effective_gcp_oauth_redirect_uri,
        "response_type": "code",
        "scope": settings.gcp_oauth_scopes,
        "access_type": "offline",  # Get refresh_token
        "prompt": "consent",  # Always show consent to ensure refresh_token
        "state": state,
        "include_granted_scopes": "true",
    }

    # Use httpx to properly encode
    url = httpx.URL(GOOGLE_AUTH_URL, params=params)

    return {"authorize_url": str(url), "state": state}


@router.get("/callback")
async def gcp_callback(
    code: str,
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Handle GCP OAuth2 callback — exchange code for tokens and store securely."""
    import json

    from app.utils.encryption import decrypt as dec

    frontend_url = settings.effective_frontend_url

    if not settings.gcp_oauth_client_id:
        raise HTTPException(status_code=503, detail="GCP OAuth not configured")

    # Decode user from encrypted state (browser redirect has no JWT)
    try:
        state_data = json.loads(dec(state))
        user_id = state_data["user_id"]
    except Exception as e:
        logger.error("GCP callback state decrypt failed", error=str(e), state_len=len(state))
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    try:
        # Exchange authorization code for tokens
        redirect_uri = settings.effective_gcp_oauth_redirect_uri
        logger.info("GCP token exchange", redirect_uri=redirect_uri)
        async with httpx.AsyncClient(timeout=30.0) as client:
            token_response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.gcp_oauth_client_id,
                    "client_secret": settings.gcp_oauth_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

            if token_response.status_code != 200:
                logger.error("GCP token exchange failed", status=token_response.status_code, body=token_response.text, redirect_uri=redirect_uri)
                raise HTTPException(status_code=400, detail=f"Token exchange failed: {token_response.text}")

            tokens = token_response.json()
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")
            granted_scopes = tokens.get("scope", "")

            if not refresh_token:
                raise HTTPException(
                    status_code=400,
                    detail="No refresh token received. Please try again — Google may not have returned offline access.",
                )

            # Get user's Google profile
            userinfo_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            google_user = userinfo_resp.json() if userinfo_resp.status_code == 200 else {}

            # List user's GCP projects (non-fatal if it fails)
            projects = []
            try:
                projects_resp = await client.get(
                    GOOGLE_PROJECTS_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"filter": "lifecycleState:ACTIVE"},
                )
                if projects_resp.status_code == 200:
                    projects = [
                        {"id": p["projectId"], "name": p.get("name", p["projectId"])}
                        for p in projects_resp.json().get("projects", [])
                    ]
            except Exception as e:
                logger.warning("Failed to list GCP projects", error=str(e))

        # Encrypt and store the refresh token
        encrypted_token = encrypt(refresh_token)

        # Upsert — update if exists, insert if not
        existing = await db.execute(
            select(CloudCredential).where(
                CloudCredential.user_id == user_id,
                CloudCredential.provider == "gcp",
            )
        )
        cred = existing.scalar_one_or_none()

        if cred:
            cred.encrypted_refresh_token = encrypted_token
            cred.email = google_user.get("email")
            cred.scopes = granted_scopes
            cred.is_active = True
            if not cred.project_id and projects:
                cred.project_id = projects[0]["id"]
        else:
            cred = CloudCredential(
                user_id=user_id,
                provider="gcp",
                project_id=projects[0]["id"] if projects else None,
                email=google_user.get("email"),
                encrypted_refresh_token=encrypted_token,
                scopes=granted_scopes,
                is_active=True,
            )
            db.add(cred)

        await db.commit()

        logger.info("GCP connected", user=user_id, email=google_user.get("email"), projects=len(projects))
        return RedirectResponse(url=f"{frontend_url}/?gcp=connected")

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        pg_host = settings.postgres_host
        logger.error("GCP callback failed", error=str(e), user=user_id, pg_host=pg_host, traceback=tb)
        raise HTTPException(status_code=500, detail=f"GCP connection failed: {str(e)} | pg_host={pg_host} | trace: {tb[-500:]}")


@router.get("/status")
async def gcp_status(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if the user has connected their GCP project."""
    user_id = user.get("sub", user.get("login", ""))

    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "gcp",
            CloudCredential.is_active == True,
        )
    )
    cred = result.scalar_one_or_none()

    if not cred:
        return {"connected": False}

    return {
        "connected": True,
        "email": cred.email,
        "project_id": cred.project_id,
        "scopes": cred.scopes,
        "connected_at": cred.connected_at.isoformat() if cred.connected_at else None,
        "last_used_at": cred.last_used_at.isoformat() if cred.last_used_at else None,
    }


@router.get("/projects")
async def list_gcp_projects(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the user's active GCP projects using their stored credentials."""
    user_id = user.get("sub", user.get("login", ""))

    # Get a fresh access token
    token_result = await get_user_gcp_access_token(user_id, db)
    if not token_result:
        raise HTTPException(status_code=404, detail="No GCP connection found. Please connect first.")

    access_token, _ = token_result

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_PROJECTS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"filter": "lifecycleState:ACTIVE"},
            timeout=15,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Failed to list GCP projects")

    projects = [
        {
            "id": p["projectId"],
            "name": p.get("name", p["projectId"]),
            "number": p.get("projectNumber", ""),
        }
        for p in resp.json().get("projects", [])
    ]

    return {"projects": projects, "count": len(projects)}


@router.post("/select-project")
async def select_gcp_project(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the selected GCP project for the user."""
    user_id = user.get("sub", user.get("login", ""))

    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "gcp",
            CloudCredential.is_active == True,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="No GCP connection found. Please connect first.")

    cred.project_id = project_id
    await db.commit()

    return {"status": "updated", "project_id": project_id}


@router.post("/disconnect")
async def gcp_disconnect(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect user's GCP project and delete all stored credentials."""
    user_id = user.get("sub", user.get("login", ""))

    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "gcp",
        )
    )
    cred = result.scalar_one_or_none()

    if cred:
        # Revoke the token at Google's end
        try:
            refresh_token = decrypt(cred.encrypted_refresh_token)
            async with httpx.AsyncClient() as client:
                await client.post(GOOGLE_REVOKE_URL, params={"token": refresh_token})
        except Exception as e:
            logger.warning("Failed to revoke GCP token at Google", error=str(e))

        # Hard delete — not soft delete
        await db.delete(cred)
        await db.commit()
        logger.info("GCP disconnected", user=user_id)

    return {"status": "disconnected"}


async def get_user_gcp_access_token(user_id: str, db: AsyncSession) -> tuple[str, str] | None:
    """Get a fresh access token for the user's GCP project.

    Returns (access_token, project_id) or None if not connected.
    """
    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "gcp",
            CloudCredential.is_active == True,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        return None

    # Decrypt refresh token and exchange for a fresh access token
    try:
        refresh_token = decrypt(cred.encrypted_refresh_token)
    except Exception as e:
        logger.error("Failed to decrypt GCP refresh token", user=user_id, error=str(e))
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.gcp_oauth_client_id,
                "client_secret": settings.gcp_oauth_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )

    if resp.status_code != 200:
        logger.error("GCP token refresh failed", user=user_id, status=resp.status_code)
        return None

    access_token = resp.json().get("access_token")
    if not access_token:
        return None

    # Update last_used_at (naive datetime to match DB column)
    from datetime import datetime
    cred.last_used_at = datetime.utcnow()
    await db.commit()

    return access_token, cred.project_id or ""
