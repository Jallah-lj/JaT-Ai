"""Replaceable ingestion dispatch boundary; local implementation records jobs only."""
from typing import Protocol
from services.workers.job_contracts import IngestionJob

class IngestionDispatcher(Protocol):
    async def dispatch(self, job: IngestionJob) -> None: ...

class LocalIngestionDispatcher:
    """Development fixture; production must replace with a durable queue adapter."""
    def __init__(self) -> None:
        self.jobs: list[IngestionJob] = []
    async def dispatch(self, job: IngestionJob) -> None:
        self.jobs.append(job)
