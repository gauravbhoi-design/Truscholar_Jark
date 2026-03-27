"""Slack MCP Client — Notifications, alert routing, channel messages."""

import httpx
import structlog
from app.config import get_settings

logger = structlog.get_logger()


class SlackMCPClient:
    """MCP-compatible client for Slack operations."""

    def __init__(self):
        settings = get_settings()
        self.token = settings.slack_bot_token
        self.base_url = "https://slack.com/api"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def send_message(self, channel: str, text: str, blocks: list | None = None) -> dict:
        """Send a message to a Slack channel."""
        payload = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/chat.postMessage",
                headers=self.headers,
                json=payload,
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error("Slack send failed", error=data.get("error"))
            return data

    async def send_alert(
        self,
        channel: str,
        title: str,
        severity: str,
        details: str,
        agent: str,
    ) -> dict:
        """Send a formatted alert notification."""
        color_map = {"critical": "#FF0000", "high": "#FF6600", "medium": "#FFCC00", "low": "#00CC00"}
        color = color_map.get(severity.lower(), "#808080")

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"DevOps Co-Pilot Alert: {title}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Severity:* {severity.upper()}"},
                    {"type": "mrkdwn", "text": f"*Agent:* {agent}"},
                ],
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": details[:2000]}},
        ]

        return await self.send_message(channel=channel, text=title, blocks=blocks)
