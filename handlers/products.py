from datetime import datetime
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db.database import (
    get_or_create_user, get_user_stores, add_product_batch,
    create_notifications_for_batch, get_store_products
)

router = Router()

EMOJI_STATUS = {
    "ok":      ("✅", "норма"),
    "warning": ("⚠️", "скоро истечёт"),
    "today":   ("🚨", "истекает сегодня"),
    "expired": ("❌", "просрочен"),
}


def get_status(days_left: int) -> tuple:
    if days_left < 0:
        return EMOJI_STATUS["expired"]
    elif days_left == 0:
        return EMOJI_STATUS["today"]
    elif days_left <= 3:
        return EMOJI_STATUS["warning"]
    return EMOJI_STATUS["ok"]


class AddProductState(StatesGroup):
    waiting_for_name = State()
    waiting_for_expiry = State()
    waiting_for_qty = State()


@router.message(Command("products"))
async def cmd_products(message: Message):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])

    if not stores:
        await message.answer("У вас нет магазинов. /newstore или /join")
        return

    store = stores[0]
    products = await get_store_products(store["id"])

    if not products:
        await message.answer(
            f"📦 Магазин <b>{store['name']}</b>\n\n"
            "Товаров пока нет. Добавьте первый: /add",
            parse_mode="HTML"
        )
        return

    text = f"📦 <b>{store['name']}</b> — товары:\n\n"

    for p in products:
        days = p["days_left"]
        emoji, status = get_status(days)

        if days < 0:
            days_text = f"просрочен {abs(days)} дн. назад"
        elif days == 0:
            days_text = "истекает СЕГОДНЯ"
        elif days == 1:
            days_text = "завтра"
        else:
            days_text = f"через {days} дн."

        text += (
            f"{emoji} <b>{p['name']}</b>\n"
            f"   Кол-во: {p['quantity']} шт.\n"
            f"   Срок: {p['expiry_date']} ({days_text})\n"
            f"   Статус: {status}\n\n"
        )

    await message.answer(text, parse_mode="HTML")


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])

    if not stores:
        await message.answer("У вас нет магазинов. /newstore или /join")
        return

    await state.update_data(store_id=stores[0]["id"], store_name=stores[0]["name"])
    await state.set_state(AddProductState.waiting_for_name)
    await message.answer(
        f"➕ Добавление товара в <b>{stores[0]['name']}</b>\n\n"
        "Введите название товара:",
        parse_mode="HTML"
    )


@router.message(AddProductState.waiting_for_name)
async def process_product_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Название слишком короткое. Попробуйте снова:")
        return

    await state.update_data(product_name=name)
    await state.set_state(AddProductState.waiting_for_expiry)
    await message.answer(
        f"Товар: <b>{name}</b>\n\n"
        "Введите срок годности в формате ДД.ММ.ГГГГ\n"
        "Например: 15.06.2025",
        parse_mode="HTML"
    )


@router.message(AddProductState.waiting_for_expiry)
async def process_expiry_date(message: Message, state: FSMContext):
    text = message.text.strip()

    for fmt in ["%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"]:
        try:
            date = datetime.strptime(text, fmt)
            expiry_str = date.strftime("%Y-%m-%d")
            break
        except ValueError:
            continue
    else:
        await message.answer(
            "❌ Неверный формат. Введите дату как ДД.ММ.ГГГГ\n"
            "Например: 20.06.2025"
        )
        return

    await state.update_data(expiry_date=expiry_str)
    await state.set_state(AddProductState.waiting_for_qty)
    await message.answer("Введите количество (штук):")


@router.message(AddProductState.waiting_for_qty)
async def process_quantity(message: Message, state: FSMContext):
    try:
        qty = int(message.text.strip())
        if qty <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число больше 0:")
        return

    data = await state.get_data()
    await state.clear()

    batch_id = await add_product_batch(
        store_id=data["store_id"],
        name=data["product_name"],
        quantity=qty,
        expiry_date=data["expiry_date"]
    )

    await create_notifications_for_batch(batch_id, data["expiry_date"])

    expiry_display = datetime.strptime(data["expiry_date"], "%Y-%m-%d").strftime("%d.%m.%Y")
    days_left = (datetime.strptime(data["expiry_date"], "%Y-%m-%d") - datetime.now()).days

    await message.answer(
        f"✅ Товар добавлен!\n\n"
        f"📦 <b>{data['product_name']}</b>\n"
        f"Кол-во: {qty} шт.\n"
        f"Срок годности: {expiry_display}\n"
        f"Осталось дней: {days_left}\n\n"
        f"Уведомления запланированы за 3 дня, 1 день и в день истечения.",
        parse_mode="HTML"
    )
