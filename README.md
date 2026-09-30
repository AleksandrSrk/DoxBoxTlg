# doxBot

Личное хранилище семейных документов: поиск и скачивание через
Telegram-бота и Mini App, загрузка/редактирование — через веб-админку.

Полная спецификация решения — в [SPEC.md](./SPEC.md).

## Стек

FastAPI + SQLite (FTS5) + aiogram3 + Telegram Mini App + Google Drive API

## Запуск (черновик, дополнится по ходу разработки)

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

## Статус

Дизайн и модель данных зафиксированы (см. SPEC.md).
Реализация: в процессе.
