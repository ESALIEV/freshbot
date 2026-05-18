from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.database import (
    get_or_create_user, get_user_stores, add_product_batch,
    create_notifications_for_batch, get_store_products,
    delete_batch, get_batch_by_id, update_batch, update_product_name
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


class EditProductState(StatesGroup):
    waiting_for_field = State()
    waiting_for_new_name = State()
    waiting_for_new_expiry = State()
    waiting_for_new_qty = State()


@router.message(Command("products"))
@router.message(F.text == "📦 Товары")
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

    await message.answer(f"📦 <b>{store['name']}</b> — товары:", parse_mode="HTML")

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

        text = (
            f"{emoji} <b>{p['name']}</b>\n"
            f"Кол-во: {p['quantity']} шт.\n"
            f"Срок: {p['expiry_date']} ({days_text})\n"
            f"Статус: {status}"
        )

        # Кнопки под каждым товаром
        builder = InlineKeyboardBuilder()
        builder.button(text="✏️ Изменить", callback_data=f"edit:{p['batch_id']}")
        builder.button(text="🗑️ Удалить", callback_data=f"delete:{p['batch_id']}")
        builder.adjust(2)

        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ──── УДАЛЕНИЕ ────

@router.callback_query(F.data.startswith("delete:"))
async def cb_delete_confirm(callback: CallbackQuery):
    batch_id = int(callback.data.split(":")[1])
    batch = await get_batch_by_id(batch_id)

    if not batch:
        await callback.answer("Товар не найден", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"delete_confirm:{batch_id}")
    builder.button(text="❌ Отмена", callback_data="delete_cancel")
    builder.adjust(2)

    await callback.message.edit_text(
        f"🗑️ Удалить товар <b>{batch['product_name']}</b>?\n"
        f"Кол-во: {batch['quantity']} шт.\n"
        f"Срок: {batch['expiry_date']}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_confirm:"))
async def cb_delete_execute(callback: CallbackQuery):
    batch_id = int(callback.data.split(":")[1])
    batch = await get_batch_by_id(batch_id)
    name = batch["product_name"] if batch else "Товар"

    await delete_batch(batch_id)
    await callback.message.edit_text(f"🗑️ <b>{name}</b> удалён.", parse_mode="HTML")
    await callback.answer("Удалено!")


@router.callback_query(F.data == "delete_cancel")
async def cb_delete_cancel(callback: CallbackQuery):
    await callback.message.edit_text("❌ Удаление отменено.")
    await callback.answer()


# ──── РЕДАКТИРОВАНИЕ ────

@router.callback_query(F.data.startswith("edit:"))
async def cb_edit_menu(callback: CallbackQuery, state: FSMContext):
    batch_id = int(callback.data.split(":")[1])
    batch = await get_batch_by_id(batch_id)

    if not batch:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await state.update_data(batch_id=batch_id, product_id=batch["product_id"])

    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Название", callback_data="edit_field:name")
    builder.button(text="📅 Дата", callback_data="edit_field:expiry")
    builder.button(text="📦 Количество", callback_data="edit_field:qty")
    builder.button(text="❌ Отмена", callback_data="edit_cancel")
    builder.adjust(2)

    await callback.message.edit_text(
        f"✏️ Редактирование <b>{batch['product_name']}</b>\n\n"
        f"Что изменить?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "edit_field:name")
async def cb_edit_name(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductState.waiting_for_new_name)
    await callback.message.edit_text("📝 Введите новое название товара:")
    await callback.answer()


@router.callback_query(F.data == "edit_field:expiry")
async def cb_edit_expiry(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductState.waiting_for_new_expiry)
    await callback.message.edit_text("📅 Введите новую дату в формате ДД.ММ.ГГГГ:")
    await callback.answer()


@router.callback_query(F.data == "edit_field:qty")
async def cb_edit_qty(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductState.waiting_for_new_qty)
    await callback.message.edit_text("📦 Введите новое количество (штук):")
    await callback.answer()


@router.callback_query(F.data == "edit_cancel")
async def cb_edit_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Редактирование отменено.")
    await callback.answer()


@router.message(EditProductState.waiting_for_new_name)
async def process_new_name(message: Message, state: FSMContext):
    data = await state.get_data()
    await update_product_name(data["product_id"], message.text.strip())
    await state.clear()
    await message.answer("✅ Название обновлено!")


@router.message(EditProductState.waiting_for_new_expiry)
async def process_new_expiry(message: Message, state: FSMContext):
    text = message.text.strip()
    for fmt in ["%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"]:
        try:
            date = datetime.strptime(text, fmt)
            expiry_str = date.strftime("%Y-%m-%d")
            break
        except ValueError:
            continue
    else:
        await message.answer("❌ Неверный формат. Введите дату как ДД.ММ.ГГГГ")
        return

    data = await state.get_data()
    batch = await get_batch_by_id(data["batch_id"])
    await update_batch(data["batch_id"], batch["quantity"], expiry_str)
    await state.clear()
    await message.answer("✅ Дата обновлена!")


@router.message(EditProductState.waiting_for_new_qty)
async def process_new_qty(message: Message, state: FSMContext):
    try:
        qty = int(message.text.strip())
        if qty <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число больше 0:")
        return

    data = await state.get_data()
    batch = await get_batch_by_id(data["batch_id"])
    await update_batch(data["batch_id"], qty, batch["expiry_date"])
    await state.clear()
    await message.answer("✅ Количество обновлено!")


# ──── ДОБАВЛЕНИЕ ────

@router.message(Command("add"))
@router.message(F.text == "➕ Добавить")
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
