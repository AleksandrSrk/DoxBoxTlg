"""Подписанные временные ссылки на скачивание одного документа.

Зачем это нужно: обычные /api/* роуты защищены заголовком
X-Telegram-Init-Data, который добавляет наш собственный JS. Но нативный
Telegram.WebApp.downloadFile() и сервер Telegram (при отправке документа
в чат) сами делают HTTP-запрос к файлу — они не умеют слать наш
кастомный заголовок. Поэтому для самого файла — отдельный, не защищённый
initData роут (/files/{id}), а доступ к нему даёт подписанный токен
с коротким сроком жизни и привязкой к конкретному документу."""

import hashlib
import hmac
import os
import time

DOWNLOAD_TOKEN_SECRET = os.getenv("DOWNLOAD_TOKEN_SECRET", "")
TOKEN_TTL_SECONDS = 300  # 5 минут — успеть скачать, не больше


def make_download_token(doc_id: int) -> tuple[str, int]:
    exp = int(time.time()) + TOKEN_TTL_SECONDS
    sig = _sign(doc_id, exp)
    return sig, exp


def verify_download_token(doc_id: int, exp: int, token: str) -> bool:
    if time.time() > exp:
        return False
    return hmac.compare_digest(_sign(doc_id, exp), token)


def _sign(doc_id: int, exp: int) -> str:
    msg = f"{doc_id}:{exp}".encode()
    return hmac.new(DOWNLOAD_TOKEN_SECRET.encode(), msg, hashlib.sha256).hexdigest()
