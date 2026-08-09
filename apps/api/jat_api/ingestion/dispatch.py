"""Replaceable ingestion dispatch boundary.

- ``inline`` (default, development): runs the ingestion pipeline synchronously after
  the upload commit, so local dev and tests need no queue infrastructure.
- ``redis``: pushes jobs onto a Redis list consumed by ``python -m jat_api.ingestion.worker``
  for durable, asynchronous processing.
- ``local``: records jobs in memory only; a test/CI fixture, not a processing path.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

import structlog
from redis.asyncio import Redis

from jat_api.ingestion.jobs import IngestionJob, job_to_payload

logger = structlog.get_logger(__name__)


class IngestionDispatcher(Protocol):
    async def dispatch(self, job: IngestionJob) -> None: ...


class LocalIngestionDispatcher:
    """Development/test fixture recording jobs; production must use a durable adapter."""

    def __init__(self) -> None:
        self.jobs: list[IngestionJob] = []

    async def dispatch(self, job: IngestionJob) -> None:
        self.jobs.append(job)


class InlineIngestionDispatcher:
    """Runs the pipeline in-request; deterministic for development and contract tests."""

    def __init__(self, runner: Callable[[IngestionJob], Awaitable[None]]) -> None:
        self._runner = runner

    async def dispatch(self, job: IngestionJob) -> None:
        await self._runner(job)


class RedisIngestionDispatcher:
    """Durable dispatch onto a Redis list consumed by ingestion workers."""

    def __init__(self, client: Redis, queue_key: str) -> None:
        self.client = client
        self.queue_key = queue_key

    async def dispatch(self, job: IngestionJob) -> None:
        # redis-py stubs union sync/async return types; the async client always awaits.
        payload = json.dumps(job_to_payload(job))
        await cast("Awaitable[Any]", self.client.rpush(self.queue_key, payload))
        logger.info(
            "ingestion_job_dispatched",
            document_id=str(job.document_id),
            queue=self.queue_key,
        )
