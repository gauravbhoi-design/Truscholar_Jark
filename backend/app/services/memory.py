"""Memory Service — Provides context from past interactions to agents.

Three memory layers:
1. Conversation Memory: Recent messages from current/past conversations
2. Analysis Memory: Past agent findings, errors, fixes (long-term, searchable)
3. User Preferences: User-specific context (important services, team info)
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, desc, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    Message,
    Conversation,
    AgentMemory,
    UserPreference,
)

logger = structlog.get_logger()


class MemoryService:
    """Manages all memory layers for the agent system."""

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id

    # ─── Layer 1: Conversation Memory ──────────────────────────────────

    async def get_recent_messages(
        self, conversation_id: uuid.UUID | None = None, limit: int = 10
    ) -> list[dict]:
        """Get recent messages from a conversation or across all conversations."""
        if conversation_id:
            result = await self.db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(desc(Message.created_at))
                .limit(limit)
            )
        else:
            # Get messages from user's most recent conversations
            convos = await self.db.execute(
                select(Conversation.id)
                .where(Conversation.user_id == self.user_id)
                .order_by(desc(Conversation.updated_at))
                .limit(3)
            )
            conv_ids = [c.id for c in convos.scalars()]
            if not conv_ids:
                return []

            result = await self.db.execute(
                select(Message)
                .where(Message.conversation_id.in_(conv_ids))
                .order_by(desc(Message.created_at))
                .limit(limit)
            )

        messages = result.scalars().all()
        return [
            {
                "role": m.role,
                "content": m.content[:500],
                "agent": m.agent_name,
                "created_at": str(m.created_at),
            }
            for m in reversed(messages)
        ]

    async def save_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        agent_name: str | None = None,
        tool_calls: dict | None = None,
        cost_usd: float = 0.0,
    ) -> None:
        """Save a message to conversation history."""
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            agent_name=agent_name,
            tool_calls=tool_calls,
            cost_usd=cost_usd,
        )
        self.db.add(msg)
        await self.db.flush()

    # ─── Layer 2: Analysis Memory (Long-term) ──────────────────────────

    async def store_analysis(
        self,
        title: str,
        content: str,
        category: str = "analysis",
        metadata: dict | None = None,
        importance: int = 5,
        ttl_days: int | None = 30,
    ) -> uuid.UUID:
        """Store an analysis result in long-term memory."""
        memory = AgentMemory(
            user_id=self.user_id,
            category=category,
            title=title,
            content=content[:5000],  # Cap content size
            extra_data=metadata or {},
            importance=importance,
            expires_at=datetime.utcnow() + timedelta(days=ttl_days) if ttl_days else None,
        )
        self.db.add(memory)
        await self.db.flush()
        return memory.id

    async def search_memories(
        self,
        query: str,
        categories: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Search past analyses by keyword matching.

        For production, integrate with Qdrant vector search for semantic matching.
        """
        conditions = [
            AgentMemory.user_id == self.user_id,
            or_(
                AgentMemory.expires_at.is_(None),
                AgentMemory.expires_at > datetime.utcnow(),
            ),
        ]

        if categories:
            conditions.append(AgentMemory.category.in_(categories))

        # Keyword search across title and content
        search_terms = query.lower().split()
        if search_terms:
            keyword_conditions = []
            for term in search_terms[:5]:  # Max 5 terms
                keyword_conditions.append(
                    or_(
                        func.lower(AgentMemory.title).contains(term),
                        func.lower(AgentMemory.content).contains(term),
                    )
                )
            if keyword_conditions:
                conditions.append(or_(*keyword_conditions))

        result = await self.db.execute(
            select(AgentMemory)
            .where(and_(*conditions))
            .order_by(desc(AgentMemory.importance), desc(AgentMemory.created_at))
            .limit(limit)
        )

        memories = result.scalars().all()
        return [
            {
                "id": str(m.id),
                "category": m.category,
                "title": m.title,
                "content": m.content[:300],
                "metadata": m.extra_data,
                "importance": m.importance,
                "created_at": str(m.created_at),
            }
            for m in memories
        ]

    async def get_recent_analyses(self, limit: int = 5) -> list[dict]:
        """Get the most recent analyses regardless of query."""
        result = await self.db.execute(
            select(AgentMemory)
            .where(
                AgentMemory.user_id == self.user_id,
                or_(
                    AgentMemory.expires_at.is_(None),
                    AgentMemory.expires_at > datetime.utcnow(),
                ),
            )
            .order_by(desc(AgentMemory.created_at))
            .limit(limit)
        )

        memories = result.scalars().all()
        return [
            {
                "id": str(m.id),
                "category": m.category,
                "title": m.title,
                "content": m.content[:300],
                "metadata": m.extra_data,
                "created_at": str(m.created_at),
            }
            for m in memories
        ]

    # ─── Layer 3: User Preferences ─────────────────────────────────────

    async def get_preference(self, key: str) -> str | None:
        """Get a user preference value."""
        result = await self.db.execute(
            select(UserPreference).where(
                UserPreference.user_id == self.user_id,
                UserPreference.key == key,
            )
        )
        pref = result.scalar_one_or_none()
        return pref.value if pref else None

    async def set_preference(self, key: str, value: str) -> None:
        """Set a user preference (upsert)."""
        result = await self.db.execute(
            select(UserPreference).where(
                UserPreference.user_id == self.user_id,
                UserPreference.key == key,
            )
        )
        pref = result.scalar_one_or_none()
        if pref:
            pref.value = value
        else:
            pref = UserPreference(user_id=self.user_id, key=key, value=value)
            self.db.add(pref)
        await self.db.flush()

    async def get_all_preferences(self) -> dict[str, str]:
        """Get all user preferences as a dict."""
        result = await self.db.execute(
            select(UserPreference).where(UserPreference.user_id == self.user_id)
        )
        prefs = result.scalars().all()
        return {p.key: p.value for p in prefs}

    # ─── Memory Context Builder ────────────────────────────────────────

    async def build_memory_context(self, query: str) -> str:
        """Build a memory context string to inject into agent system prompts.

        This is the key method — it assembles relevant memories into a
        context block that agents receive alongside the user's query.
        """
        sections = []

        # 1. Relevant past analyses
        memories = await self.search_memories(query, limit=3)
        if memories:
            memory_lines = []
            for m in memories:
                memory_lines.append(f"- [{m['category']}] {m['title']} ({m['created_at'][:10]}): {m['content']}")
            sections.append("## Past Analyses\n" + "\n".join(memory_lines))

        # 2. User preferences
        prefs = await self.get_all_preferences()
        if prefs:
            pref_lines = [f"- {k}: {v}" for k, v in prefs.items()]
            sections.append("## User Context\n" + "\n".join(pref_lines))

        if not sections:
            return ""

        return "--- MEMORY CONTEXT (from previous interactions) ---\n\n" + "\n\n".join(sections) + "\n\n--- END MEMORY CONTEXT ---"
