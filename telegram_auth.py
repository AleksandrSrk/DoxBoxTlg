"""Проверка, что запрос к API реально пришёл из Telegram Mini App,
а не откуда попало, + whitelist по telegram user_id (только семья)."""

import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
ALLOWED_IDS = {
    int(x) for x in os.getenv("ALLOWED_TELEGRAM_IDS", "").split(",") if x.strip()
}
MAX_INIT_DATA_AGE = 24 * 60 * 60  # сутки — старую initData не принимаем


def _verify_init_data(init_data: str) -> dict:
    """Проверяет подпись initData по алгоритму Telegram, возвращает данные юзера."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Нет подписи initData")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise HTTPException(401, "Подпись initData не сошлась")

    auth_date = int(pairs.get("auth_date", 0))
    if time.time() - auth_date > MAX_INIT_DATA_AGE:
        raise HTTPException(401, "initData устарела, открой мини-апп заново")

    return json.loads(pairs.get("user", "{}"))


def require_telegram_user(x_telegram_init_data: str | None = Header(default=None)) -> dict:
    """FastAPI-зависимость: пускает только реальных пользователей Telegram
    из белого списка. DEV_MODE — только для локальной разработки без
    настоящего Telegram-клиента, на проде должен быть выключен."""
    if not x_telegram_init_data:
        if DEV_MODE:
            print("⚠️  DEV_MODE: запрос без initData пропущен как локальный тест")
            return {"id": 0, "first_name": "Dev"}
        raise HTTPException(401, "Открой это через Telegram-бота")

    user = _verify_init_data(x_telegram_init_data)
    if ALLOWED_IDS and user.get("id") not in ALLOWED_IDS:
        raise HTTPException(403, "Доступ только для членов семьи")
    return user
