"""Zadania w tle: jeden wątek roboczy, jedno zadanie naraz (spec Planu 5 §2.2).

Zadanie może zostać przerwane (`stop` → `Job.should_stop`/`check`) i może zapytać UI
(`Job.ask` → zdarzenie z `job_id`, odpowiedź przez `JobRunner.answer`). Analizę APK da się
porzucić (`abandon`): wątek kończy się sam, a nowe zadanie startuje od razu.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from admenot.app.errors import AppError, report_error
from admenot.app.events import Emitter


class Stopped(Exception):
    """Zadanie przerwane przez `stop()`."""


@dataclass
class Job:
    id: str
    kind: str
    emitter: Emitter
    done: threading.Event = field(default_factory=threading.Event)
    _stop: threading.Event = field(default_factory=threading.Event)
    _answers: queue.Queue = field(default_factory=queue.Queue)

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def check(self) -> None:
        if self._stop.is_set():
            raise Stopped

    def ask(self, event: str, detail: dict) -> str | None:
        self.emitter.emit(event, {"job_id": self.id, **detail})
        while not self._stop.is_set():
            try:
                return self._answers.get(timeout=0.2)
            except queue.Empty:
                continue
        return None


class JobRunner:
    def __init__(self, emitter: Emitter, sync: bool = False) -> None:
        self._emitter = emitter
        self._sync = sync
        self._lock = threading.Lock()
        self._current: Job | None = None
        self._count = 0

    def start(self, kind: str, fn: Callable[[Job], None]) -> str:
        with self._lock:
            if self._current is not None:
                raise AppError("busy", self._current.kind)
            self._count += 1
            job = Job(f"job-{self._count}", kind, self._emitter)
            self._current = job
        if self._sync:
            self._run(job, fn)
        else:
            threading.Thread(target=self._run, args=(job, fn), daemon=True,
                              name=f"admenot-{kind}").start()
        return job.id

    def _run(self, job: Job, fn: Callable[[Job], None]) -> None:
        try:
            fn(job)
        except Stopped:
            pass
        except Exception as exc:  # noqa: BLE001 — każdy błąd zadania trafia do UI
            self._emitter.emit("job:error", {"job_id": job.id, "kind": job.kind,
                                              **report_error(exc)})
        finally:
            with self._lock:
                if self._current is job:
                    self._current = None
            self._emitter.emit("job:end", {"job_id": job.id, "kind": job.kind})
            job.done.set()

    def current(self) -> Job | None:
        with self._lock:
            return self._current

    def _match(self, job_id: str | None) -> Job | None:
        job = self.current()
        return job if job is not None and job_id in (None, job.id) else None

    def stop(self, job_id: str | None = None) -> bool:
        job = self._match(job_id)
        if job is None:
            return False
        job._stop.set()
        return True

    def answer(self, job_id: str, value: str) -> bool:
        job = self._match(job_id)
        if job is None:
            return False
        job._answers.put(value)
        return True

    def wait(self, timeout: float) -> bool:
        job = self.current()
        return True if job is None else job.done.wait(timeout)

    def abandon(self, job_id: str) -> bool:
        with self._lock:
            job = self._current
            if job is None or job.id != job_id:
                return False
            job._stop.set()
            self._current = None
        return True
