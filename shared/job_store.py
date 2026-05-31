"""
Job Store — Redis-backed async task persistence
================================================
Solves the core gap: "when an agent runs long, how does the client poll results?"

Every background task gets a job_id. State transitions:
  pending → running → done | error

TTL: 1 hour (configurable). Clients poll GET /tasks/{job_id}.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import redis.asyncio as aioredis
from pydantic import BaseModel, Field

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

JOB_TTL_SECONDS = 3600  # 1 hour


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class JobRecord(BaseModel):
    """Full job lifecycle record stored in Redis."""

    job_id: str
    status: JobStatus = JobStatus.PENDING
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    user_input: Optional[str] = None
    session_id: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_seconds: Optional[float] = None

    def to_redis(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_redis(cls, raw: str) -> "JobRecord":
        return cls.model_validate_json(raw)


class JobStore:
    """Redis-backed store for async background jobs."""

    KEY_PREFIX = "job:"

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url or settings.redis_url

    async def _get_redis(self) -> aioredis.Redis:
        return await aioredis.from_url(self._redis_url, decode_responses=True)

    def _key(self, job_id: str) -> str:
        return f"{self.KEY_PREFIX}{job_id}"

    # ──────────────────────────────────────────────
    # Write operations
    # ──────────────────────────────────────────────

    async def create(
        self,
        job_id: str,
        user_input: str,
        session_id: str,
    ) -> JobRecord:
        """Create a new pending job record."""
        record = JobRecord(
            job_id=job_id,
            status=JobStatus.PENDING,
            user_input=user_input,
            session_id=session_id,
        )
        await self._save(record)
        logger.info("[JobStore] Created job %s", job_id)
        return record

    async def mark_running(self, job_id: str) -> None:
        """Transition job to running state."""
        record = await self.get(job_id)
        if record:
            record.status = JobStatus.RUNNING
            record.started_at = datetime.now(timezone.utc).isoformat()
            await self._save(record)

    async def mark_done(
        self,
        job_id: str,
        result: Any,
        execution_time_seconds: float,
    ) -> None:
        """Transition job to done with result payload."""
        record = await self.get(job_id)
        if record:
            record.status = JobStatus.DONE
            record.result = result
            record.execution_time_seconds = execution_time_seconds
            record.completed_at = datetime.now(timezone.utc).isoformat()
            await self._save(record)
            logger.info(
                "[JobStore] Job %s completed in %.2fs", job_id, execution_time_seconds
            )

    async def mark_error(self, job_id: str, error: str) -> None:
        """Transition job to error state."""
        record = await self.get(job_id)
        if record:
            record.status = JobStatus.ERROR
            record.error = error
            record.completed_at = datetime.now(timezone.utc).isoformat()
            await self._save(record)
            logger.error("[JobStore] Job %s failed: %s", job_id, error)

    # ──────────────────────────────────────────────
    # Read operations
    # ──────────────────────────────────────────────

    async def get(self, job_id: str) -> Optional[JobRecord]:
        """Retrieve a job record by ID. Returns None if not found."""
        redis = await self._get_redis()
        try:
            raw = await redis.get(self._key(job_id))
            if not raw:
                return None
            return JobRecord.from_redis(raw)
        finally:
            await redis.aclose()

    async def exists(self, job_id: str) -> bool:
        redis = await self._get_redis()
        try:
            return bool(await redis.exists(self._key(job_id)))
        finally:
            await redis.aclose()

    # ──────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────

    async def _save(self, record: JobRecord) -> None:
        redis = await self._get_redis()
        try:
            await redis.setex(
                self._key(record.job_id),
                JOB_TTL_SECONDS,
                record.to_redis(),
            )
        finally:
            await redis.aclose()


# Process-wide singleton
_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """Get or create the singleton job store."""
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store
