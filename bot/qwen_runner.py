"""Qwen Code CLI runner — subprocess execution with in-memory message queue."""

import asyncio
import json
import logging
from typing import Optional, Callable

from config import QWEN_BIN, QWEN_MAX_TURNS, QWEN_TIMEOUT, WORK_DIR

logger = logging.getLogger("qwen_runner")

# In-memory state
_is_busy = False
_message_queue: list[dict] = []  # [{"text": str, "callback": Callable}]


def is_busy() -> bool:
    return _is_busy


def queue_length() -> int:
    return len(_message_queue)


async def run_qwen(
    prompt: str,
    session_id: Optional[str] = None,
    on_result: Optional[Callable] = None,
    max_turns: Optional[int] = None,
    queue_max: int = 5,
) -> dict:
    """Run Qwen Code CLI. If busy, queue the message.

    Returns:
        {"status": "started"} — task launched
        {"status": "queued", "position": N} — added to queue
        {"status": "queue_full"} — rejected
    """
    global _is_busy

    if _is_busy:
        if len(_message_queue) >= queue_max:
            return {"status": "queue_full"}
        _message_queue.append({"text": prompt, "session_id": session_id, "callback": on_result})
        return {"status": "queued", "position": len(_message_queue)}

    _is_busy = True

    # Launch in background task so we don't block the handler
    asyncio.create_task(_process_prompt(prompt, session_id, on_result, max_turns))
    return {"status": "started"}


async def _process_prompt(
    prompt: str,
    session_id: Optional[str],
    on_result: Optional[Callable],
    max_turns: Optional[int],
):
    """Execute qwen CLI and then drain the queue."""
    global _is_busy

    try:
        result = await _execute_qwen(prompt, session_id, max_turns)

        new_session_id = result.get("session_id", session_id) if result else session_id
        result_text = result.get("result", "") if result else ""

        if on_result:
            await on_result(result_text, new_session_id)

        # Drain queued messages
        while _message_queue:
            queued = _message_queue.pop(0)
            sid = new_session_id or queued.get("session_id")
            combined_prompt = queued["text"]

            qr = await _execute_qwen(combined_prompt, sid, max_turns)
            q_text = qr.get("result", "") if qr else ""
            q_sid = qr.get("session_id", sid) if qr else sid
            new_session_id = q_sid

            cb = queued.get("callback")
            if cb:
                await cb(q_text, q_sid)

    except Exception as e:
        logger.error(f"Error in _process_prompt: {e}", exc_info=True)
        if on_result:
            await on_result(f"Error: {e}", session_id)
    finally:
        _is_busy = False


async def _execute_qwen(
    prompt: str,
    session_id: Optional[str] = None,
    max_turns: Optional[int] = None,
) -> Optional[dict]:
    """Run qwen CLI as subprocess, return parsed JSON result."""

    cmd = [QWEN_BIN, "-p", prompt, "--output-format", "json"]
    cmd += ["--max-turns", str(max_turns or QWEN_MAX_TURNS)]
    cmd += ["--yolo"]

    if session_id:
        cmd += ["--resume", session_id]

    logger.info(f"Running: {QWEN_BIN} -p '{prompt[:60]}...' session={session_id}")

    try:
        WORK_DIR.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(WORK_DIR),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=QWEN_TIMEOUT,
        )

    except asyncio.TimeoutError:
        logger.error(f"Qwen timed out after {QWEN_TIMEOUT}s")
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return None
    except FileNotFoundError:
        logger.error(f"Qwen binary not found: {QWEN_BIN}")
        return None

    raw = stdout.decode("utf-8", errors="replace").strip()
    result = _parse_output(raw)

    if result is None:
        error = stderr.decode("utf-8", errors="replace").strip()
        if error:
            logger.error(f"Qwen stderr: {error[:300]}")

        # If no JSON but there's stdout, wrap it as plain result
        if raw:
            logger.warning("No JSON in output, wrapping raw stdout as result")
            return {"result": raw, "session_id": session_id}

        return None

    logger.info(
        f"Qwen done: turns={result.get('num_turns', '?')}, "
        f"session={result.get('session_id', '?')}"
    )
    return result


def _parse_output(raw: str) -> Optional[dict]:
    """Parse CLI JSON output — find line with {"result": ...}."""
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                if "result" in data:
                    return data
            except json.JSONDecodeError:
                continue
    return None
