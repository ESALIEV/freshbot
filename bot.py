import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import BOT_TOKEN
from db.database import init_db
from handlers.start import router as start_router
from handlers.store import router as store_router
from handlers.products import router as products_router
from services.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="newstore", description="Создать магазин"),
    BotCommand(command="join", description="Войти по коду"),
    BotCommand(command="products", description="Список товаров"),
    BotCommand(command="add", description="Добавить товар"),
    BotCommand(command="invite", description="Пригласить сотрудника"),
    BotCommand(command="mystores", description="Мои магазины"),
    BotCommand(command="members", description="Сотрудники"),
    BotCommand(command="help", description="Справка"),
]


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Укажите BOT_TOKEN в файле freshbot/.env")
        sys.exit(1)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Подключаем роутеры
    dp.include_router(start_router)
    dp.include_router(store_router)
    dp.include_router(products_router)

    await init_db()
    logger.info("Database initialized")

    await bot.set_my_commands(BOT_COMMANDS)
    me = await bot.get_me()
    logger.info("Bot @%s is running", me.username)

    # Запускаем планировщик уведомлений
    scheduler = await start_scheduler(bot)
    logger.info("Scheduler started")

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
