"""Contributor-owned process launch and actual local resource enforcement."""

import functools
import os
import shutil
import subprocess
import sys
import uuid


@functools.lru_cache(maxsize=1)
def cgroup_available():
    if not shutil.which("systemd-run"):
        return False
    try:
        result = subprocess.run(
            ["systemd-run", "--user", "--quiet", "--scope", "-p", "MemoryMax=16M", "/usr/bin/true"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def executor_command(task_file, task):
    command = [
        sys.executable,
        "-m",
        "research_market.executor",
        str(task_file),
        "--parent-pid",
        str(os.getpid()),
    ]
    if task["kind"] == "cpu" and cgroup_available():
        return [
            "systemd-run",
            "--user",
            "--quiet",
            "--scope",
            "--unit=research-market-" + uuid.uuid4().hex,
            "-p",
            f"MemoryMax={task['memory_mb']}M",
            "-p",
            "MemorySwapMax=0",
            "-p",
            f"CPUQuota={task['cpu_cores'] * 100}%",
            *command,
            "--cgroup-memory",
        ]
    return command
