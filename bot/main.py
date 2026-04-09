"""QwenBot — Personal AI assistant via Telegram + Qwen Code CLI."""

import asyncio
import logging
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from config import BOT_TOKEN, ADMIN_CHAT_ID, GROQ_API_KEY, MESSAGE_QUEUE_MAX
from db import (
    init_db,
    create_session,
    get_session,
    get_active_sessions,
    set_session_done,
    set_session_active,
    save_message,
)
from qwen_runner import run_qwen, is_busy, queue_length
from formatting import md_to_telegram_html, split_message
from voice import transcribe_voice

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Track which session user is focused on
user_focus: dict[int, str] = {}  # chat_id -> session_id

SESSIONS_PER_PAGE = 5


# ==================== Security ====================

def is_admin(message: Message) -> bool:
    return message.chat.id == ADMIN_CHAT_ID


def is_admin_cb(callback: CallbackQuery) -> bool:
    return callback.message.chat.id == ADMIN_CHAT_ID


# ==================== Keyboards ====================

def build_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Sessions", callback_data="sessions:0"),
            InlineKeyboardButton(text="+ New", callback_data="new_session"),
        ],
        [
            InlineKeyboardButton(text="Status", callback_data="status"),
            InlineKeyboardButton(text="Close all", callback_data="close_all"),
        ],
    ])


def build_sessions_keyboard(sessions: list[dict], page: int = 0, focus_id: str = None) -> InlineKeyboardMarkup:
    total = len(sessions)
    start = page * SESSIONS_PER_PAGE
    end = start + SESSIONS_PER_PAGE
    page_sessions = sessions[start:end]

    buttons = []
    for s in page_sessions:
        icon = {"active": "\u26a1", "idle": "\u25cb"}.get(s["status"], "?")
        marker = "\u25b6 " if s["session_id"] == focus_id else ""
        name = s["name"][:28] + ".." if len(s["name"]) > 28 else s["name"]

        buttons.append([
            InlineKeyboardButton(
                text=f"{marker}{icon} {name}",
                callback_data=f'switch:{s["session_id"]}',
            ),
            InlineKeyboardButton(text="x", callback_data=f'close:{s["session_id"]}'),
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="< Back", callback_data=f"sessions:{page - 1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="Next >", callback_data=f"sessions:{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="Menu", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== Text extraction ====================

async def extract_text(message: Message) -> str | None:
    """Extract text from message: plain text, voice, or caption."""
    if message.text:
        return message.text

    if message.voice or message.audio:
        voice_obj = message.voice or message.audio
        transcript = await transcribe_voice(voice_obj, bot)
        if transcript is None:
            return None  # Groq not configured
        return transcript

    if message.caption:
        return message.caption

    return None


# ==================== Commands ====================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if not is_admin(message):
        return

    voice_status = "on (Groq)" if GROQ_API_KEY else "off"
    await message.reply(
        f"<b>QwenBot</b> — your personal AI assistant\n\n"
        f"Powered by Qwen Code (1000 free requests/day)\n"
        f"Voice: {voice_status}\n\n"
        f"Just send me a message to start.",
        parse_mode=ParseMode.HTML,
        reply_markup=build_main_menu(),
    )


@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    if not is_admin(message):
        return
    await message.reply(
        "<b>Control Panel</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=build_main_menu(),
    )


@dp.message(Command("new"))
async def cmd_new(message: Message):
    if not is_admin(message):
        return
    user_focus[message.chat.id] = "__force_new__"
    await message.reply(
        "Send your message — it will start a new session.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Cancel", callback_data="cancel_new")],
        ]),
    )


@dp.message(Command("sessions"))
async def cmd_sessions(message: Message):
    if not is_admin(message):
        return
    sessions = get_active_sessions()
    if not sessions:
        await message.reply(
            "No active sessions.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="+ New", callback_data="new_session")],
                [InlineKeyboardButton(text="Menu", callback_data="menu")],
            ]),
        )
        return

    focus_id = user_focus.get(message.chat.id)
    await message.reply(
        f"<b>Sessions</b> ({len(sessions)} active)",
        parse_mode=ParseMode.HTML,
        reply_markup=build_sessions_keyboard(sessions, 0, focus_id),
    )


@dp.message(Command("status"))
async def cmd_status(message: Message):
    if not is_admin(message):
        return
    await _send_status(message.chat.id)


# ==================== Callback handlers ====================

