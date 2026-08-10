"""Durable ingestion worker: consumes Redis-queued jobs and runs the pipeline.

Run with: ``python -m jat_api.ingestion.worker``

The worker only receives object references (never host paths) and treats all
parsed content as untrusted data. Reliability is best-effort at this milestone:
jobs popped without a processed terminal state remain ``pending``/intermediate
and are re-dispatchable; a production queue must add acknowledgement/redrive
semantics (see docs/RAG.md).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import cast

import structlog

from jat_api.config import get_settings
from jat_api.db import Database, RedisClient
from jat_api.ingestion.jobs import job_from_json
from jat_api.ingestion.pipeline import process_ingestion_job
from jat_api.observability.logging import configure_logging
from jat_api.rag.providers import create_embedding_provider
from jat_api.storage import LocalObjectStore

logger = structlog.get_logger(__name__)

POLL_TIMEOUT_SECONDS = 5


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.database_url)
    redis = RedisClient(settings.redis_url)
    object_store = LocalObjectStore.for_settings(settings)
    embedder = create_embedding_provider(
        settings.embedding_provider,
        endpoint=getattr(settings, "embedding_endpoint", None) or settings.model_endpoint,
        model=getattr(settings, "embedding_model", None),
    )
    logger.info("ingestion_worker_started", queue=settings.ingestion_queue)
    try:
        while True:
            item = await cast(
                "Awaitable[list[str] | None]",
                redis.client.blpop([settings.ingestion_queue], timeout=POLL_TIMEOUT_SECONDS),
            )
            if item is None:
                continue
            _, raw = item
            try:
                job = job_from_json(raw if isinstance(raw, str) else raw.decode("utf-8"))
            except (ValueError, json.JSONDecodeError) as error:
                logger.error("ingestion_job_malformed", error=str(error))
                continue
            outcome = await process_ingestion_job(
                job,
                session_factory=database.session_factory,
                object_store=object_store,
                embedder=embedder,
                settings=settings,
            )
            logger.info(
                "ingestion_job_finished", document_id=outcome.document_id, status=outcome.status
            )
    finally:
        await redis.close()
        await database.close()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:  # pragma: no cover - manual shutdown path
        pass


if __name__ == "__main__":
    main()
