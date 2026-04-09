# QwenBot

Personal AI assistant in Telegram, powered by Qwen Code.

**Free**: 1000 requests/day, no subscriptions.

## What it does

- Chat with Qwen Code AI through Telegram
- Session management (create, switch, close)
- Voice messages (via Groq Whisper API, optional)
- HTML formatting for code blocks and structured responses
- Auto-start via systemd

## Install (3 steps)

### Prerequisites
- Ubuntu/Debian VPS
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Your Chat ID from [@userinfobot](https://t.me/userinfobot)

### One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/a-prs/qwen-bot/main/install.sh | sudo bash
```

The installer will:
1. Install Node.js, Python, Qwen Code CLI
2. Ask for your Telegram bot token and chat ID
3. (Optional) Ask for Groq API key for voice messages
4. Authorize Qwen Code
5. Set up and start the bot

### Voice messages (optional)

Get a free API key at [console.groq.com/keys](https://console.groq.com/keys) and enter it during install,
or add later to `/opt/qwenbot/.env`:

```
GROQ_API_KEY=gsk_your_key_here
```

Then restart: `systemctl restart qwenbot`

## Usage

Just send a message to your bot in Telegram.

**Commands:**
- `/menu` — control panel
- `/new` — start new session
- `/sessions` — list sessions
- `/status` — system status

**Inline buttons** for switching sessions, closing, and navigation.

## Update

```bash
cd /opt/qwenbot && git pull && systemctl restart qwenbot
```

## Manage

```bash
systemctl status qwenbot     # check status
systemctl restart qwenbot    # restart
journalctl -u qwenbot -f     # view logs
```

## Configuration

Edit `/opt/qwenbot/.env`:

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | yes | Your Telegram user ID |
| `GROQ_API_KEY` | no | For voice messages |
| `QWEN_MAX_TURNS` | no | Max AI iterations (default: 15) |
| `QWEN_TIMEOUT` | no | Timeout in seconds (default: 600) |

## Architecture

```
GitHub: https://github.com/a-prs/qwen-bot

/opt/qwenbot/
  bot/
    main.py          — Telegram bot (aiogram 3.x)
    qwen_runner.py   — Qwen Code CLI subprocess runner
    voice.py         — Groq Whisper API for voice
    formatting.py    — Markdown to Telegram HTML
    config.py        — .env loader
    db.py            — SQLite sessions & history
  workspace/         — Qwen Code working directory
  data/              — SQLite database
  .env               — configuration
```

## Security

- Single-user: only your Chat ID can interact
- Runs as dedicated `qwenbot` system user (not root)
- systemd sandbox: ProtectSystem, ProtectHome, NoNewPrivileges

## License

MIT
