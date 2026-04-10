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

ZOHO_AUTH_URL = "https://accounts.zoho.in/oauth/v2/auth"
ZOHO_TOKEN_URL = "https://accounts.zoho.in/oauth/v2/token"
ZOHO_USERINFO_URL = "https://accounts.zoho.in/oauth/user/info"


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

    tokens = resp.json()
    logger.info("Zoho token exchange response", status=resp.status_code, keys=list(tokens.keys()), redirect_uri=settings.effective_zoho_redirect_uri)

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Zoho token exchange failed: {resp.text[:200]}")

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")

    if not access_token:
        logger.error("Zoho token exchange returned no access_token", response=tokens)
        raise HTTPException(status_code=400, detail=f"Zoho returned no access token: {tokens}")

    # Get user info — Zoho APIs require the "Zoho-oauthtoken" scheme,
    # NOT the standard "Bearer".
    zoho_email = ""
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            ZOHO_USERINFO_URL,
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        )
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
                detail="No refresh token from Zoho. Revoke app access at accounts.zoho.in and retry.",
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


@router.get("/debug/exact")
async def zoho_debug_exact(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hit the exact URL captured from the Zoho Sprints web UI with our
    OAuth token. If this returns 200, OAuth works on /zsapi/ endpoints
    and we just need to find the right list endpoint. If it returns
    7404 or 401, /zsapi/ is cookie-only and we need a different API.
    """
    import httpx

    user_id = user.get("sub", user.get("login", ""))
    token = await get_zoho_access_token(user_id, db)
    if not token:
        return {"error": "Zoho not connected"}

    headers_variants = {
        "Zoho-oauthtoken": {"Authorization": f"Zoho-oauthtoken {token}"},
        "Bearer": {"Authorization": f"Bearer {token}"},
        "Zoho-authtoken": {"Authorization": f"Zoho-authtoken {token}"},  # legacy
    }

    # Three candidate URLs of increasing specificity.
    # 1. The exact URL from the user's DevTools capture.
    # 2. A simpler team-level URL.
    # 3. A top-level portals URL that Zoho's legacy API docs mention.
    urls = [
        "https://sprints.zoho.in/zsapi/team/60009511678/projects/16176000000006001/priority/?action=data&index=1&range=250",
        "https://sprints.zoho.in/zsapi/team/60009511678/settings/?action=banners",
        "https://sprints.zoho.in/zsapi/team/?action=data",
        "https://sprints.zoho.in/zsapi/portals/?action=data",
        "https://sprints.zoho.in/zsapi/myteam/?action=data",
        "https://sprints.zoho.in/zsapi/teams/?action=data",
    ]

    results = []
    async with httpx.AsyncClient(timeout=10) as http:
        for url in urls:
            for scheme, hdrs in headers_variants.items():
                try:
                    resp = await http.get(url, headers=hdrs)
                    results.append({
                        "url": url.replace("https://sprints.zoho.in/zsapi", "…"),
                        "auth": scheme,
                        "status": resp.status_code,
                        "body": resp.text[:200],
                    })
                except Exception as e:
                    results.append({
                        "url": url.replace("https://sprints.zoho.in/zsapi", "…"),
                        "auth": scheme,
                        "error": str(e)[:150],
                    })

    # Classify: anything that's NOT 7404 is interesting
    interesting = [r for r in results if "7404" not in r.get("body", "")]

    return {
        "token_preview": f"{token[:10]}…{token[-4:]}" if token else None,
        "total_attempts": len(results),
        "interesting": interesting,
    }


@router.get("/debug")
async def zoho_debug(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Diagnostic endpoint that walks the full chain (portals → teams →
    sprints) and reports each step's raw result so we can see exactly
    where Zoho integration is failing.

    Also probes several candidate Zoho REST API base URLs to find one
    that responds correctly — useful when an account lives in a region
    other than the configured default.
    """
    import httpx

    user_id = user.get("sub", user.get("login", ""))
    token = await get_zoho_access_token(user_id, db)
    if not token:
        return {"step": "token", "ok": False, "error": "Zoho not connected"}

    # ── First: probe a matrix of (host, path_prefix) combinations ──
    # 7404 means Zoho couldn't match the URL shape. We need to find the
    # right combination of host and path prefix. Zoho Projects uses
    # /restapi/; Zoho Sprints might use /zsapi/, /restapi/, or the
    # unified /sprints/v1/ gateway on www.zohoapis.*.
    hosts = [
        "https://sprintsapi.zoho.in",
        "https://sprintsapi.zoho.com",
        "https://sprintsapi.zoho.eu",
        "https://sprints.zoho.in",
        "https://sprints.zoho.com",
        "https://www.zohoapis.in",
        "https://www.zohoapis.com",
    ]
    path_prefixes = [
        "/zsapi",
        "/zsapi/latest",
        "/zsapi/v1",
        "/restapi",
        "/restapi/v1",
        "/sprints/v1",
        "",  # no prefix
    ]
    # Endpoint shapes under each prefix. Zoho Sprints' UI calls them
    # "Projects" now (v2), so try both the old `portals`/`teams` terms
    # and the new `projects` term.
    endpoint_suffixes = [
        "/portals/",
        "/projects/",
        "/teams/",
        "/portals",
        "/projects",
    ]

    headers = {"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/json"}
    probe_results = []
    working_base = None

    # Zoho Sprints requires ?action=<name> on every call. Without it,
    # Zoho returns 7404 "Given URL is wrong" even for correct paths.
    async with httpx.AsyncClient(timeout=8) as http:
        for host in hosts:
            for prefix in path_prefixes:
                for suffix in endpoint_suffixes:
                    url = f"{host}{prefix}{suffix}"
                    try:
                        resp = await http.get(url, headers=headers, params={"action": "data"})
                    except Exception as e:
                        probe_results.append({"url": url, "error": str(e)[:150]})
                        continue

                    body = resp.text[:150]
                    probe_results.append({
                        "url": f"{url}?action=data",
                        "status": resp.status_code,
                        "body": body,
                    })
                    # A 200 is the goal. A 401 or 403 also means the URL
                    # shape is correct (Zoho parsed it) but auth failed —
                    # still useful signal. We prefer 200 but record the
                    # first non-7404 as a strong candidate.
                    if resp.status_code == 200 and not working_base:
                        working_base = f"{host}{prefix}"
                    elif (
                        resp.status_code in (401, 403)
                        and "7404" not in body
                        and not working_base
                    ):
                        working_base = f"{host}{prefix}"

    # Keep only the interesting probe results (non-7404) in the response
    # so the JSON isn't overwhelming. 7404 results are counted instead.
    interesting = [p for p in probe_results if "7404" not in p.get("body", "")]
    total_7404 = len(probe_results) - len(interesting)

    # ── Then: walk the chain on the working base (or configured one) ──
    from app.mcp.zoho import ZohoSprintsMCPClient
    client = ZohoSprintsMCPClient(access_token=token)
    if working_base:
        # Override the instance base for this single diagnostic walk
        import app.mcp.zoho as zmod
        original_base = zmod.ZOHO_SPRINTS_API
        zmod.ZOHO_SPRINTS_API = working_base
        try:
            portals = await client.get_portals()
        finally:
            zmod.ZOHO_SPRINTS_API = original_base
    else:
        portals = await client.get_portals()

    chain: dict = {
        "configured_base": settings.zoho_sprints_api_base,
        "working_base": working_base,
        "total_probes": len(probe_results),
        "probes_returning_7404": total_7404,
        "interesting_probes": interesting,  # Only non-7404 responses
    }

    if "error" in portals or not portals.get("portals"):
        chain.update({"step": "portals", "ok": False, "result": portals})
        return chain

    portal_id = portals["portals"][0]["id"]
    teams = await client.get_teams(portal_id)
    if "error" in teams or not teams.get("teams"):
        chain.update({"step": "teams", "ok": False, "portal_id": portal_id, "result": teams})
        return chain

    team_id = teams["teams"][0]["id"]
    sprints = await client.get_sprints(portal_id, team_id)
    chain.update({
        "step": "sprints",
        "ok": True,
        "portal_id": portal_id,
        "team_id": team_id,
        "portals_count": len(portals.get("portals", [])),
        "teams_count": len(teams.get("teams", [])),
        "sprints_count": len(sprints.get("sprints", [])),
        "sprint_statuses": [s.get("status") for s in sprints.get("sprints", [])][:20],
        "first_sprint": sprints.get("sprints", [{}])[0] if sprints.get("sprints") else None,
    })
    return chain
