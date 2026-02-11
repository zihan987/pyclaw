from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

from croniter import croniter


@dataclass
class Schedule:
    kind: str  # cron, every, at
    expr: str = ""
    every_ms: int = 0
    at_ms: int = 0


@dataclass
class Payload:
    message: str
    deliver: bool = False
    channel: str = ""
    to: str = ""


@dataclass
class JobState:
    last_run_at_ms: int = 0
    last_status: str = ""
    last_error: str = ""


@dataclass
class CronJob:
    id: str
    name: str
    enabled: bool
    schedule: Schedule
    payload: Payload
    delete_after_run: bool = False
    state: JobState = field(default_factory=JobState)


class CronService:
    def __init__(self, store_path: str) -> None:
        self.store_path = Path(store_path)
        self.jobs: List[CronJob] = []
        self.on_job: Optional[Callable[[CronJob], Awaitable[str]]] = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._start_time = time.time()

    async def start(self, stop_event: asyncio.Event) -> None:
        self._start_time = time.time()
        await self._load()
        self._task = asyncio.create_task(self._tick_loop(stop_event))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def add_job(self, job: CronJob) -> None:
        async with self._lock:
            self.jobs.append(job)
            await self._save()

    async def list_jobs(self) -> List[CronJob]:
        async with self._lock:
            return list(self.jobs)

    async def remove_job(self, job_id: str) -> bool:
        async with self._lock:
            for i, job in enumerate(self.jobs):
                if job.id == job_id:
                    del self.jobs[i]
                    await self._save()
                    return True
        return False

    async def enable_job(self, job_id: str, enabled: bool) -> bool:
        async with self._lock:
            for job in self.jobs:
                if job.id == job_id:
                    job.enabled = enabled
                    await self._save()
                    return True
        return False

    async def _tick_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            now_ms = int(time.time() * 1000)
            async with self._lock:
                for job in list(self.jobs):
                    if not job.enabled:
                        continue
                    if job.schedule.kind == "cron":
                        if self._cron_due(job, now_ms):
                            await self._run_job(job)
                    elif job.schedule.kind == "every":
                        if job.schedule.every_ms > 0 and now_ms >= job.state.last_run_at_ms + job.schedule.every_ms:
                            await self._run_job(job)
                    elif job.schedule.kind == "at":
                        if job.schedule.at_ms > 0 and now_ms >= job.schedule.at_ms:
                            job.enabled = False
                            await self._run_job(job)
            await asyncio.sleep(1)

    def _cron_due(self, job: CronJob, now_ms: int) -> bool:
        if not job.schedule.expr:
            return False
        base = job.state.last_run_at_ms / 1000 if job.state.last_run_at_ms else self._start_time
        itr = croniter(job.schedule.expr, base)
        next_time = itr.get_next(float)
        return now_ms >= int(next_time * 1000)

    async def _run_job(self, job: CronJob) -> None:
        if self.on_job is None:
            return

        try:
            result = await self.on_job(job)
            job.state.last_status = "ok"
            job.state.last_error = ""
        except Exception as exc:
            job.state.last_status = "error"
            job.state.last_error = str(exc)
        job.state.last_run_at_ms = int(time.time() * 1000)

        if job.delete_after_run:
            self.jobs = [j for j in self.jobs if j.id != job.id]

        await self._save()

    async def _load(self) -> None:
        if not self.store_path.exists():
            return
        raw = self.store_path.read_text(encoding="utf-8")
        if not raw.strip():
            return
        data = json.loads(raw)
        self.jobs = [self._from_dict(item) for item in data]

    async def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data = [self._to_dict(job) for job in self.jobs]
        self.store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _from_dict(data: dict) -> CronJob:
        schedule = Schedule(
            kind=data.get("schedule", {}).get("kind", ""),
            expr=data.get("schedule", {}).get("expr", ""),
            every_ms=data.get("schedule", {}).get("every_ms", 0),
            at_ms=data.get("schedule", {}).get("at_ms", 0),
        )
        payload = Payload(
            message=data.get("payload", {}).get("message", ""),
            deliver=data.get("payload", {}).get("deliver", False),
            channel=data.get("payload", {}).get("channel", ""),
            to=data.get("payload", {}).get("to", ""),
        )
        state = JobState(
            last_run_at_ms=data.get("state", {}).get("last_run_at_ms", 0),
            last_status=data.get("state", {}).get("last_status", ""),
            last_error=data.get("state", {}).get("last_error", ""),
        )
        return CronJob(
            id=data.get("id", ""),
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
            schedule=schedule,
            payload=payload,
            delete_after_run=data.get("delete_after_run", False),
            state=state,
        )

    @staticmethod
    def _to_dict(job: CronJob) -> dict:
        return {
            "id": job.id,
            "name": job.name,
            "enabled": job.enabled,
            "schedule": {
                "kind": job.schedule.kind,
                "expr": job.schedule.expr,
                "every_ms": job.schedule.every_ms,
                "at_ms": job.schedule.at_ms,
            },
            "payload": {
                "message": job.payload.message,
                "deliver": job.payload.deliver,
                "channel": job.payload.channel,
                "to": job.payload.to,
            },
            "delete_after_run": job.delete_after_run,
            "state": {
                "last_run_at_ms": job.state.last_run_at_ms,
                "last_status": job.state.last_status,
                "last_error": job.state.last_error,
            },
        }


import contextlib
