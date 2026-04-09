"""Markdown to Telegram HTML converter.

Telegram supports a limited subset of HTML:
<b>, <i>, <u>, <s>, <code>, <pre>, <a href="">, <blockquote>

Order of operations is critical:
1. Escape HTML entities (&, <, >) INSIDE text (not inside code blocks)
2. Convert ```code blocks``` -> <pre>
3. Convert `inline code` -> <code>
4. Convert **bold** -> <b>
5. Convert _italic_ -> <i> (careful with snake_case)
"""

import re


def md_to_telegram_html(text: str) -> str:
    """Convert Markdown text to Telegram-safe HTML."""
    if not text:
        return ""

    # Step 1: Extract code blocks to protect them from processing
    code_blocks = []

    def save_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2)
        # Escape HTML inside code blocks
        code = _escape_html(code)
        code_blocks.append(f"<pre>{code}</pre>")
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = re.sub(r"```(\w*)\n?(.*?)```", save_code_block, text, flags=re.DOTALL)

    # Step 2: Extract inline code
    inline_codes = []

    def save_inline_code(match):
        code = _escape_html(match.group(1))
        inline_codes.append(f"<code>{code}</code>")
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", save_inline_code, text)

    # Step 3: Escape HTML in remaining text
    text = _escape_html(text)

    # Step 4: Convert bold **text** and __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Step 5: Convert italic *text* (but not inside words like file_name)
    # Only match *text* that is not **
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

    # Step 6: Convert strikethrough ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Step 7: Convert links [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Step 8: Restore code blocks and inline code
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", block)
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{i}\x00", code)

    # Step 9: Convert headers (# Title) to bold
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Step 10: Convert blockquotes (> text)
    text = re.sub(r"^>\s?(.+)$", r"<blockquote>\1</blockquote>", text, flags=re.MULTILINE)

    return text.strip()


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split long messages for Telegram (limit 4096 chars)."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find a good split point (newline)
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
