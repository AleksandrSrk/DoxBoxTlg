"""Telegram-бот doxBot: пока только вход в Mini App через /start.
Загрузка документов через бота не делается — только чтение (см. SPEC.md)."""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env")
if not WEBAPP_URL or not WEBAPP_URL.startswith("https://"):
    raise RuntimeError("WEBAPP_URL должен быть https-ссылкой (Telegram не пустит http)")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📄 Открыть документы", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await message.answer(
        # Не рассказываем посторонним, как устроена защита: только ID,
        # который владелец добавит в белый список, если это свой человек.
        f"Привет!\n\nВаш Telegram ID: <code>{message.from_user.id}</code>\n"
        "Доступ к документам выдаёт администратор.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def main():
    logging.info("doxBot запущен, жду /start...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