@dp.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery):
    if not is_admin_cb(callback):
        return
    await callback.message.edit_text(
        "<b>Control Panel</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=build_main_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("sessions:"))
async def cb_sessions(callback: CallbackQuery):
    if not is_admin_cb(callback):
        return
    page = int(callback.data.split(":")[1])
    sessions = get_active_sessions()

    if not sessions:
        await callback.message.edit_text(
            "No active sessions.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="+ New", callback_data="new_session")],
                [InlineKeyboardButton(text="Menu", callback_data="menu")],
            ]),
        )
        await callback.answer()
        return

    focus_id = user_focus.get(callback.message.chat.id)
    await callback.message.edit_text(
        f"<b>Sessions</b> ({len(sessions)} active)",
        parse_mode=ParseMode.HTML,
        reply_markup=build_sessions_keyboard(sessions, page, focus_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("switch:"))
async def cb_switch(callback: CallbackQuery):
    if not is_admin_cb(callback):
        return
    session_id = callback.data.split(":", 1)[1]
    session = get_session(session_id)
    if not session:
        await callback.answer("Session not found", show_alert=True)
        return

    user_focus[callback.message.chat.id] = session_id
    created = datetime.fromisoformat(session["created_at"]).strftime("%d.%m %H:%M")
    summary = session.get("summary", "") or "No description"

    await callback.message.edit_text(
        f"<b>{session['name']}</b>\n\n"
        f"Status: {session['status']}\n"
        f"Created: {created}\n\n"
        f"<i>{summary[:150]}</i>\n\n"
        f"Switched. Send a message to continue.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Sessions", callback_data="sessions:0")],
            [InlineKeyboardButton(text="Menu", callback_data="menu")],
        ]),
    )
    await callback.answer(f"Session: {session['name'][:30]}")


@dp.callback_query(F.data.startswith("close:"))
async def cb_close(callback: CallbackQuery):
    if not is_admin_cb(callback):
        return
    session_id = callback.data.split(":", 1)[1]
    session = get_session(session_id)
    if not session:
        await callback.answer("Session not found", show_alert=True)
        return

    set_session_done(session_id)

    if user_focus.get(callback.message.chat.id) == session_id:
        user_focus.pop(callback.message.chat.id, None)

    await callback.answer(f"Closed: {session['name'][:30]}", show_alert=True)

    sessions = get_active_sessions()
    if sessions:
        focus_id = user_focus.get(callback.message.chat.id)
        await callback.message.edit_text(
            f"<b>Sessions</b> ({len(sessions)} active)\n"
            f"Closed: {session['name']}",
            parse_mode=ParseMode.HTML,
            reply_markup=build_sessions_keyboard(sessions, 0, focus_id),
        )
    else:
        await callback.message.edit_text(
            f"Closed: {session['name']}\nNo more active sessions.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="+ New", callback_data="new_session")],
                [InlineKeyboardButton(text="Menu", callback_data="menu")],
            ]),
        )


@dp.callback_query(F.data == "new_session")
async def cb_new_session(callback: CallbackQuery):
    if not is_admin_cb(callback):
        return
    user_focus[callback.message.chat.id] = "__force_new__"
    await callback.message.edit_text(
        "Send your first message — it becomes the session name.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Cancel", callback_data="cancel_new")],
        ]),
    )
    await callback.answer()


@dp.callback_query(F.data == "cancel_new")
async def cb_cancel_new(callback: CallbackQuery):
    if not is_admin_cb(callback):
        return
    user_focus.pop(callback.message.chat.id, None)
    await callback.message.edit_text("Cancelled.", reply_markup=build_main_menu())
    await callback.answer()


@dp.callback_query(F.data == "close_all")
async def cb_close_all(callback: CallbackQuery):
    if not is_admin_cb(callback):
        return
    sessions = get_active_sessions()
    if not sessions:
        await callback.answer("No active sessions", show_alert=True)
        return

    await callback.message.edit_text(
        f"<b>Close all {len(sessions)} sessions?</b>\nThis cannot be undone.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Yes, close all", callback_data="confirm_close_all"),
                InlineKeyboardButton(text="Cancel", callback_data="menu"),
            ],
        ]),
    )
    await callback.answer()


@dp.callback_query(F.data == "confirm_close_all")
async def cb_confirm_close_all(callback: CallbackQuery):
    if not is_admin_cb(callback):
        return
    sessions = get_active_sessions()
    for s in sessions:
        set_session_done(s["session_id"])
    user_focus.pop(callback.message.chat.id, None)

    await callback.message.edit_text(
        f"Closed {len(sessions)} sessions.",
        reply_markup=build_main_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "status")
async def cb_status(callback: CallbackQuery):
    if not is_admin_cb(callback):
        return
    await _send_status(callback.message.chat.id, edit_message=callback.message)
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer("Working...")


# ==================== Main message handler ====================

