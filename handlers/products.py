from datetime import datetime, date
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.database import (
    get_or_create_user, get_user_stores, add_product_batch,
    create_notifications_for_batch, get_store_products,
    delete_batch, get_batch_by_id, update_batch, update_product_name,
    update_product_article, get_member_role  # Добавлен импорт update_product_article
)

router = Router()

PAGE_SIZE = 5

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


def format_product(p: dict) -> str:
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
    article = f"\nАртикул: <code>{p['article']}</code>" if p.get("article") else ""
    return (
        f"{emoji} <b>{p['name']}</b>{article}\n"
        f"Кол-во: {p['quantity']} шт.\n"
        f"Срок: {p['expiry_date']} ({days_text})\n"
        f"Статус: {status}"
    )


# ──── ВСПОМОГАТЕЛЬНАЯ: выбор магазина ────

async def ask_select_store(message: Message, stores: list, action: str):
    """Показывает кнопки выбора магазина. action — префикс callback_data."""
    builder = InlineKeyboardBuilder()
    for s in stores:
        role_emoji = "👑" if s["role"] == "admin" else "👷"
        builder.button(
            text=f"{role_emoji} {s['name']}",
            callback_data=f"{action}:{s['id']}"
        )
    builder.adjust(1)
    await message.answer("🏪 Выберите магазин:", reply_markup=builder.as_markup())


# ──── СПИСОК ТОВАРОВ ────

async def show_products_page(message: Message, store_id: int, page: int = 0, search: str = ""):
    products = await get_store_products(store_id, search)
    total = len(products)

    if not products:
        text = "🔍 Ничего не найдено." if search else "Товаров пока нет. Добавьте первый: /add"
        await message.answer(text)
        return

    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    page_products = products[start:end]
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

    header = f"📦 Товары"
    if search:
        header += f" (поиск: «{search}»)"
    header += f" — стр. {page + 1}/{total_pages} ({total} шт.)"
    await message.answer(header)

    for p in page_products:
        text = format_product(p)
        builder = InlineKeyboardBuilder()
        builder.button(text="✏️ Изменить", callback_data=f"edit:{p['batch_id']}")
        builder.button(text="🗑️ Удалить", callback_data=f"delete:{p['batch_id']}")
        builder.adjust(2)
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="⬅️ Назад", callback_data=f"page:{page-1}:{store_id}:{search}")
    if end < total:
        nav.button(text="➡️ Вперёд", callback_data=f"page:{page+1}:{store_id}:{search}")
    nav.button(text="🔍 Поиск", callback_data=f"search_start:{store_id}")
    nav.button(text="📄 Перейти на стр.", callback_data=f"goto_page:{store_id}:{search}")
    nav.adjust(2)
    await message.answer(
        f"_{page + 1} из {total_pages} страниц_",
        reply_markup=nav.as_markup(),
        parse_mode="Markdown"
    )

class AddProductState(StatesGroup):
    waiting_for_name = State()
    waiting_for_article = State()
    waiting_for_category = State()
    waiting_for_expiry = State()
    waiting_for_qty = State()


class EditProductState(StatesGroup):
    waiting_for_new_name = State()
    waiting_for_new_article = State()  # Добавлено состояние
    waiting_for_new_expiry = State()
    waiting_for_new_qty = State()


class SearchState(StatesGroup):
    waiting_for_query = State()


# ──── /products — выбор магазина если несколько ────

@router.message(Command("products"))
@router.message(F.text == "📦 Товары")
async def cmd_products(message: Message, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])

    if not stores:
        await message.answer("У вас нет магазинов. /newstore или /join")
        return

    if len(stores) == 1:
        store_id = stores[0]["id"]
        await state.update_data(store_id=store_id)
        await show_products_page(message, store_id, page=0)
    else:
        await ask_select_store(message, stores, "products_store")


@router.callback_query(F.data.startswith("products_store:"))
async def cb_select_store_products(callback: CallbackQuery, state: FSMContext):
    store_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(callback.from_user.id)

    role = await get_member_role(user["id"], store_id)
    if not role:
        await callback.answer("❌ Нет доступа к этому магазину", show_alert=True)
        return

    await state.update_data(store_id=store_id)
    await show_products_page(callback.message, store_id, page=0)
    await callback.answer()


@router.callback_query(F.data.startswith("page:"))
async def cb_page(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":", 3)
    page = int(parts[1])
    store_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    search = parts[3] if len(parts) > 3 else ""

    if not store_id:
        data = await state.get_data()
        store_id = data.get("store_id")

    if not store_id:
        await callback.answer("Ошибка: магазин не выбран", show_alert=True)
        return

    await show_products_page(callback.message, store_id, page=page, search=search)
    await callback.answer()
class GotoPageState(StatesGroup):
    waiting_for_page = State()


@router.callback_query(F.data.startswith("goto_page:"))
async def cb_goto_page(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":", 2)
    store_id = int(parts[1])
    search = parts[2] if len(parts) > 2 else ""
    await state.update_data(store_id=store_id, search=search)
    await state.set_state(GotoPageState.waiting_for_page)
    await callback.message.answer("📄 Введите номер страницы:")
    await callback.answer()


