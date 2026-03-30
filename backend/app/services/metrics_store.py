"""Metrics Store — Persists metric snapshots to PostgreSQL + Qdrant vector DB.

Ensures engineering metrics data is never lost across sessions.
- PostgreSQL: Structured snapshots for dashboard queries and trend analysis.
- Qdrant: Vector embeddings for semantic search by AI agents.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import MetricDataPoint, MetricSnapshot

logger = structlog.get_logger()
settings = get_settings()

# Qdrant collection name for metrics
METRICS_COLLECTION = "engineering_metrics"
VECTOR_SIZE = 384  # Using a lightweight embedding model


class MetricsStore:
    """Persists and retrieves engineering metrics from PostgreSQL + Qdrant."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._qdrant = None

    # ─── Qdrant Client ─────────────────────────────────────────────────

    async def _get_qdrant(self):
        """Lazy-initialize Qdrant client and ensure collection exists."""
        if self._qdrant is not None:
            return self._qdrant

        try:
            from qdrant_client import AsyncQdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._qdrant = AsyncQdrantClient(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
            )

            # Ensure collection exists
            collections = await self._qdrant.get_collections()
            collection_names = [c.name for c in collections.collections]

            if METRICS_COLLECTION not in collection_names:
                await self._qdrant.create_collection(
                    collection_name=METRICS_COLLECTION,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                logger.info("Created Qdrant collection", collection=METRICS_COLLECTION)

            return self._qdrant
        except Exception as e:
            logger.warning("Qdrant not available, using PostgreSQL only", error=str(e))
            self._qdrant = None
            return None

    # ─── Embedding ─────────────────────────────────────────────────────

    def _generate_embedding(self, text: str) -> list[float]:
        """Generate a simple deterministic embedding from text.

        For production, replace with a proper embedding model (e.g., sentence-transformers).
        This uses a hash-based approach as a fallback that still enables basic vector search.
        """
        # Create a deterministic hash-based vector
        # Each dimension is derived from a different hash seed
        vector = []
        for i in range(VECTOR_SIZE):
            h = hashlib.sha256(f"{text}:{i}".encode()).hexdigest()
            # Convert first 8 hex chars to a float between -1 and 1
            val = (int(h[:8], 16) / 0xFFFFFFFF) * 2 - 1
            vector.append(val)
        return vector

    def _build_search_text(self, layer: str, metrics_data: dict, team_id: str | None = None) -> str:
        """Build a text representation of metrics for embedding."""
        parts = [f"Engineering metrics {layer} layer"]
        if team_id:
            parts.append(f"team {team_id}")

        if layer == "dora":
            for key in ["deployment_frequency", "lead_time", "change_failure_rate", "recovery_time", "rework_rate"]:
                if key in metrics_data:
                    detail = metrics_data[key]
                    if isinstance(detail, dict):
                        parts.append(f"{key}: tier={detail.get('tier', 'unknown')} value={detail.get('value', 0)}")
        elif layer == "composite":
            parts.append(f"overall_tier={metrics_data.get('overall_tier', 'unknown')}")
            parts.append(f"final_score={metrics_data.get('final_score', 0)}")
        elif layer == "space":
            for dim in ["satisfaction", "performance", "activity", "communication", "efficiency"]:
                if dim in metrics_data:
                    score = metrics_data[dim].get("score", 0) if isinstance(metrics_data[dim], dict) else 0
                    parts.append(f"{dim}: {score}/5")

        return " | ".join(parts)

    # ─── Save Metrics ─────────────────────────────────────────────────

    async def save_snapshot(
        self,
        team_id: uuid.UUID,
        layer: str,
        metrics_data: dict,
        scores: dict | None = None,
        overall_score: float | None = None,
        tier: str | None = None,
        period_days: int = 30,
    ) -> uuid.UUID:
        """Save a metric snapshot to PostgreSQL and Qdrant.

        This is the primary persistence method — call after every metrics computation.
        """
        now = datetime.now(UTC)

        # 1. Save to PostgreSQL
        snapshot = MetricSnapshot(
            team_id=team_id,
            snapshot_date=now,
            layer=layer,
            metrics_data=metrics_data,
            scores=scores,
            overall_score=overall_score,
            tier=tier,
            period_days=period_days,
        )
        self.db.add(snapshot)
        await self.db.flush()

        snapshot_id = snapshot.id
        logger.info("Saved metric snapshot to PostgreSQL", layer=layer, team_id=str(team_id), snapshot_id=str(snapshot_id))

        # 2. Save to Qdrant for vector search
        qdrant = await self._get_qdrant()
        if qdrant:
            try:
                from qdrant_client.models import PointStruct

                search_text = self._build_search_text(layer, metrics_data, str(team_id))
                embedding = self._generate_embedding(search_text)

                point = PointStruct(
                    id=snapshot_id.hex,
                    vector=embedding,
                    payload={
                        "snapshot_id": str(snapshot_id),
                        "team_id": str(team_id),
                        "layer": layer,
                        "tier": tier,
                        "overall_score": overall_score,
                        "snapshot_date": now.isoformat(),
                        "period_days": period_days,
                        "metrics_summary": self._summarize_metrics(layer, metrics_data),
                        "full_metrics": json.dumps(metrics_data, default=str),
                    },
                )

                await qdrant.upsert(collection_name=METRICS_COLLECTION, points=[point])
                logger.info("Saved metric snapshot to Qdrant", layer=layer, point_id=snapshot_id.hex)

            except Exception as e:
                logger.warning("Failed to save to Qdrant", error=str(e))

        return snapshot_id

    async def save_data_point(
        self,
        team_id: uuid.UUID,
        metric_name: str,
        metric_layer: str,
        value: float,
        unit: str | None = None,
        source: str = "github",
        source_metadata: dict | None = None,
    ) -> None:
        """Save an individual metric data point for granular trend tracking."""
        point = MetricDataPoint(
            team_id=team_id,
            metric_name=metric_name,
            metric_layer=metric_layer,
            value=value,
            unit=unit,
            source=source,
            source_metadata=source_metadata,
            recorded_at=datetime.now(UTC),
        )
        self.db.add(point)
        await self.db.flush()

    async def save_full_dashboard(
        self,
        team_id: uuid.UUID,
        dora_data: dict,
        space_data: dict,
        dx_core4_data: dict,
        ai_cap_data: dict,
        composite_data: dict,
    ) -> dict:
        """Save all 4 layers + composite as separate snapshots in one call."""
        snapshot_ids = {}

        # DORA
        sid = await self.save_snapshot(
            team_id=team_id,
            layer="dora",
            metrics_data=dora_data.get("metrics", dora_data) if isinstance(dora_data, dict) else dora_data,
            overall_score=dora_data.get("overall_score"),
            tier=None,
            period_days=30,
        )
        snapshot_ids["dora"] = str(sid)

        # SPACE
        sid = await self.save_snapshot(
            team_id=team_id,
            layer="space",
            metrics_data=space_data if isinstance(space_data, dict) else {},
            overall_score=space_data.get("overall_score") if isinstance(space_data, dict) else None,
        )
        snapshot_ids["space"] = str(sid)

        # DX Core 4
        sid = await self.save_snapshot(
            team_id=team_id,
            layer="dx_core4",
            metrics_data=dx_core4_data if isinstance(dx_core4_data, dict) else {},
            overall_score=dx_core4_data.get("overall_score") if isinstance(dx_core4_data, dict) else None,
        )
        snapshot_ids["dx_core4"] = str(sid)

        # AI Capabilities
        sid = await self.save_snapshot(
            team_id=team_id,
            layer="ai_capabilities",
            metrics_data=ai_cap_data if isinstance(ai_cap_data, dict) else {},
            overall_score=ai_cap_data.get("normalized_score") if isinstance(ai_cap_data, dict) else None,
        )
        snapshot_ids["ai_capabilities"] = str(sid)

        # Composite
        sid = await self.save_snapshot(
            team_id=team_id,
            layer="composite",
            metrics_data=composite_data if isinstance(composite_data, dict) else {},
            overall_score=composite_data.get("final_score") if isinstance(composite_data, dict) else None,
            tier=composite_data.get("overall_tier") if isinstance(composite_data, dict) else None,
        )
        snapshot_ids["composite"] = str(sid)

        await self.db.commit()
        return snapshot_ids

    # ─── Retrieve Metrics ──────────────────────────────────────────────

    async def get_latest_snapshot(self, team_id: uuid.UUID, layer: str) -> dict | None:
        """Get the most recent snapshot for a team + layer."""
        result = await self.db.execute(
            select(MetricSnapshot)
            .where(
                MetricSnapshot.team_id == team_id,
                MetricSnapshot.layer == layer,
            )
            .order_by(desc(MetricSnapshot.snapshot_date))
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        if not snapshot:
            return None

        return {
            "id": str(snapshot.id),
            "layer": snapshot.layer,
            "metrics_data": snapshot.metrics_data,
            "scores": snapshot.scores,
            "overall_score": snapshot.overall_score,
            "tier": snapshot.tier,
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "period_days": snapshot.period_days,
        }

    async def get_snapshots_history(
        self, team_id: uuid.UUID, layer: str, limit: int = 30
    ) -> list[dict]:
        """Get historical snapshots for trend analysis."""
        result = await self.db.execute(
            select(MetricSnapshot)
            .where(
                MetricSnapshot.team_id == team_id,
                MetricSnapshot.layer == layer,
            )
            .order_by(desc(MetricSnapshot.snapshot_date))
            .limit(limit)
        )
        snapshots = result.scalars().all()
        return [
            {
                "id": str(s.id),
                "overall_score": s.overall_score,
                "tier": s.tier,
                "snapshot_date": s.snapshot_date.isoformat(),
                "metrics_data": s.metrics_data,
            }
            for s in reversed(snapshots)  # Oldest first for charting
        ]

    async def get_data_points(
        self,
        team_id: uuid.UUID,
        metric_name: str,
        days: int = 30,
    ) -> list[dict]:
        """Get individual data points for a specific metric over time."""
        since = datetime.now(UTC) - __import__("datetime").timedelta(days=days)
        result = await self.db.execute(
            select(MetricDataPoint)
            .where(
                MetricDataPoint.team_id == team_id,
                MetricDataPoint.metric_name == metric_name,
                MetricDataPoint.recorded_at >= since,
            )
            .order_by(MetricDataPoint.recorded_at)
        )
        points = result.scalars().all()
        return [
            {
                "value": p.value,
                "unit": p.unit,
                "source": p.source,
                "recorded_at": p.recorded_at.isoformat(),
            }
            for p in points
        ]

    # ─── Vector Search (Qdrant) ────────────────────────────────────────

    async def search_metrics(
        self,
        query: str,
        team_id: str | None = None,
        layer: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Semantic search across stored metric snapshots via Qdrant.

        Used by the AI agent to find relevant historical metrics context.
        """
        qdrant = await self._get_qdrant()
        if not qdrant:
            # Fallback to PostgreSQL keyword search
            return await self._search_postgres_fallback(query, team_id, layer, limit)

        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            embedding = self._generate_embedding(query)

            # Build filter conditions
            conditions = []
            if team_id:
                conditions.append(FieldCondition(key="team_id", match=MatchValue(value=team_id)))
            if layer:
                conditions.append(FieldCondition(key="layer", match=MatchValue(value=layer)))

            search_filter = Filter(must=conditions) if conditions else None  # type: ignore[arg-type]

            results = await qdrant.search(
                collection_name=METRICS_COLLECTION,
                query_vector=embedding,
                query_filter=search_filter,
                limit=limit,
            )

            return [
                {
                    "snapshot_id": hit.payload.get("snapshot_id"),
                    "layer": hit.payload.get("layer"),
                    "tier": hit.payload.get("tier"),
                    "overall_score": hit.payload.get("overall_score"),
                    "snapshot_date": hit.payload.get("snapshot_date"),
                    "metrics_summary": hit.payload.get("metrics_summary"),
                    "score": hit.score,
                }
                for hit in results
            ]

        except Exception as e:
            logger.warning("Qdrant search failed, falling back to PostgreSQL", error=str(e))
            return await self._search_postgres_fallback(query, team_id, layer, limit)

    async def _search_postgres_fallback(
        self, query: str, team_id: str | None, layer: str | None, limit: int
    ) -> list[dict]:
        """Fallback search using PostgreSQL when Qdrant is unavailable."""
        conditions = []
        if team_id:
            conditions.append(MetricSnapshot.team_id == uuid.UUID(team_id))
        if layer:
            conditions.append(MetricSnapshot.layer == layer)

        stmt = select(MetricSnapshot).order_by(desc(MetricSnapshot.snapshot_date)).limit(limit)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        result = await self.db.execute(stmt)
        snapshots = result.scalars().all()

        return [
            {
                "snapshot_id": str(s.id),
                "layer": s.layer,
                "tier": s.tier,
                "overall_score": s.overall_score,
                "snapshot_date": s.snapshot_date.isoformat(),
                "metrics_summary": self._summarize_metrics(s.layer, s.metrics_data),
                "score": 1.0,  # No relevance scoring in fallback
            }
            for s in snapshots
        ]

    # ─── Helpers ───────────────────────────────────────────────────────

    def _summarize_metrics(self, layer: str, data: dict) -> str:
        """Create a human-readable summary of metrics for display."""
        if layer == "dora":
            parts = []
            for key in ["deployment_frequency", "lead_time", "change_failure_rate", "recovery_time", "rework_rate"]:
                detail = data.get(key, {})
                if isinstance(detail, dict):
                    parts.append(f"{key.replace('_', ' ').title()}: {detail.get('label', 'N/A')} ({detail.get('tier', '?')})")
            return " | ".join(parts) if parts else "No DORA data"

        elif layer == "space":
            parts = []
            for dim in ["satisfaction", "performance", "activity", "communication", "efficiency"]:
                dim_data = data.get(dim, {})
                score = dim_data.get("score", 0) if isinstance(dim_data, dict) else 0
                parts.append(f"{dim.title()}: {score}/5")
            return " | ".join(parts)

        elif layer == "composite":
            return f"Score: {data.get('final_score', 0)}/100 | Tier: {data.get('overall_tier', 'unknown')}"

        elif layer == "dx_core4":
            parts = []
            for p in ["speed", "effectiveness", "quality", "business_impact"]:
                p_data = data.get(p, {})
                score = p_data.get("score", 0) if isinstance(p_data, dict) else 0
                parts.append(f"{p.replace('_', ' ').title()}: {score}")
            return " | ".join(parts)

        return json.dumps(data, default=str)[:200]
