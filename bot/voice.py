"""Voice message transcription via Groq Whisper API."""

import logging
import tempfile
from pathlib import Path

import httpx

from config import GROQ_API_KEY

logger = logging.getLogger("voice")

GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


async def transcribe_voice(voice, bot) -> str | None:
    """Download voice message and transcribe via Groq Whisper API.

    Args:
        voice: aiogram Voice or Audio object
        bot: aiogram Bot instance

    Returns:
        Transcribed text, error message, or None if not configured
    """
    if not GROQ_API_KEY:
        return None

    tmp_path = None
    try:
        # Download voice file from Telegram
        file = await bot.get_file(voice.file_id)
        tmp_path = Path(tempfile.gettempdir()) / f"qwenbot_voice_{voice.file_id}.ogg"
        await bot.download_file(file.file_path, destination=str(tmp_path))

        # Send to Groq Whisper API
        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(tmp_path, "rb") as f:
                response = await client.post(
                    GROQ_API_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    files={"file": (tmp_path.name, f, "audio/ogg")},
                    data={"model": "whisper-large-v3", "language": "ru"},
                )

        if response.status_code == 200:
            data = response.json()
            text = data.get("text", "").strip()
            if text:
                logger.info(f"Transcribed {voice.duration}s voice: {text[:60]}...")
                return text
            return "[Пустая запись]"

        elif response.status_code == 429:
            logger.warning("Groq rate limit hit")
            return "[Слишком много голосовых, подожди минуту]"

        elif response.status_code == 401:
            logger.error("Invalid Groq API key")
            return "[Неверный GROQ_API_KEY, проверь настройки]"

        else:
            logger.error(f"Groq API error {response.status_code}: {response.text[:200]}")
            return "[Не удалось распознать, попробуй текстом]"

    except httpx.TimeoutException:
        logger.error("Groq API timeout")
        return "[Таймаут распознавания, попробуй текстом]"
    except Exception as e:
        logger.error(f"Voice transcription error: {e}", exc_info=True)
        return "[Ошибка распознавания, попробуй текстом]"
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