@router.message(GotoPageState.waiting_for_page)
async def process_goto_page(message: Message, state: FSMContext):
    try:
        page = int(message.text.strip()) - 1
        if page < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректный номер страницы:")
        return

    data = await state.get_data()
    store_id = data.get("store_id")
    search = data.get("search", "")
    await state.clear()

    products = await get_store_products(store_id, search)
    total_pages = (len(products) + PAGE_SIZE - 1) // PAGE_SIZE

    if page >= total_pages:
        await message.answer(f"❌ Страницы {page + 1} не существует. Всего страниц: {total_pages}")
        return

    await state.update_data(store_id=store_id)
    await show_products_page(message, store_id, page=page, search=search)

# ──── ПОИСК ────

@router.callback_query(F.data.startswith("search_start"))
async def cb_search_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) > 1:
        await state.update_data(store_id=int(parts[1]))
    await state.set_state(SearchState.waiting_for_query)
    await callback.message.answer("🔍 Введите название или артикул для поиска:")
    await callback.answer()


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext):
    await state.set_state(SearchState.waiting_for_query)
    await message.answer("🔍 Введите название или артикул для поиска:")


@router.message(SearchState.waiting_for_query)
async def process_search(message: Message, state: FSMContext):
    query = message.text.strip()
    data = await state.get_data()
    store_id = data.get("store_id")
    await state.clear()

    if not store_id:
        user = await get_or_create_user(message.from_user.id)
        stores = await get_user_stores(user["id"])
        if not stores:
            await message.answer("У вас нет магазинов.")
            return
        store_id = stores[0]["id"]

    await state.update_data(store_id=store_id)
    await show_products_page(message, store_id, page=0, search=query)


# ──── УДАЛЕНИЕ ────

