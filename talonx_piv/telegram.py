"""Synchronous best-effort Telegram sender used behind EventBus isolation."""

from __future__ import annotations
import requests


def sender(token: str, chat_id: str):
    def send(message: str) -> bool:
        if not token or not chat_id:
            return False
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": message}, timeout=10)
        return response.status_code == 200
    return send
