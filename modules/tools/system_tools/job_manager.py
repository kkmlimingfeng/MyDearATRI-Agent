"""Bounded background command jobs owned by a conversation."""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


MAX_JOBS = 64
MAX_ACTIVE_JOBS = 16
MAX_BUFFER_BYTES = 512 * 1024
MAX_READ_BYTES = 24 * 1024
JOB_TTL_SECONDS = 24 * 60 * 60


class _OutputBuffer:
    def __init__(self) -> None:
        self.data = bytearray()
        self.total = 0

    @property
    def start(self) -> int:
        return self.total - len(self.data)

    def append(self, chunk: bytes) -> None:
        self.total += len(chunk)
        self.data.extend(chunk)
        if len(self.data) > MAX_BUFFER_BYTES:
            del self.data[: len(self.data) - MAX_BUFFER_BYTES]

    def read(self, offset: int) -> tuple[bytes, int, bool]:
        dropped = offset < self.start
        start = max(offset, self.start)
        end = min(self.total, start + MAX_READ_BYTES)
        left = start - self.start
        right = end - self.start
        return bytes(self.data[left:right]), end, dropped


@dataclass
class _Job:
    id: str
    owner_id: str
    label: str
    process: subprocess.Popen
    created_at: float = field(default_factory=time.time)
    stdout: _OutputBuffer = field(default_factory=_OutputBuffer)
    stderr: _OutputBuffer = field(default_factory=_OutputBuffer)
    stdout_offset: int = 0
    stderr_offset: int = 0
    status: str = "running"
    returncode: int | None = None
    cancel_requested: bool = False
    done: threading.Event = field(default_factory=threading.Event)
    readers: list[threading.Thread] = field(default_factory=list)


class BackgroundJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _owner(value: str | None) -> str:
        return value if isinstance(value, str) and value else "default"

    def start(
        self,
        owner_id: str,
        args: list[str],
        cwd: str,
        environment: dict[str, str],
        label: str = "后台命令",
    ) -> str:
        with self._lock:
            self._prune_locked()
            active = sum(job.status == "running" for job in self._jobs.values())
            if active >= MAX_ACTIVE_JOBS:
                raise RuntimeError(f"后台任务已达到全局上限 {MAX_ACTIVE_JOBS}")
            self._make_room_locked()
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=environment,
                start_new_session=(os.name == "posix"),
                bufsize=0,
            )
            job_id = uuid.uuid4().hex
            job = _Job(
                id=job_id,
                owner_id=self._owner(owner_id),
                label=(label.strip()[:120] if isinstance(label, str) else "") or "后台命令",
                process=process,
            )
            self._jobs[job_id] = job
            for name, stream, buffer in (
                ("stdout", process.stdout, job.stdout),
                ("stderr", process.stderr, job.stderr),
            ):
                if stream is not None:
                    reader = threading.Thread(
                        target=self._capture,
                        args=(job, stream, buffer),
                        name=f"atri-job-{job_id[:8]}-{name}",
                        daemon=True,
                    )
                    job.readers.append(reader)
                    reader.start()
            threading.Thread(
                target=self._reap,
                args=(job,),
                name=f"atri-job-{job_id[:8]}-wait",
                daemon=True,
            ).start()
            return job_id

    def _capture(self, job: _Job, stream, buffer: _OutputBuffer) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                with self._lock:
                    buffer.append(chunk)
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _reap(self, job: _Job) -> None:
        returncode = job.process.wait()
        for reader in job.readers:
            reader.join(timeout=2)
        with self._lock:
            job.returncode = returncode
            if job.cancel_requested:
                job.status = "cancelled"
            else:
                job.status = "completed" if returncode == 0 else "failed"
            job.done.set()

    def _prune_locked(self) -> None:
        cutoff = time.time() - JOB_TTL_SECONDS
        expired = [
            job_id for job_id, job in self._jobs.items()
            if job.status != "running" and job.created_at < cutoff
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)

    def _make_room_locked(self) -> None:
        if len(self._jobs) < MAX_JOBS:
            return
        finished = sorted(
            (job for job in self._jobs.values() if job.status != "running"),
            key=lambda job: job.created_at,
        )
        for job in finished:
            self._jobs.pop(job.id, None)
            if len(self._jobs) < MAX_JOBS:
                return
        raise RuntimeError("后台任务记录已满；请先清理已完成的任务")

    def _get_locked(self, owner_id: str, job_id: str) -> _Job | None:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != self._owner(owner_id):
            return None
        return job

    def list(self, owner_id: str) -> list[dict]:
        with self._lock:
            jobs = sorted(
                (job for job in self._jobs.values() if job.owner_id == self._owner(owner_id)),
                key=lambda job: job.created_at,
                reverse=True,
            )[:30]
            return [self._snapshot(job) for job in jobs]

    @staticmethod
    def _snapshot(job: _Job) -> dict:
        return {
            "id": job.id,
            "label": job.label,
            "status": job.status,
            "returncode": job.returncode,
            "created_at": datetime.fromtimestamp(job.created_at, timezone.utc).isoformat(),
        }

    def output(self, owner_id: str, job_id: str, wait_seconds: int = 0) -> str:
        with self._lock:
            job = self._get_locked(owner_id, job_id)
        if job is None:
            return "后台任务不存在，或当前对话无权访问。"
        try:
            wait = max(0, min(30, int(wait_seconds)))
        except (TypeError, ValueError, OverflowError):
            wait = 0
        if wait:
            job.done.wait(wait)
        with self._lock:
            stdout, job.stdout_offset, stdout_dropped = job.stdout.read(job.stdout_offset)
            stderr, job.stderr_offset, stderr_dropped = job.stderr.read(job.stderr_offset)
            status = job.status
            returncode = job.returncode
        chunks = []
        if stdout_dropped or stderr_dropped:
            chunks.append("[较早的输出已超出保留上限]")
        if stdout:
            chunks.append("[stdout]\n" + stdout.decode("utf-8", errors="replace"))
        if stderr:
            chunks.append("[stderr]\n" + stderr.decode("utf-8", errors="replace"))
        if not chunks:
            chunks.append("(暂无新输出)")
        exit_text = f", exit code {returncode}" if returncode is not None else ""
        chunks.append(f"[status: {status}{exit_text}]")
        return "\n".join(chunks)

    def kill(self, owner_id: str, job_id: str) -> str:
        with self._lock:
            job = self._get_locked(owner_id, job_id)
            if job is None:
                return "后台任务不存在，或当前对话无权访问。"
            if job.status != "running":
                return f"后台任务已结束（{job.status}）。"
            job.cancel_requested = True
            process = job.process
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            pass
        except OSError as exc:
            return f"无法停止后台任务：{exc}"
        if not job.done.wait(2):
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            except OSError:
                pass
            job.done.wait(2)
        with self._lock:
            return f"后台任务已停止（{job.status}）。"

    def stop_all(self) -> None:
        with self._lock:
            jobs = [job for job in self._jobs.values() if job.status == "running"]
        for job in jobs:
            self.kill(job.owner_id, job.id)


job_manager = BackgroundJobManager()
atexit.register(job_manager.stop_all)
