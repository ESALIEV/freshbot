import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from db.database import get_pending_notifications, mark_notification_sent, get_store_members

logger = logging.getLogger(__name__)

NOTIF_TEMPLATES = {
    "3d":      ("⚠️", "истекает через 3 дня"),
    "1d":      ("🔔", "истекает ЗАВТРА"),
    "0d":      ("🚨", "истекает СЕГОДНЯ"),
    "expired": ("❌", "ПРОСРОЧЕН"),
}


async def send_notifications(bot: Bot):
    """Проверяем и отправляем все накопившиеся уведомления"""
    notifications = await get_pending_notifications()
    
    if not notifications:
        return

    logger.info(f"Found {len(notifications)} pending notifications")

    for notif in notifications:
        emoji, status_text = NOTIF_TEMPLATES.get(notif["type"], ("📢", "срок годности"))

        text = (
            f"{emoji} <b>{notif['product_name']}</b> — {status_text}\n"
            f"Срок: {notif['expiry_date']}\n"
            f"Количество: {notif['quantity']} шт."
        )

        # Отправляем всем сотрудникам магазина
        members = await get_store_members(notif["store_id"])
        for member in members:
            try:
                await bot.send_message(
                    chat_id=member["telegram_id"],
                    text=text,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to send to {member['telegram_id']}: {e}")

        await mark_notification_sent(notif["id"])


async def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    
    # Проверяем уведомления каждый час
    scheduler.add_job(
        send_notifications,
        trigger="interval",
        hours=1,
        kwargs={"bot": bot},
        id="check_notifications"
    )
    
    # И сразу при старте
    scheduler.add_job(
        send_notifications,
        trigger="date",
        kwargs={"bot": bot},
        id="check_on_start"
    )
    
    scheduler.start()
    return scheduler
