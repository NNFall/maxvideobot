from __future__ import annotations

from maxapi.types import CallbackButton, LinkButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def inline_keyboard(rows):
    kb = InlineKeyboardBuilder()
    for row in rows:
        buttons = []
        for button in row:
            kind = button.get("type", "callback")
            if kind == "link":
                buttons.append(LinkButton(text=button["text"], url=button["url"]))
            else:
                buttons.append(CallbackButton(text=button["text"], payload=button["payload"]))
        kb.row(*buttons)
    return kb.as_markup()


def cb(text: str, payload: str) -> dict[str, str]:
    return {"text": text, "payload": payload}


def link(text: str, url: str) -> dict[str, str]:
    return {"type": "link", "text": text, "url": url}
