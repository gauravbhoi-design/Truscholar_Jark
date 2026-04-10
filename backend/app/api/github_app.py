"""GitHub App — authentication, installation management, and webhook handling.

This module converts TruJark from a GitHub OAuth App to a full GitHub App,
providing:
- JWT-based app authentication (RS256 signed with private key)
- Installation access tokens for per-org/user API calls
- Webhook endpoint for receiving GitHub events
- Installation setup/callback flow
- Coexists with existing OAuth sign-in flow
"""

import hashlib
import hmac
import time
from datetime import UTC, datetime

import httpx
import jwt as pyjwt  # PyJWT for RS256 signing
import structlog
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import GitHubAppInstallation, WebhookEvent, get_db

logger = structlog.get_logger()
settings = get_settings()
router = APIRouter(prefix="/github-app", tags=["github-app"])

GITHUB_API = "https://api.github.com"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  App-Level JWT Authentication (RS256)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _generate_app_jwt() -> str:
    """Generate a short-lived JWT for GitHub App authentication.

    This JWT is used to authenticate as the GitHub App itself (not as a user
    or installation). It's valid for up to 10 minutes.
    """
    private_key = settings.github_app_private_key_content
    if not private_key:
        raise ValueError("GitHub App private key not configured")

    now = int(time.time())
    payload = {
        "iat": now - 60,           # Issued at (60s clock skew buffer)
        "exp": now + (9 * 60),     # Expires in 9 minutes (max 10)
        "iss": settings.github_app_id,
    }

    return pyjwt.encode(payload, private_key, algorithm="RS256")


async def get_installation_access_token(installation_id: int) -> dict:
    """Get an installation access token for making API calls on behalf of an installation.

    Returns:
        dict with 'token', 'expires_at', 'permissions', 'repository_selection'
    """
    app_jwt = _generate_app_jwt()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github.v3+json",
            },
        )

        if resp.status_code != 201:
            logger.error(
                "Failed to get installation token",
                installation_id=installation_id,
                status=resp.status_code,
                body=resp.text,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to get GitHub installation token: {resp.status_code}",
            )

        data = resp.json()
        return {
            "token": data["token"],
            "expires_at": data["expires_at"],
            "permissions": data.get("permissions", {}),
            "repository_selection": data.get("repository_selection"),
        }


