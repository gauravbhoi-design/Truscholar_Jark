"""WebSocket endpoint for real-time agent streaming."""

import json
import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.services.orchestrator import AgentOrchestrator

logger = structlog.get_logger()
router = APIRouter()


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    """WebSocket endpoint for streaming agent responses in real-time."""
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            query = payload.get("query", "")
            conversation_id = payload.get("conversation_id")
            token = payload.get("token", "dev_local")

            # Simple auth for WS (in production, validate JWT before accept)
            user = {"sub": "ws|user", "email": "ws@user", "name": "WS User", "role": "engineer"}

            orchestrator = AgentOrchestrator(db=None, user=user)

            async for event in orchestrator.process_query_stream(
                query=query, conversation_id=conversation_id
            ):
                await websocket.send_text(json.dumps(event))

            await websocket.send_text(json.dumps({"event": "done", "data": {}}))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error", error=str(e))
        try:
            await websocket.send_text(json.dumps({"event": "error", "data": {"message": str(e)}}))
        except Exception:
            pass
