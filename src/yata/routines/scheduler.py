"""APScheduler tick that launches due routines inside the FastAPI process."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from yata.routines.service import RoutineService

logger = logging.getLogger(__name__)


class RoutineScheduler:
    def __init__(self, service: RoutineService, interval_seconds: int):
        self.service = service
        self.interval_seconds = interval_seconds
        self.scheduler: AsyncIOScheduler | None = None

    async def start(self) -> None:
        await self.service.recover()
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.scheduler.add_job(
            self.service.run_due,
            "interval",
            seconds=self.interval_seconds,
            id="yata-routines",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=self.interval_seconds,
        )
        self.scheduler.start()
        logger.info("routine scheduler started, checking every %s seconds", self.interval_seconds)
        await self.service.run_due()

    async def stop(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        await self.service.cancel()
