"""Scheduler — reads schedules.json and executes tasks via Qwen on time.

The flow:
1. Qwen writes entries to workspace/schedules.json (natural language -> cron)
2. This scheduler checks every 30 seconds if any task is due
3. When due, runs qwen -p "task prompt" and sends result to Telegram
4. One-time tasks (once=true) are removed after execution
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from config import WORK_DIR

logger = logging.getLogger("scheduler")

SCHEDULES_FILE = WORK_DIR / "schedules.json"
CHECK_INTERVAL = 30  # seconds

# Track last execution to avoid double-firing within the same minute
_last_fired: dict[str, str] = {}  # task_id -> "YYYY-MM-DD HH:MM"


def _load_schedules() -> list[dict]:
    if not SCHEDULES_FILE.exists():
        return []
    try:
        data = json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to read schedules.json: {e}")
    return []


def _save_schedules(schedules: list[dict]):
    try:
        SCHEDULES_FILE.write_text(
            json.dumps(schedules, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.error(f"Failed to write schedules.json: {e}")


def _cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if a 5-field cron expression matches a datetime.

    Format: minute hour day month weekday
    Supports: *, */N, N, N-M, N,M
    """
    try:
        fields = cron_expr.strip().split()
        if len(fields) != 5:
            return False

        values = [dt.minute, dt.hour, dt.day, dt.month, dt.isoweekday() % 7]
        # isoweekday: Mon=1..Sun=7, cron: Sun=0..Sat=6
        # Convert: isoweekday % 7 gives Sun=0, Mon=1..Sat=6

        for field, value in zip(fields, values):
            if not _field_matches(field, value):
                return False
        return True
    except Exception:
        return False


def _field_matches(field: str, value: int) -> bool:
    """Check if a single cron field matches a value."""
    if field == "*":
        return True

    for part in field.split(","):
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base == "*":
                if value % step == 0:
                    return True
            else:
                start = int(base)
                if value >= start and (value - start) % step == 0:
                    return True
        elif "-" in part:
            start, end = part.split("-", 1)
            if int(start) <= value <= int(end):
                return True
        else:
            if int(part) == value:
                return True

    return False


def get_due_tasks() -> list[dict]:
    """Return tasks that should fire right now."""
    now = datetime.now()
    now_key = now.strftime("%Y-%m-%d %H:%M")
    schedules = _load_schedules()
    due = []

    for task in schedules:
        if not task.get("enabled", True):
            continue

        task_id = task.get("id", "unknown")
        cron = task.get("cron", "")

        # Skip if already fired this minute
        if _last_fired.get(task_id) == now_key:
            continue

        if _cron_matches(cron, now):
            due.append(task)
            _last_fired[task_id] = now_key

    return due


def remove_once_task(task_id: str):
    """Remove a one-time task after execution."""
    schedules = _load_schedules()
    schedules = [s for s in schedules if s.get("id") != task_id]
    _save_schedules(schedules)
    logger.info(f"Removed one-time task: {task_id}")


async def run_scheduler(
    run_qwen_fn: Callable,
    send_result_fn: Callable,
):
    """Main scheduler loop. Call this as asyncio.create_task() on bot startup.

    Args:
        run_qwen_fn: async function(prompt, session_id=None) -> result_text
        send_result_fn: async function(text, task_description) -> None
    """
    logger.info("Scheduler started")

    while True:
        try:
            due_tasks = get_due_tasks()

            for task in due_tasks:
                task_id = task.get("id", "?")
                prompt = task.get("prompt", "")
                description = task.get("description", task_id)
                is_once = task.get("once", False)

                logger.info(f"Firing scheduled task: {task_id} ({description})")

                try:
                    # Run Qwen with the task prompt
                    from qwen_runner import _execute_qwen
                    result = await _execute_qwen(prompt)
                    result_text = result.get("result", "") if result else "No response"

                    # Send to Telegram
                    await send_result_fn(result_text, description)

                    # Remove one-time tasks
                    if is_once:
                        remove_once_task(task_id)

                except Exception as e:
                    logger.error(f"Scheduled task {task_id} failed: {e}", exc_info=True)
                    await send_result_fn(f"Scheduled task failed: {description}\nError: {e}", description)

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}", exc_info=True)

        await asyncio.sleep(CHECK_INTERVAL)
