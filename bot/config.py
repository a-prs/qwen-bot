"""QwenBot configuration — loaded from .env."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (/opt/qwenbot/.env)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Telegram
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

# Qwen CLI
QWEN_BIN = os.getenv("QWEN_BIN", "qwen")
QWEN_MAX_TURNS = int(os.getenv("QWEN_MAX_TURNS", "15"))
QWEN_TIMEOUT = int(os.getenv("QWEN_TIMEOUT", "600"))

# Working directory for Qwen Code
WORK_DIR = Path(os.getenv("QWEN_WORK_DIR", str(PROJECT_ROOT / "workspace")))

# Groq Whisper API (optional, for voice messages)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Database
DB_PATH = PROJECT_ROOT / "data" / "bot.db"

# Limits
MESSAGE_QUEUE_MAX = 5
SESSION_IDLE_TIMEOUT_HOURS = 48
