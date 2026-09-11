from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any


FIELD_PATTERN = re.compile(r"(\w+)=(.*?)(?=\s+\w+=|$)")
MAX_JOBS = 100


class SlurmCollector:
    """Collect scheduler data through standard Slurm command-line tools."""

    def __init__(self, enabled: bool = False, node_name: str | None = None) -> None:
        self.node_name = node_name or "localhost"
        self._scontrol = shutil.which("scontrol") if enabled else None
        self._squeue = shutil.which("squeue") if enabled else None

    @property
    def available(self) -> bool:
        return bool(self._scontrol or self._squeue)

    @staticmethod
    def _run(command: list[str]) -> str | None:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    @staticmethod
    def _integer(value: str | None) -> int | None:
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    @staticmethod
    def _text(value: str | None, limit: int) -> str | None:
        return value[:limit] if value else None

    def collect(self) -> dict[str, Any] | None:
        if not self.available:
            return None

        node_output = (
            self._run([self._scontrol, "--oneliner", "show", "node", self.node_name])
            if self._scontrol
            else None
        )
        job_output = (
            self._run(
                [
                    self._squeue,
                    "--noheader",
                    "--nodelist",
                    self.node_name,
                    "--states=RUNNING",
                    "--format=%i|%u|%j|%T",
                ]
            )
            if self._squeue
            else None
        )
        if node_output is None and job_output is None:
            return None

        fields = dict(FIELD_PATTERN.findall(node_output or ""))
        job_lines = [line.strip() for line in (job_output or "").splitlines() if line.strip()]
        jobs = None
        if job_output is not None:
            jobs = []
            for line in job_lines[:MAX_JOBS]:
                parts = [part.strip() for part in line.split("|", 3)]
                if len(parts) == 4:
                    jobs.append(
                        {
                            "job_id": parts[0][:64],
                            "user": parts[1][:128],
                            "name": parts[2][:256],
                            "state": parts[3][:64],
                        }
                    )

        reason = fields.get("Reason")
        if reason and reason.lower() in {"none", "n/a", "(null)"}:
            reason = None

        return {
            "node_name": (fields.get("NodeName") or self.node_name)[:255],
            "node_state": self._text(fields.get("State"), 128),
            "reason": self._text(reason, 500),
            "allocated_cpus": self._integer(fields.get("CPUAlloc")),
            "total_cpus": self._integer(fields.get("CPUTot")),
            "running_jobs": jobs,
            "jobs_truncated": jobs is not None and len(job_lines) > MAX_JOBS,
        }