async def get_installation_token_for_repo(repo_full_name: str, db: AsyncSession) -> str | None:
    """Find the installation that has access to a repo and return its token.

    Tries to match by account login (org/user that owns the repo).
    """
    owner = repo_full_name.split("/")[0]

    result = await db.execute(
        select(GitHubAppInstallation).where(
            GitHubAppInstallation.account_login == owner,
            GitHubAppInstallation.is_active == True,
        )
    )
    installation = result.scalar_one_or_none()

    if not installation:
        return None

    token_data = await get_installation_access_token(installation.installation_id)
    return token_data["token"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Installation Management Routes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/install")
async def install_app():
    """Redirect user to install the GitHub App on their org/account."""
    if not settings.github_app_name:
        raise HTTPException(status_code=503, detail="GitHub App not configured")

    install_url = f"https://github.com/apps/{settings.github_app_name}/installations/new"
    return {"install_url": install_url}


@router.get("/setup")
async def setup_callback(
    installation_id: int = Query(...),
    setup_action: str = Query("install"),
    db: AsyncSession = Depends(get_db),
):
    """GitHub App post-installation setup callback.

    GitHub redirects here after a user installs or updates the app.
    We fetch the installation details and store them.
    """
    try:
        app_jwt = _generate_app_jwt()

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GITHUB_API}/app/installations/{installation_id}",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )

        if resp.status_code != 200:
            logger.error("Failed to fetch installation", status=resp.status_code)
            raise HTTPException(status_code=502, detail="Failed to fetch installation details")

        data = resp.json()
        account = data["account"]

        # Upsert installation record
        result = await db.execute(
            select(GitHubAppInstallation).where(
                GitHubAppInstallation.installation_id == installation_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.account_login = account["login"]
            existing.account_type = account["type"]
            existing.account_id = account["id"]
            existing.account_avatar_url = account.get("avatar_url")
            existing.repository_selection = data.get("repository_selection", "all")
            existing.permissions = data.get("permissions")
            existing.events = data.get("events")
            existing.is_active = True
            existing.suspended_at = None
        else:
            installation = GitHubAppInstallation(
                installation_id=installation_id,
                account_login=account["login"],
                account_type=account["type"],
                account_id=account["id"],
                account_avatar_url=account.get("avatar_url"),
                repository_selection=data.get("repository_selection", "all"),
                permissions=data.get("permissions"),
                events=data.get("events"),
                is_active=True,
            )
            db.add(installation)

        await db.commit()

        logger.info(
            "GitHub App installed",
            installation_id=installation_id,
            account=account["login"],
            action=setup_action,
        )

        # Redirect to frontend dashboard
        frontend_url = settings.effective_frontend_url
        return RedirectResponse(url=f"{frontend_url}/?github_app=installed&account={account['login']}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Setup callback failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Setup failed: {str(e)}")


@router.get("/installations")
async def list_installations(db: AsyncSession = Depends(get_db)):
    """List all active GitHub App installations."""
    result = await db.execute(
        select(GitHubAppInstallation)
        .where(GitHubAppInstallation.is_active == True)
        .order_by(GitHubAppInstallation.installed_at.desc())
    )
    installations = result.scalars().all()

    return {
        "total": len(installations),
        "installations": [
            {
                "installation_id": i.installation_id,
                "account_login": i.account_login,
                "account_type": i.account_type,
                "account_avatar_url": i.account_avatar_url,
                "repository_selection": i.repository_selection,
                "permissions": i.permissions,
                "events": i.events,
                "installed_at": str(i.installed_at),
                "is_active": i.is_active,
            }
            for i in installations
        ],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Webhook Endpoint
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _verify_webhook_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify the webhook payload signature using HMAC-SHA256."""
    if not settings.github_app_webhook_secret:
        logger.warning("Webhook secret not configured — skipping verification")
        return True

    if not signature_header:
        return False

    expected = "sha256=" + hmac.new(
        settings.github_app_webhook_secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


@router.post("/webhook")
async def webhook_handler(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: str = Header(None, alias="X-GitHub-Delivery"),
):
    """Receive and process GitHub webhook events.

    Handles all subscribed events: push, pull_request, issues,
    workflow_run, installation, etc.
    """
    body = await request.body()

    # Verify signature
    if not _verify_webhook_signature(body, x_hub_signature_256 or ""):
        logger.warning("Webhook signature verification failed", delivery=x_github_delivery)
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    action = payload.get("action")
    installation_data = payload.get("installation", {})
    installation_id = installation_data.get("id")
    repo_data = payload.get("repository", {})
    sender_data = payload.get("sender", {})

    logger.info(
        "Webhook received",
        event=x_github_event,
        action=action,
        delivery=x_github_delivery,
        installation_id=installation_id,
        repo=repo_data.get("full_name"),
        sender=sender_data.get("login"),
    )

    # Log the webhook event
    event_record = WebhookEvent(
        event_type=x_github_event,
        action=action,
        installation_id=installation_id,
        repository=repo_data.get("full_name"),
        sender=sender_data.get("login"),
        payload_summary=_extract_payload_summary(x_github_event, action, payload),
        processed=False,
    )
    db.add(event_record)

    # Route to specific handler
    handler = WEBHOOK_HANDLERS.get(x_github_event)
    if handler:
        try:
            await handler(payload, action, db)
            event_record.processed = True
        except Exception as e:
            logger.error("Webhook handler failed", event=x_github_event, error=str(e))

    await db.commit()

    return {"status": "ok", "event": x_github_event, "action": action}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Webhook Event Handlers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _handle_installation(payload: dict, action: str | None, db: AsyncSession):
    """Handle installation created/deleted/suspended/unsuspended events."""
    installation = payload["installation"]
    account = installation["account"]
    installation_id = installation["id"]

    if action == "created":
        result = await db.execute(
            select(GitHubAppInstallation).where(
                GitHubAppInstallation.installation_id == installation_id
            )
        )
        existing = result.scalar_one_or_none()

        if not existing:
            new_install = GitHubAppInstallation(
                installation_id=installation_id,
                account_login=account["login"],
                account_type=account["type"],
                account_id=account["id"],
                account_avatar_url=account.get("avatar_url"),
                repository_selection=installation.get("repository_selection", "all"),
                permissions=installation.get("permissions"),
                events=installation.get("events"),
                sender_login=payload.get("sender", {}).get("login"),
                is_active=True,
            )
            db.add(new_install)

        logger.info("App installed", account=account["login"], installation_id=installation_id)

    elif action == "deleted":
        result = await db.execute(
            select(GitHubAppInstallation).where(
                GitHubAppInstallation.installation_id == installation_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.is_active = False
        logger.info("App uninstalled", account=account["login"])

    elif action == "suspend":
        result = await db.execute(
            select(GitHubAppInstallation).where(
                GitHubAppInstallation.installation_id == installation_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.suspended_at = datetime.now(UTC)
        logger.info("App suspended", account=account["login"])

    elif action == "unsuspend":
        result = await db.execute(
            select(GitHubAppInstallation).where(
                GitHubAppInstallation.installation_id == installation_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.suspended_at = None
        logger.info("App unsuspended", account=account["login"])


async def _handle_installation_repositories(payload: dict, action: str | None, db: AsyncSession):
    """Handle when repos are added/removed from the installation."""
    installation_id = payload["installation"]["id"]

    result = await db.execute(
        select(GitHubAppInstallation).where(
            GitHubAppInstallation.installation_id == installation_id
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        added = [r["full_name"] for r in payload.get("repositories_added", [])]
        removed = [r["full_name"] for r in payload.get("repositories_removed", [])]

        current = existing.selected_repositories or []
        updated = [r for r in current if r not in removed] + added
        existing.selected_repositories = updated
        existing.repository_selection = payload["installation"].get("repository_selection", "selected")

        logger.info(
            "Installation repos updated",
            installation_id=installation_id,
            added=added,
            removed=removed,
        )


async def _handle_push(payload: dict, action: str | None, db: AsyncSession):
    """Handle push events — new commits pushed to a branch."""
    repo = payload.get("repository", {}).get("full_name", "")
    ref = payload.get("ref", "")
    commits = payload.get("commits", [])
    pusher = payload.get("pusher", {}).get("name", "")

    logger.info(
        "Push event",
        repo=repo,
        ref=ref,
        commits=len(commits),
        pusher=pusher,
    )


async def _handle_pull_request(payload: dict, action: str | None, db: AsyncSession):
    """Handle pull request events — opened, closed, merged, review_requested, etc."""
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Pull request event",
        repo=repo,
        action=action,
        pr_number=pr.get("number"),
        title=pr.get("title"),
        user=pr.get("user", {}).get("login"),
        merged=pr.get("merged", False),
    )


async def _handle_issues(payload: dict, action: str | None, db: AsyncSession):
    """Handle issue events — opened, closed, labeled, etc."""
    issue = payload.get("issue", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Issue event",
        repo=repo,
        action=action,
        issue_number=issue.get("number"),
        title=issue.get("title"),
    )


async def _handle_issue_comment(payload: dict, action: str | None, db: AsyncSession):
    """Handle issue/PR comment events."""
    comment = payload.get("comment", {})
    issue = payload.get("issue", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Comment event",
        repo=repo,
        action=action,
        issue_number=issue.get("number"),
        commenter=comment.get("user", {}).get("login"),
    )


async def _handle_workflow_run(payload: dict, action: str | None, db: AsyncSession):
    """Handle workflow run events — completed, requested, etc."""
    run = payload.get("workflow_run", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Workflow run event",
        repo=repo,
        action=action,
        workflow=run.get("name"),
        status=run.get("status"),
        conclusion=run.get("conclusion"),
        branch=run.get("head_branch"),
    )


async def _handle_workflow_job(payload: dict, action: str | None, db: AsyncSession):
    """Handle workflow job events — queued, in_progress, completed."""
    job = payload.get("workflow_job", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Workflow job event",
        repo=repo,
        action=action,
        job_name=job.get("name"),
        status=job.get("status"),
        conclusion=job.get("conclusion"),
    )


async def _handle_check_run(payload: dict, action: str | None, db: AsyncSession):
    """Handle check run events — created, completed, rerequested."""
    check_run = payload.get("check_run", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Check run event",
        repo=repo,
        action=action,
        name=check_run.get("name"),
        status=check_run.get("status"),
        conclusion=check_run.get("conclusion"),
    )


async def _handle_check_suite(payload: dict, action: str | None, db: AsyncSession):
    """Handle check suite events."""
    check_suite = payload.get("check_suite", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Check suite event",
        repo=repo,
        action=action,
        status=check_suite.get("status"),
        conclusion=check_suite.get("conclusion"),
    )


async def _handle_deployment(payload: dict, action: str | None, db: AsyncSession):
    """Handle deployment events."""
    deployment = payload.get("deployment", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Deployment event",
        repo=repo,
        environment=deployment.get("environment"),
        ref=deployment.get("ref"),
        creator=deployment.get("creator", {}).get("login"),
    )


async def _handle_deployment_status(payload: dict, action: str | None, db: AsyncSession):
    """Handle deployment status events."""
    status = payload.get("deployment_status", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Deployment status event",
        repo=repo,
        state=status.get("state"),
        environment=status.get("environment"),
    )


async def _handle_release(payload: dict, action: str | None, db: AsyncSession):
    """Handle release events — published, created, edited, etc."""
    release = payload.get("release", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Release event",
        repo=repo,
        action=action,
        tag=release.get("tag_name"),
        name=release.get("name"),
        prerelease=release.get("prerelease"),
    )


async def _handle_create(payload: dict, action: str | None, db: AsyncSession):
    """Handle branch/tag creation events."""
    repo = payload.get("repository", {}).get("full_name", "")
    ref_type = payload.get("ref_type", "")
    ref = payload.get("ref", "")

    logger.info("Create event", repo=repo, ref_type=ref_type, ref=ref)


async def _handle_delete(payload: dict, action: str | None, db: AsyncSession):
    """Handle branch/tag deletion events."""
    repo = payload.get("repository", {}).get("full_name", "")
    ref_type = payload.get("ref_type", "")
    ref = payload.get("ref", "")

    logger.info("Delete event", repo=repo, ref_type=ref_type, ref=ref)


async def _handle_pull_request_review(payload: dict, action: str | None, db: AsyncSession):
    """Handle PR review events — submitted, dismissed, edited."""
    review = payload.get("review", {})
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "PR review event",
        repo=repo,
        action=action,
        pr_number=pr.get("number"),
        state=review.get("state"),
        reviewer=review.get("user", {}).get("login"),
    )


async def _handle_pull_request_review_comment(payload: dict, action: str | None, db: AsyncSession):
    """Handle PR review comment events."""
    comment = payload.get("comment", {})
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "PR review comment event",
        repo=repo,
        action=action,
        pr_number=pr.get("number"),
        commenter=comment.get("user", {}).get("login"),
    )


async def _handle_status(payload: dict, action: str | None, db: AsyncSession):
    """Handle commit status events."""
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Status event",
        repo=repo,
        state=payload.get("state"),
        context=payload.get("context"),
        sha=payload.get("sha", "")[:8],
    )


async def _handle_repository(payload: dict, action: str | None, db: AsyncSession):
    """Handle repository events — created, deleted, archived, etc."""
    repo = payload.get("repository", {})

    logger.info(
        "Repository event",
        action=action,
        repo=repo.get("full_name"),
        private=repo.get("private"),
    )


async def _handle_member(payload: dict, action: str | None, db: AsyncSession):
    """Handle collaborator added/removed events."""
    member = payload.get("member", {})
    repo = payload.get("repository", {}).get("full_name", "")

    logger.info(
        "Member event",
        repo=repo,
        action=action,
        member=member.get("login"),
    )


async def _handle_ping(payload: dict, action: str | None, db: AsyncSession):
    """Handle ping event — sent when webhook is first configured."""
    logger.info("Ping received", zen=payload.get("zen"), hook_id=payload.get("hook_id"))


# Event handler registry
WEBHOOK_HANDLERS = {
    "ping": _handle_ping,
    "installation": _handle_installation,
    "installation_repositories": _handle_installation_repositories,
    "push": _handle_push,
    "pull_request": _handle_pull_request,
    "pull_request_review": _handle_pull_request_review,
    "pull_request_review_comment": _handle_pull_request_review_comment,
    "issues": _handle_issues,
    "issue_comment": _handle_issue_comment,
    "workflow_run": _handle_workflow_run,
    "workflow_job": _handle_workflow_job,
    "check_run": _handle_check_run,
    "check_suite": _handle_check_suite,
    "deployment": _handle_deployment,
    "deployment_status": _handle_deployment_status,
    "release": _handle_release,
    "create": _handle_create,
    "delete": _handle_delete,
    "status": _handle_status,
    "repository": _handle_repository,
    "member": _handle_member,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Webhook Events Query API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/events")
async def list_webhook_events(
    event_type: str | None = None,
    repo: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Query stored webhook events for dashboards and debugging."""
    query = select(WebhookEvent).order_by(WebhookEvent.created_at.desc())

    if event_type:
        query = query.where(WebhookEvent.event_type == event_type)
    if repo:
        query = query.where(WebhookEvent.repository == repo)

    query = query.limit(min(limit, 200))
    result = await db.execute(query)
    events = result.scalars().all()

    return {
        "total": len(events),
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "action": e.action,
                "installation_id": e.installation_id,
                "repository": e.repository,
                "sender": e.sender,
                "payload_summary": e.payload_summary,
                "processed": e.processed,
                "created_at": str(e.created_at),
            }
            for e in events
        ],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Utilities
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _extract_payload_summary(event_type: str, action: str | None, payload: dict) -> dict:
    """Extract key fields from a webhook payload for storage."""
    summary: dict = {}

    if event_type == "push":
        summary = {
            "ref": payload.get("ref"),
            "commits_count": len(payload.get("commits", [])),
            "pusher": payload.get("pusher", {}).get("name"),
            "head_commit": payload.get("head_commit", {}).get("message", "")[:200],
        }
    elif event_type == "pull_request":
        pr = payload.get("pull_request", {})
        summary = {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "state": pr.get("state"),
            "user": pr.get("user", {}).get("login"),
            "merged": pr.get("merged"),
            "base": pr.get("base", {}).get("ref"),
            "head": pr.get("head", {}).get("ref"),
        }
    elif event_type == "issues":
        issue = payload.get("issue", {})
        summary = {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "state": issue.get("state"),
            "labels": [l.get("name") for l in issue.get("labels", [])],
        }
    elif event_type == "workflow_run":
        run = payload.get("workflow_run", {})
        summary = {
            "workflow": run.get("name"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "branch": run.get("head_branch"),
            "run_number": run.get("run_number"),
        }
    elif event_type == "deployment":
        dep = payload.get("deployment", {})
        summary = {
            "environment": dep.get("environment"),
            "ref": dep.get("ref"),
            "task": dep.get("task"),
        }
    elif event_type == "deployment_status":
        ds = payload.get("deployment_status", {})
        summary = {
            "state": ds.get("state"),
            "environment": ds.get("environment"),
            "description": ds.get("description", "")[:200],
        }
    elif event_type == "release":
        rel = payload.get("release", {})
        summary = {
            "tag": rel.get("tag_name"),
            "name": rel.get("name"),
            "prerelease": rel.get("prerelease"),
            "draft": rel.get("draft"),
        }
    elif event_type in ("check_run", "check_suite"):
        check = payload.get(event_type, {})
        summary = {
            "name": check.get("name"),
            "status": check.get("status"),
            "conclusion": check.get("conclusion"),
        }
    elif event_type == "installation":
        inst = payload.get("installation", {})
        summary = {
            "installation_id": inst.get("id"),
            "account": inst.get("account", {}).get("login"),
            "repository_selection": inst.get("repository_selection"),
        }

    return summary
