"""Reviewed local profiles. No project-supplied shell commands are executed."""

from __future__ import annotations

import argparse
import json
import math
import os
import resource
import signal
import threading
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--cgroup-memory", action="store_true")
    args = parser.parse_args()
    task_file = Path(args.task)
    task = json.loads(task_file.read_text())
    started = time.monotonic()
    if args.parent_pid:

        def parent_watch():
            while True:
                time.sleep(0.3)
                if not Path(f"/proc/{args.parent_pid}").exists():
                    os.killpg(os.getpgrp(), signal.SIGTERM)

        threading.Thread(target=parent_watch, daemon=True).start()
    os.environ.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    if hasattr(os, "sched_getaffinity"):
        available = sorted(os.sched_getaffinity(0))
        os.sched_setaffinity(0, set(available[: task["cpu_cores"]]))
    # Agent runtime owns its own model process limits; caller always enforces wall time.
    if task["kind"] not in {"agent", "gpu"} and not args.cgroup_memory:
        memory = task["memory_mb"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    cpu_limit = math.ceil(task["budget_seconds"] * task["cpu_cores"] + 2)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit + 1))
    try:
        if task["operation"] == "trefethen_recompute":
            from .trefethen import compute

            artifact = compute(
                task["input"]["mode"],
                task["input"]["start"],
                timeout=max(1, task["budget_seconds"] - 1),
            )
        elif task["operation"] == "research_session":
            from .research_harness import last_session_id, run_research

            brief = (
                task["instruction"]
                + "\nProject context:\n"
                + json.dumps(task.get("research_context", {}))
            )
            workspace = task_file.parent
            session_id = None
            if task.get("resume_from"):
                workspace = task_file.parent.parent / task["resume_from"]
                original = json.loads((workspace / "task.json").read_text())
                if (
                    original["project_id"] != task["project_id"]
                    or original["operation"] != "research_session"
                ):
                    raise ValueError("The saved workspace belongs to different research.")
                session_id = last_session_id(workspace)
                if not session_id:
                    raise ValueError("No native research session is available to continue.")
                brief = (
                    "Continue your saved investigation. Prioritize returning the findings and reproducible evidence already obtained, with remaining leads as requests.\n"
                    + brief
                )
            artifact = run_research(
                workspace, brief, max(1, task["budget_seconds"] - 3), session_id
            )
            artifact["continued_from"] = task.get("resume_from")
        else:
            raise ValueError("No installed executor supports this task operation.")
        own, child = (
            resource.getrusage(resource.RUSAGE_SELF),
            resource.getrusage(resource.RUSAGE_CHILDREN),
        )
        usage = {
            "wall_seconds": time.monotonic() - started,
            "cpu_seconds": own.ru_utime + own.ru_stime + child.ru_utime + child.ru_stime,
            "peak_rss_mb": max(own.ru_maxrss, child.ru_maxrss) / 1024,
            "measurement": "OS process accounting",
            "memory_enforcement": "cgroup v2 MemoryMax; swap disabled"
            if args.cgroup_memory
            else "virtual address-space limit"
            if task["kind"] == "cpu"
            else "reported only",
            "provider_usage": artifact.get("provider_usage"),
            "provider_calls": artifact.get("provider_calls"),
            "harness_invocations": artifact.get("harness_invocations", 0),
            "device": artifact.get("device", "CPU"),
            "cost": None,
        }
        value = {"artifact": artifact, "usage": usage}
        temporary = task_file.parent / "output.tmp"
        temporary.write_text(json.dumps(value, allow_nan=False))
        temporary.replace(task_file.parent / "output.json")
        print(json.dumps({"ok": True}))
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