@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def handle_message(message: Message):
    """Main handler: extract text -> route to session -> run Qwen."""

    # 1. Extract text (plain text, voice, caption)
    text = await extract_text(message)

    if text is None and (message.voice or message.audio):
        await message.reply(
            "Voice messages require GROQ_API_KEY.\n"
            "Get a free key at https://console.groq.com/keys\n"
            "Then add it to /opt/qwenbot/.env",
        )
        return

    if not text:
        await message.reply("Send text or voice message.")
        return

    # Show transcribed voice text
    if message.voice or message.audio:
        if text.startswith("["):
            # Error message from voice.py
            await message.reply(text)
            return
        await message.reply(f"<i>Voice:</i> {md_to_telegram_html(text)}", parse_mode=ParseMode.HTML)

    # 2. Route to session
    force_new = user_focus.get(message.chat.id) == "__force_new__"

    if force_new:
        user_focus.pop(message.chat.id, None)
        session_id = None
        session_name = text[:50]
    else:
        focus_id = user_focus.get(message.chat.id)
        if focus_id and focus_id != "__force_new__":
            session = get_session(focus_id)
            if session and session["status"] != "done":
                session_id = focus_id
                session_name = session["name"]
            else:
                session_id = None
                session_name = text[:50]
        else:
            session_id = None
            session_name = text[:50]

    # Save user message
    save_message("user", text, session_id)

    # 3. Show "working" indicator
    if session_id:
        status_text = f"Continuing: <b>{session_name}</b>"
    else:
        status_text = f"New task: <i>{session_name}</i>"

    status_msg = await message.reply(
        status_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Working...", callback_data="noop")],
        ]),
    )

    # Mark session active
    if session_id:
        set_session_active(session_id)

    # 4. Run Qwen
    async def on_result(result_text: str, returned_session_id: str):
        if returned_session_id:
            user_focus[message.chat.id] = returned_session_id

            if not session_id:
                existing = get_session(returned_session_id)
                if not existing:
                    create_session(returned_session_id, session_name)

        # Save assistant response
        save_message("assistant", result_text or "", returned_session_id)

        # Delete "working" status
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass

        # Send result
        if result_text:
            html = md_to_telegram_html(result_text)
            chunks = split_message(html)

            for i, chunk in enumerate(chunks):
                reply_markup = None
                if i == len(chunks) - 1:
                    reply_markup = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="Sessions", callback_data="sessions:0"),
                            InlineKeyboardButton(text="+ New", callback_data="new_session"),
                        ],
                    ])

                try:
                    await bot.send_message(
                        ADMIN_CHAT_ID,
                        chunk,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                    )
                except TelegramBadRequest as e:
                    logger.warning(f"HTML parse failed, sending as plain text: {e}")
                    await bot.send_message(
                        ADMIN_CHAT_ID,
                        result_text[:4000] if i == 0 else chunk[:4000],
                        reply_markup=reply_markup,
                    )
                    break
        else:
            await bot.send_message(
                ADMIN_CHAT_ID,
                "Done (no text response).",
                reply_markup=build_main_menu(),
            )

    result = await run_qwen(
        prompt=text,
        session_id=session_id,
        on_result=on_result,
        queue_max=MESSAGE_QUEUE_MAX,
    )

    if result["status"] == "queued":
        try:
            await status_msg.edit_text(
                f"Qwen is busy. Message queued ({result['position']}/{MESSAGE_QUEUE_MAX}).",
            )
        except TelegramBadRequest:
            pass
    elif result["status"] == "queue_full":
        try:
            await status_msg.edit_text("Queue is full. Wait for current task to finish.")
        except TelegramBadRequest:
            pass


# ==================== Helpers ====================

async def _send_status(chat_id: int, edit_message=None):
    sessions = get_active_sessions()
    active = [s for s in sessions if s["status"] == "active"]
    idle = [s for s in sessions if s["status"] == "idle"]

    focus_id = user_focus.get(chat_id)
    focus_session = get_session(focus_id) if focus_id and focus_id != "__force_new__" else None

    text = f"<b>Status</b>\n\n"
    text += f"Active: {len(active)}\n"
    text += f"Idle: {len(idle)}\n"
    text += f"Queue: {queue_length()}\n\n"

    if focus_session:
        text += f"Current: <b>{focus_session['name']}</b>\n"
    else:
        text += f"Current: <i>none</i>\n"

    voice_status = "on (Groq)" if GROQ_API_KEY else "off"
    text += f"Voice: {voice_status}\n"
    text += f"Busy: {'yes' if is_busy() else 'no'}"

    if edit_message:
        await edit_message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=build_main_menu())
    else:
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=build_main_menu())


async def setup_bot_commands():
    commands = [
        BotCommand(command="menu", description="Control panel"),
        BotCommand(command="sessions", description="Session list"),
        BotCommand(command="new", description="New session"),
        BotCommand(command="status", description="System status"),
    ]
    await bot.set_my_commands(commands)


async def main():
    init_db()
    await setup_bot_commands()
    logger.info("QwenBot starting...")
    logger.info(f"Admin chat ID: {ADMIN_CHAT_ID}")
    logger.info(f"Voice: {'Groq' if GROQ_API_KEY else 'disabled'}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