@router.callback_query(F.data.startswith("delete:"))
async def cb_delete_confirm(callback: CallbackQuery):
    batch_id = int(callback.data.split(":")[1])
    batch = await get_batch_by_id(batch_id)

    if not batch:
        await callback.answer("Товар не найден", show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)
    role = await get_member_role(user["id"], batch["store_id"])
    if not role:
        await callback.answer("❌ У вас нет доступа к этому товару", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"delete_confirm:{batch_id}")
    builder.button(text="❌ Отмена", callback_data="delete_cancel")
    builder.adjust(2)

    await callback.message.edit_text(
        f"🗑️ Удалить <b>{batch['product_name']}</b>?\n"
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

    if not batch:
        await callback.answer("Товар уже удалён", show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)
    role = await get_member_role(user["id"], batch["store_id"])
    if not role:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    name = batch["product_name"]
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

    user = await get_or_create_user(callback.from_user.id)
    role = await get_member_role(user["id"], batch["store_id"])
    if not role:
        await callback.answer("❌ У вас нет доступа к этому товару", show_alert=True)
        return

    await state.update_data(batch_id=batch_id, product_id=batch["product_id"])

    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Название",   callback_data="edit_field:name")
    builder.button(text="🏷️ Артикул",   callback_data="edit_field:article")  # Изменен callback_data на общий стиль
    builder.button(text="📅 Дата",       callback_data="edit_field:expiry")
    builder.button(text="📦 Количество", callback_data="edit_field:qty")
    builder.button(text="❌ Отмена",     callback_data="edit_cancel")
    builder.adjust(2)

    await callback.message.edit_text(
        f"✏️ Редактирование <b>{batch['product_name']}</b>\n\nЧто изменить?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "edit_field:name")
async def cb_edit_name(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductState.waiting_for_new_name)
    await callback.message.edit_text("📝 Введите новое название товара:")
    await callback.answer()


@router.callback_query(F.data == "edit_field:article")
async def cb_edit_article(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductState.waiting_for_new_article)
    await callback.message.edit_text("🏷️ Введите новый артикул товара:")
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


@router.message(EditProductState.waiting_for_new_article)
async def process_new_article(message: Message, state: FSMContext):
    data = await state.get_data()
    await update_product_article(data["product_id"], message.text.strip())
    await state.clear()
    await message.answer("✅ Артикул обновлён!")


@router.message(EditProductState.waiting_for_new_expiry)
async def process_new_expiry(message: Message, state: FSMContext):
    text = message.text.strip()
    for fmt in ["%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"]:
        try:
            date_obj = datetime.strptime(text, fmt)
            expiry_str = date_obj.strftime("%Y-%m-%d")
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

    if len(stores) == 1:
        await state.update_data(store_id=stores[0]["id"], store_name=stores[0]["name"])
        await state.set_state(AddProductState.waiting_for_name)
        await message.answer(
            f"➕ Добавление товара в <b>{stores[0]['name']}</b>\n\nВведите название товара:",
            parse_mode="HTML"
        )
    else:
        await ask_select_store(message, stores, "add_store")


@router.callback_query(F.data.startswith("add_store:"))
async def cb_select_store_add(callback: CallbackQuery, state: FSMContext):
    store_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(callback.from_user.id)

    role = await get_member_role(user["id"], store_id)
    if not role:
        await callback.answer("❌ Нет доступа к этому магазину", show_alert=True)
        return

    user_stores = await get_user_stores(user["id"])
    store = next((s for s in user_stores if s["id"] == store_id), None)
    store_name = store["name"] if store else f"Магазин #{store_id}"

    await state.update_data(store_id=store_id, store_name=store_name)
    await state.set_state(AddProductState.waiting_for_name)
    await callback.message.edit_text(
        f"➕ Добавление товара в <b>{store_name}</b>\n\nВведите название товара:",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AddProductState.waiting_for_name)
async def process_product_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Название слишком короткое. Попробуйте снова:")
        return
    await state.update_data(product_name=name)
    await state.set_state(AddProductState.waiting_for_article)
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭️ Пропустить", callback_data="skip_article")
    await message.answer("Введите артикул товара (или пропустите):", reply_markup=builder.as_markup())


@router.callback_query(F.data == "skip_article")
async def cb_skip_article(callback: CallbackQuery, state: FSMContext):
    await state.update_data(article="")
    await state.set_state(AddProductState.waiting_for_expiry)
    await callback.message.edit_text(
        "📅 Введите срок годности в формате ДД.ММ.ГГГГ\nНапример: 15.06.2025"
    )
    await callback.answer()


@router.message(AddProductState.waiting_for_article)
async def process_article(message: Message, state: FSMContext):
    await state.update_data(article=message.text.strip())
    await _ask_category(message, state)


@router.callback_query(F.data == "skip_article")
async def cb_skip_article(callback: CallbackQuery, state: FSMContext):
    await state.update_data(article="")
    await _ask_category(callback.message, state)
    await callback.answer()


async def _ask_category(message: Message, state: FSMContext):
    data = await state.get_data()
    store_id = data.get("store_id")

    # Берём существующие категории магазина
    from db.database import get_store_categories
    categories = await get_store_categories(store_id)

    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.button(text=cat, callback_data=f"set_category:{cat}")
    builder.button(text="✏️ Своя категория", callback_data="custom_category")
    builder.button(text="⏭️ Без категории",  callback_data="skip_category")
    builder.adjust(2)

    await state.set_state(AddProductState.waiting_for_category)
    await message.answer("📂 Выберите категорию товара:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("set_category:"))
async def cb_set_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    await state.update_data(category=category)
    await state.set_state(AddProductState.waiting_for_expiry)
    await callback.message.edit_text("📅 Введите срок годности в формате ДД.ММ.ГГГГ\nНапример: 15.06.2025")
    await callback.answer()


@router.callback_query(F.data == "custom_category")
async def cb_custom_category(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✏️ Введите название категории:")
    await callback.answer()
    # Остаёмся в waiting_for_category, следующее сообщение — текст категории


@router.message(AddProductState.waiting_for_category)
async def process_custom_category(message: Message, state: FSMContext):
    await state.update_data(category=message.text.strip())
    await state.set_state(AddProductState.waiting_for_expiry)
    await message.answer("📅 Введите срок годности в формате ДД.ММ.ГГГГ\nНапример: 15.06.2025")


@router.callback_query(F.data == "skip_category")
async def cb_skip_category(callback: CallbackQuery, state: FSMContext):
    await state.update_data(category="Общее")
    await state.set_state(AddProductState.waiting_for_expiry)
    await callback.message.edit_text("📅 Введите срок годности в формате ДД.ММ.ГГГГ\nНапример: 15.06.2025")
    await callback.answer()


@router.message(AddProductState.waiting_for_expiry)
async def process_expiry_date(message: Message, state: FSMContext):
    text = message.text.strip()
    for fmt in ["%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"]:
        try:
            date_obj = datetime.strptime(text, fmt)
            expiry_str = date_obj.strftime("%Y-%m-%d")
            break
        except ValueError:
            continue
    else:
        await message.answer("❌ Неверный формат. Введите дату как ДД.ММ.ГГГГ\nНапример: 20.06.2025")
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
    expiry_date=data["expiry_date"],
    article=data.get("article", ""),
    category=data.get("category", "Общее"),   # ← добавить
)

    await create_notifications_for_batch(batch_id, data["expiry_date"])

    expiry_dt = datetime.strptime(data["expiry_date"], "%Y-%m-%d")
    expiry_display = expiry_dt.strftime("%d.%m.%Y")
    
    # Исправлено вычитание: сравниваем только даты (date), чтобы избежать багов с часами
    days_left = (expiry_dt.date() - date.today()).days
    article_text = f"\nАртикул: <code>{data['article']}</code>" if data.get("article") else ""

    await message.answer(
        f"✅ Товар добавлен!\n\n"
        f"📦 <b>{data['product_name']}</b>{article_text}\n"
        f"Кол-во: {qty} шт.\n"
        f"Срок годности: {expiry_display}\n"
        f"Осталось дней: {days_left}",
        parse_mode="HTML"
    )
