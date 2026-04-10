"""GitHub OAuth authentication — users sign in with GitHub and grant repo access."""

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import get_settings
from app.models.schemas import UserRole

logger = structlog.get_logger()
settings = get_settings()
security = HTTPBearer(auto_error=False)

# GitHub OAuth endpoints
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_USER_EMAILS_URL = "https://api.github.com/user/emails"

# GitHub OAuth scopes — what the user grants access to
GITHUB_SCOPES = [
    "read:user",        # Read user profile
    "user:email",       # Read email addresses
    "repo",             # Full access to private and public repos
    "read:org",         # Read org membership
    "workflow",         # Access GitHub Actions workflows
]


def build_github_authorize_url(state: str | None = None) -> dict:
    """Build the GitHub OAuth authorization URL.

    The user is redirected here to sign in and select which repos to grant access.
    """
    state = state or secrets.token_urlsafe(32)

    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.effective_github_callback_url,
        "scope": " ".join(GITHUB_SCOPES),
        "state": state,
        "allow_signup": "true",
    }

    return {
        "url": f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}",
        "state": state,
    }


async def exchange_code_for_token(code: str) -> dict:
    """Exchange the OAuth authorization code for a GitHub access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.effective_github_callback_url,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            logger.error("GitHub OAuth error", error=data["error"], desc=data.get("error_description"))
            raise HTTPException(status_code=400, detail=data.get("error_description", data["error"]))

        return data  # Contains access_token, scope, token_type


async def fetch_github_user(access_token: str) -> dict:
    """Fetch the authenticated user's GitHub profile and emails."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    async with httpx.AsyncClient() as client:
        # Fetch user profile
        user_resp = await client.get(GITHUB_USER_URL, headers=headers, timeout=10)
        user_resp.raise_for_status()
        user_data = user_resp.json()

        # Fetch primary email (may be private)
        email = user_data.get("email")
        if not email:
            email_resp = await client.get(GITHUB_USER_EMAILS_URL, headers=headers, timeout=10)
            if email_resp.status_code == 200:
                emails = email_resp.json()
                primary = next((e for e in emails if e.get("primary")), None)
                email = primary["email"] if primary else (emails[0]["email"] if emails else None)

        # Fetch user's repos to know what they have
        repos_resp = await client.get(
            "https://api.github.com/user/repos",
            headers=headers,
            params={"per_page": 100, "sort": "updated"},
            timeout=15,
        )
        repos = []
        if repos_resp.status_code == 200:
            repos = [
                {
                    "full_name": r["full_name"],
                    "private": r["private"],
                    "language": r.get("language"),
                    "default_branch": r.get("default_branch", "main"),
                    "url": r["html_url"],
                }
                for r in repos_resp.json()
            ]

        # Fetch org memberships
        orgs_resp = await client.get(
            "https://api.github.com/user/orgs",
            headers=headers,
            timeout=10,
        )
        orgs = []
        if orgs_resp.status_code == 200:
            orgs = [o["login"] for o in orgs_resp.json()]

        return {
            "github_id": user_data["id"],
            "login": user_data["login"],
            "name": user_data.get("name") or user_data["login"],
            "email": email,
            "avatar_url": user_data.get("avatar_url"),
            "bio": user_data.get("bio"),
            "company": user_data.get("company"),
            "public_repos": user_data.get("public_repos", 0),
            "repos": repos,
            "orgs": orgs,
        }


def create_jwt_token(
    user_data: dict,
    github_access_token: str,
    db_id: str | None = None,
    role: str = "engineer",
) -> str:
    """Create a JWT token containing user info and the GitHub access token.

    The GitHub token is embedded so the backend can make API calls on behalf
    of the user when analyzing their repos. db_id (the persisted User.id UUID
    as a string) is embedded so authenticated routes can join against the
    Conversations / Plans / Messages tables.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_data["github_id"]),
        "login": user_data["login"],
        "name": user_data["name"],
        "email": user_data.get("email"),
        "avatar_url": user_data.get("avatar_url"),
        "role": role,
        "db_id": db_id,
        "github_token": github_access_token,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def upsert_user_on_login(user_data: dict, db) -> "User":  # type: ignore[name-defined]
    """Create or update the persisted User row for a freshly authenticated user.

    Keyed by `auth0_sub` (the JWT `sub` claim, which is the GitHub user ID
    string or `google_<id>` for GCP sign-ins). Returns the User row so the
    caller can embed `id` into the JWT.

    The very first user to sign up is automatically promoted to admin so the
    admin panel is reachable without a manual DB poke.
    """
    from sqlalchemy import func, select

    from app.models.database import User

    sub = str(user_data["github_id"])
    email = user_data.get("email") or f"{user_data['login']}@users.noreply.github.com"
    name = user_data.get("name") or user_data["login"]
    # The users.last_login_at column is TIMESTAMP WITHOUT TIME ZONE
    # (matches the rest of the schema), so we store a naive UTC datetime.
    now_naive = datetime.now(UTC).replace(tzinfo=None)

    # Primary lookup: by auth0_sub (set on every fresh login).
    result = await db.execute(select(User).where(User.auth0_sub == sub))
    user = result.scalar_one_or_none()

    # Fallback: a row with this email may already exist from an older code
    # path that didn't set auth0_sub. Adopt it instead of trying to INSERT
    # and tripping the unique-email constraint.
    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.auth0_sub = sub

    if user:
        user.email = email
        user.name = name
        user.login = user_data.get("login")
        user.avatar_url = user_data.get("avatar_url")
        user.last_login_at = now_naive
        user.login_count = (user.login_count or 0) + 1
        user.is_active = True
    else:
        # First user becomes admin so the admin panel is bootstrappable.
        existing_count = await db.scalar(select(func.count(User.id))) or 0
        role = "admin" if existing_count == 0 else "engineer"

        user = User(
            auth0_sub=sub,
            email=email,
            name=name,
            login=user_data.get("login"),
            avatar_url=user_data.get("avatar_url"),
            role=role,
            last_login_at=now_naive,
            login_count=1,
            is_active=True,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> dict:
    """Validate JWT token and return user claims including GitHub token."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials

    # Dev mode: accept simple tokens for local testing
    if settings.environment == "development" and token.startswith("dev_"):
        return {
            "sub": "dev|local",
            "login": "dev-user",
            "email": "dev@localhost",
            "name": "Dev User",
            "role": "admin",
            "github_token": settings.github_token,  # Use fallback token in dev
        }

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )

        if datetime.fromtimestamp(payload["exp"], tz=UTC) < datetime.now(UTC):
            raise HTTPException(status_code=401, detail="Token expired")

        return payload

    except JWTError as e:
        logger.warning("JWT validation failed", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_role(*roles: UserRole):
    """Dependency that enforces role-based access."""

    async def _check_role(user: dict = Depends(get_current_user)) -> dict:
        user_role = user.get("role", "viewer")
        if user_role not in [r.value for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user_role}' not authorized. Required: {[r.value for r in roles]}",
            )
        return user

    return _check_role
