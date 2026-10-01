"""Стриминг файлов из Google Drive через сервисный аккаунт.
Файлы нигде не кешируются локально — всегда тянутся из Drive на лету."""

import io
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# readonly было достаточно, пока только скачивали — теперь ещё и бэкап
# льётся в Drive, нужны права на запись в расшаренную папку.
SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "./service_account.json")

_service = None


def _get_service():
    global _service
    if _service is None:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        _service = build("drive", "v3", credentials=creds)
    return _service


def get_file_metadata(file_id: str) -> dict:
    """Имя, mime-type и размер файла — размер нужен для Content-Length,
    без него некоторые клиенты (включая Telegram при скачивании по URL)
    ведут себя непредсказуемо с потоковым ответом без длины."""
    return _get_service().files().get(fileId=file_id, fields="name,mimeType,size").execute()


def download_file_bytes(file_id: str) -> io.BytesIO:
    request = _get_service().files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf


def stream_file_chunks(file_id: str):
    """Отдаёт файл кусками по мере скачивания из Drive, не дожидаясь,
    пока он весь соберётся в памяти — иначе TTFB может оказаться слишком
    большим для чужих фетчеров (например, Telegram сам идёт забирать файл
    по нашей ссылке и, похоже, не готов долго ждать первый байт)."""
    request = _get_service().files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request, chunksize=1024 * 1024)
    done = False
    sent = 0
    while not done:
        _, done = downloader.next_chunk()
        buf.seek(sent)
        chunk = buf.read()
        sent = buf.tell()
        if chunk:
            yield chunk


def update_file_content(file_id: str, local_path: str,
                         mimetype: str = "application/octet-stream") -> dict:
    """Перезаписывает содержимое уже существующего файла — сервисный
    аккаунт не может создавать новые файлы (нет своей квоты на обычном
    личном Диске), а вот обновлять расшаренные ему файлы может свободно.
    Старые версии остаются в истории версий самого файла в Drive."""
    media = MediaFileUpload(local_path, mimetype=mimetype)
    return _get_service().files().update(
        fileId=file_id, media_body=media, fields="id,name,modifiedTime"
    ).execute()
