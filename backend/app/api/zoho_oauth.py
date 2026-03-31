"""Zoho OAuth2 endpoints — Connect user's Zoho Sprints account."""

from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.config import get_settings
from app.models.database import CloudCredential, get_db
from app.utils.encryption import decrypt, encrypt

logger = structlog.get_logger()
settings = get_settings()
router = APIRouter(prefix="/auth/zoho", tags=["zoho-auth"])

ZOHO_AUTH_URL = "https://accounts.zoho.com/oauth/v2/auth"
ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
ZOHO_USERINFO_URL = "https://accounts.zoho.com/oauth/user/info"


@router.get("/login")
async def zoho_login(user: dict = Depends(get_current_user)):
    """Start Zoho OAuth flow."""
    if not settings.zoho_client_id:
        raise HTTPException(status_code=503, detail="Zoho OAuth not configured. Set ZOHO_CLIENT_ID.")

    import json

    from app.utils.encryption import encrypt as enc

    user_id = user.get("sub", user.get("login", ""))
    state = enc(json.dumps({"user_id": user_id, "flow": "zoho_connect"}))

    params = {
        "client_id": settings.zoho_client_id,
        "redirect_uri": settings.effective_zoho_redirect_uri,
        "response_type": "code",
        "scope": "ZohoSprints.teams.READ,ZohoSprints.projects.READ,ZohoSprints.sprints.READ,ZohoSprints.items.READ",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    return {"authorize_url": f"{ZOHO_AUTH_URL}?{urlencode(params)}", "state": state}


@router.get("/callback")
async def zoho_callback(
    code: str = Query(...),
    state: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """Zoho OAuth callback — exchange code for tokens."""
    # Decode user from state
    import json
    try:
        state_data = json.loads(decrypt(state))
        user_id = state_data["user_id"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ZOHO_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.zoho_client_id,
                "client_secret": settings.zoho_client_secret,
                "redirect_uri": settings.effective_zoho_redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Zoho token exchange failed: {resp.text[:200]}")

    tokens = resp.json()
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")

    # Get user info
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            ZOHO_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    zoho_email = ""
    if user_resp.status_code == 200:
        zoho_user = user_resp.json()
        zoho_email = zoho_user.get("Email", "")

    # Check for existing credential
    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "zoho",
        )
    )
    cred = result.scalar_one_or_none()

    # Zoho only sends refresh_token on first consent; reuse existing if available
    if not refresh_token:
        if cred and cred.encrypted_refresh_token:
            logger.info("Zoho re-auth without refresh token, keeping existing", user=user_id)
            refresh_token = decrypt(cred.encrypted_refresh_token)
        else:
            raise HTTPException(
                status_code=400,
                detail="No refresh token from Zoho. Revoke app access at accounts.zoho.com and retry.",
            )

    encrypted_token = encrypt(refresh_token)

    if cred:
        cred.encrypted_refresh_token = encrypted_token
        cred.email = zoho_email
        cred.is_active = True
    else:
        cred = CloudCredential(
            user_id=user_id,
            provider="zoho",
            email=zoho_email,
            encrypted_refresh_token=encrypted_token,
            scopes=tokens.get("scope", ""),
            is_active=True,
        )
        db.add(cred)

    await db.commit()
    logger.info("Zoho connected", user=user_id, email=zoho_email)

    frontend_url = settings.effective_frontend_url
    return RedirectResponse(url=f"{frontend_url}/?zoho=connected")


@router.get("/status")
async def zoho_status(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check Zoho connection status."""
    user_id = user.get("sub", user.get("login", ""))
    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "zoho",
            CloudCredential.is_active == True,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        return {"connected": False}
    return {"connected": True, "email": cred.email}


@router.post("/disconnect")
async def zoho_disconnect(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect Zoho."""
    user_id = user.get("sub", user.get("login", ""))
    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "zoho",
        )
    )
    cred = result.scalar_one_or_none()
    if cred:
        await db.delete(cred)
        await db.commit()
    return {"status": "disconnected"}


async def get_zoho_access_token(user_id: str, db: AsyncSession) -> str | None:
    """Get a fresh Zoho access token using stored refresh token."""
    result = await db.execute(
        select(CloudCredential).where(
            CloudCredential.user_id == user_id,
            CloudCredential.provider == "zoho",
            CloudCredential.is_active == True,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        return None

    refresh_token = decrypt(cred.encrypted_refresh_token)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ZOHO_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.zoho_client_id,
                "client_secret": settings.zoho_client_secret,
                "grant_type": "refresh_token",
            },
        )

    if resp.status_code != 200:
        return None

    return resp.json().get("access_token")


# ─── Sprints Data Endpoints (for dashboard) ────────────────────────


@router.get("/sprints/active")
async def get_active_sprint_data(
    portal_id: str = "",
    team_id: str = "",
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get active sprint data for the dashboard."""
    user_id = user.get("sub", user.get("login", ""))
    token = await get_zoho_access_token(user_id, db)
    if not token:
        raise HTTPException(status_code=403, detail="Zoho not connected")

    from app.mcp.zoho import ZohoSprintsMCPClient
    client = ZohoSprintsMCPClient(access_token=token)

    # If no portal/team specified, get first available
    if not portal_id:
        portals = await client.get_portals()
        if "error" in portals or not portals.get("portals"):
            return portals
        portal_id = portals["portals"][0]["id"]

    if not team_id:
        teams = await client.get_teams(portal_id)
        if "error" in teams or not teams.get("teams"):
            return teams
        team_id = teams["teams"][0]["id"]

    return await client.get_active_sprint(portal_id, team_id)


@router.get("/portals")
async def get_zoho_portals(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List Zoho portals and teams."""
    user_id = user.get("sub", user.get("login", ""))
    token = await get_zoho_access_token(user_id, db)
    if not token:
        raise HTTPException(status_code=403, detail="Zoho not connected")

    from app.mcp.zoho import ZohoSprintsMCPClient
    client = ZohoSprintsMCPClient(access_token=token)
    return await client.get_portals()
