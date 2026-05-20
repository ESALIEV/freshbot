remove_store_member, leave_store, rename_store
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.database import (
    get_or_create_user, create_store, get_user_stores,
    get_member_role, create_invite_code, get_store_members
)

router = Router()


class NewStoreState(StatesGroup):
    waiting_for_name = State()


class RenameStoreState(StatesGroup):
    waiting_for_new_name = State()


class InviteState(StatesGroup):
    waiting_for_max_uses = State()


# ──── СОЗДАНИЕ ────

@router.message(Command("newstore"))
@router.message(F.text == "🏪 Создать магазин")
async def cmd_new_store(message: Message, state: FSMContext):
    await state.set_state(NewStoreState.waiting_for_name)
    await message.answer("🏪 Введите название нового магазина:")


@router.message(NewStoreState.waiting_for_name)
async def process_store_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Название слишком короткое. Попробуйте снова:")
        return
    user = await get_or_create_user(message.from_user.id)
    store = await create_store(name, user["id"])
    await state.clear()
    stores = await get_user_stores(user["id"])
    from keyboards.main import main_menu_kb
    await message.answer(
        f"✅ Магазин <b>{store['name']}</b> создан!\n\n"
        f"Вы — администратор. Пригласите сотрудников командой /invite\n"
        f"Добавьте первый товар командой /add",
        reply_markup=main_menu_kb(stores),
        parse_mode="HTML"
    )


# ──── МОИ МАГАЗИНЫ ────

@router.message(Command("mystores"))
@router.message(F.text == "🏪 Мои магазины")
async def cmd_my_stores(message: Message):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])
    if not stores:
        await message.answer("У вас нет магазинов.\n/newstore — создать\n/join — присоединиться")
        return
    text = "🏪 <b>Ваши магазины:</b>\n\n"
    for i, s in enumerate(stores, 1):
        role_emoji = "👑" if s["role"] == "admin" else "👷"
        text += f"{i}. {role_emoji} <b>{s['name']}</b> (ID: {s['id']})\n"
    await message.answer(text, parse_mode="HTML")


# ──── ПЕРЕИМЕНОВАНИЕ ────

@router.message(Command("rename"))
async def cmd_rename(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])
    admin_stores = [s for s in stores if s["role"] == "admin"]

    if not admin_stores:
        await message.answer("❌ У вас нет прав администратора ни в одном магазине.")
        return

    if len(admin_stores) == 1:
        await state.update_data(rename_store_id=admin_stores[0]["id"], rename_store_name=admin_stores[0]["name"])
        await state.set_state(RenameStoreState.waiting_for_new_name)
        await message.answer(
            f"✏️ Текущее название: <b>{admin_stores[0]['name']}</b>\n\n"
            f"Введите новое название:",
            parse_mode="HTML"
        )
    else:
        builder = InlineKeyboardBuilder()
        for s in admin_stores:
            builder.button(text=f"🏪 {s['name']}", callback_data=f"rename_store:{s['id']}")
        builder.adjust(1)
        await message.answer("Какой магазин переименовать?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("rename_store:"))
async def cb_rename_store(callback: CallbackQuery, state: FSMContext):
    store_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(callback.from_user.id)
    role = await get_member_role(user["id"], store_id)
    if role != "admin":
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    stores = await get_user_stores(user["id"])
    store = next((s for s in stores if s["id"] == store_id), None)
    await state.update_data(rename_store_id=store_id, rename_store_name=store["name"] if store else "")
    await state.set_state(RenameStoreState.waiting_for_new_name)
    await callback.message.edit_text(
        f"✏️ Текущее название: <b>{store['name']}</b>\n\nВведите новое название:",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(RenameStoreState.waiting_for_new_name)
async def process_rename(message: Message, state: FSMContext):
    new_name = message.text.strip()
    if len(new_name) < 2:
        await message.answer("❌ Название слишком короткое. Попробуйте снова:")
        return
    data = await state.get_data()
    store_id = data["rename_store_id"]
    old_name = data["rename_store_name"]
    await state.clear()

    from db.database import rename_store
    await rename_store(store_id, new_name)

    await message.answer(
        f"✅ Магазин переименован!\n"
        f"<s>{old_name}</s> → <b>{new_name}</b>",
        parse_mode="HTML"
    )


# ──── ПРИГЛАШЕНИЯ ────

@router.message(Command("invite"))
@router.message(F.text == "🔗 Пригласить")
async def cmd_invite(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])
    admin_stores = [s for s in stores if s["role"] == "admin"]

    if not admin_stores:
        await message.answer("❌ У вас нет прав администратора ни в одном магазине.")
        return

    if len(admin_stores) > 1:
        builder = InlineKeyboardBuilder()
        for s in admin_stores:
            builder.button(text=f"🏪 {s['name']}", callback_data=f"invite_store:{s['id']}")
        builder.adjust(1)
        await message.answer("Для какого магазина создать ссылку?", reply_markup=builder.as_markup())
        return

    await state.update_data(invite_store_id=admin_stores[0]["id"], invite_store_name=admin_stores[0]["name"])
    await _ask_max_uses(message)


@router.callback_query(F.data.startswith("invite_store:"))
async def cb_invite_store(callback: CallbackQuery, state: FSMContext):
    store_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(callback.from_user.id)
    role = await get_member_role(user["id"], store_id)
    if role != "admin":
        await callback.answer("❌ Нет прав администратора", show_alert=True)
        return
    stores = await get_user_stores(user["id"])
    store = next((s for s in stores if s["id"] == store_id), None)
    await state.update_data(invite_store_id=store_id, invite_store_name=store["name"] if store else "")
    await _ask_max_uses(callback.message)
    await callback.answer()


async def _ask_max_uses(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="1 человек",        callback_data="invite_uses:1")
    builder.button(text="5 человек",        callback_data="invite_uses:5")
    builder.button(text="10 человек",       callback_data="invite_uses:10")
    builder.button(text="Без ограничений",  callback_data="invite_uses:999")
    builder.adjust(2)
    await message.answer("👥 На сколько человек рассчитана ссылка?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("invite_uses:"))
async def cb_invite_uses(callback: CallbackQuery, state: FSMContext):
    max_uses = int(callback.data.split(":")[1])
    data = await state.get_data()
    store_id = data.get("invite_store_id")
    store_name = data.get("invite_store_name", "")

    if not store_id:
        await callback.answer("Ошибка: магазин не выбран", show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)
    code = await create_invite_code(store_id, user["id"], max_uses=max_uses)
    uses_text = "без ограничений" if max_uses == 999 else f"до {max_uses} чел."

    await callback.message.edit_text(
        f"🔗 Invite-код для магазина <b>{store_name}</b>:\n\n"
        f"<code>{code}</code>\n\n"
        f"Действителен 7 дней · {uses_text}\n"
        f"Отправьте сотруднику — пусть введёт /join",
        parse_mode="HTML"
    )
    await callback.answer()


# ──── СОТРУДНИКИ ────

@router.message(Command("members"))
async def cmd_members(message: Message):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])
    if not stores:
        await message.answer("У вас нет магазинов.")
        return
    store_id = stores[0]["id"]
    members = await get_store_members(store_id)
    text = "👥 <b>Сотрудники магазина:</b>\n\n"
    for m in members:
        emoji = "👑" if m["role"] == "admin" else "👷"
        name = f"@{m['username']}" if m["username"] else f"ID {m['telegram_id']}"
        text += f"{emoji} {name} — {m['role']}\n"
    await message.answer(text, parse_mode="HTML")


# ──── ИСКЛЮЧЕНИЕ УЧАСТНИКА ────

@router.message(Command("kick"))
async def cmd_kick(message: Message):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])
    admin_stores = [s for s in stores if s["role"] == "admin"]

    if not admin_stores:
        await message.answer("❌ У вас нет прав администратора.")
        return

    store_id = admin_stores[0]["id"]
    members = await get_store_members(store_id)
    other_members = [m for m in members if m["telegram_id"] != user["telegram_id"]]

    if not other_members:
        await message.answer("В магазине нет других участников.")
        return

    builder = InlineKeyboardBuilder()
    for m in other_members:
        emoji = "👑" if m["role"] == "admin" else "👷"
        name = f"@{m['username']}" if m["username"] else f"ID {m['telegram_id']}"
        builder.button(
            text=f"{emoji} {name}",
            callback_data=f"kick_confirm:{store_id}:{m['telegram_id']}"
        )
    builder.button(text="❌ Отмена", callback_data="kick_cancel")
    builder.adjust(1)

    await message.answer("👤 Кого исключить из магазина?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("kick_confirm:"))
async def cb_kick_confirm(callback: CallbackQuery):
    _, store_id_str, target_telegram_id_str = callback.data.split(":")
    store_id = int(store_id_str)
    target_telegram_id = int(target_telegram_id_str)

    user = await get_or_create_user(callback.from_user.id)
    role = await get_member_role(user["id"], store_id)
    if role != "admin":
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    members = await get_store_members(store_id)
    target = next((m for m in members if m["telegram_id"] == target_telegram_id), None)
    if not target:
        await callback.answer("Участник не найден", show_alert=True)
        return

    name = f"@{target['username']}" if target["username"] else f"ID {target_telegram_id}"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, исключить", callback_data=f"kick_execute:{store_id}:{target_telegram_id}")
    builder.button(text="❌ Отмена", callback_data="kick_cancel")
    builder.adjust(2)

    await callback.message.edit_text(
        f"⚠️ Исключить <b>{name}</b> из магазина?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("kick_execute:"))
async def cb_kick_execute(callback: CallbackQuery):
    _, store_id_str, target_telegram_id_str = callback.data.split(":")
    store_id = int(store_id_str)
    target_telegram_id = int(target_telegram_id_str)

    user = await get_or_create_user(callback.from_user.id)
    role = await get_member_role(user["id"], store_id)
    if role != "admin":
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    from db.database import kick_member
    await kick_member(store_id, target_telegram_id)

    await callback.message.edit_text("✅ Участник исключён из магазина.")
    await callback.answer("Готово!")


@router.callback_query(F.data == "kick_cancel")
async def cb_kick_cancel(callback: CallbackQuery):
    await callback.message.edit_text("❌ Исключение отменено.")
    await callback.answer()


# ──── ВЫХОД ИЗ МАГАЗИНА ────

@router.message(Command("leave"))
async def cmd_leave(message: Message):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])

    if not stores:
        await message.answer("У вас нет магазинов.")
        return

    if len(stores) == 1:
        store = stores[0]
        if store["role"] == "admin":
            await message.answer(
                "⚠️ Вы единственный администратор магазина <b>{}</b>.\n"
                "Сначала назначьте другого администратора или удалите магазин.".format(store["name"]),
                parse_mode="HTML"
            )
            return
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Да, покинуть", callback_data=f"leave_confirm:{store['id']}")
        builder.button(text="❌ Отмена", callback_data="leave_cancel")
        builder.adjust(2)
        await message.answer(
            f"🚪 Покинуть магазин <b>{store['name']}</b>?",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    else:
        builder = InlineKeyboardBuilder()
        for s in stores:
            if s["role"] != "admin":
                builder.button(text=f"🏪 {s['name']}", callback_data=f"leave_confirm:{s['id']}")
        builder.button(text="❌ Отмена", callback_data="leave_cancel")
        builder.adjust(1)
        await message.answer("Из какого магазина вы хотите выйти?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("leave_confirm:"))
async def cb_leave_confirm(callback: CallbackQuery):
    store_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(callback.from_user.id)

    from db.database import kick_member
    await kick_member(store_id, user["telegram_id"])

    stores = await get_user_stores(user["id"])
    from keyboards.main import main_menu_kb
    await callback.message.edit_text("🚪 Вы покинули магазин.")
    await callback.message.answer(
        "Главное меню обновлено.",
        reply_markup=main_menu_kb(stores)
    )
    await callback.answer()


@router.callback_query(F.data == "leave_cancel")
async def cb_leave_cancel(callback: CallbackQuery):
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()

from db.database import remove_store_member, leave_store, rename_store  # добавить в импорты вверху

# ──── ПЕРЕИМЕНОВАНИЕ ────

class RenameStoreState(StatesGroup):
    waiting_for_new_name = State()


@router.message(Command("renamstore"))
async def cmd_rename_store(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])
    admin_stores = [s for s in stores if s["role"] == "admin"]

    if not admin_stores:
        await message.answer("❌ У вас нет прав администратора.")
        return

    if len(admin_stores) == 1:
        await state.update_data(rename_store_id=admin_stores[0]["id"],
                                rename_store_name=admin_stores[0]["name"])
        await state.set_state(RenameStoreState.waiting_for_new_name)
        await message.answer(f"✏️ Новое название для <b>{admin_stores[0]['name']}</b>:",
                             parse_mode="HTML")
    else:
        builder = InlineKeyboardBuilder()
        for s in admin_stores:
            builder.button(text=f"🏪 {s['name']}", callback_data=f"rename_store:{s['id']}")
        builder.adjust(1)
        await message.answer("Какой магазин переименовать?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("rename_store:"))
async def cb_rename_store(callback: CallbackQuery, state: FSMContext):
    store_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(callback.from_user.id)
    if await get_member_role(user["id"], store_id) != "admin":
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    stores = await get_user_stores(user["id"])
    store = next((s for s in stores if s["id"] == store_id), None)
    await state.update_data(rename_store_id=store_id, rename_store_name=store["name"] if store else "")
    await state.set_state(RenameStoreState.waiting_for_new_name)
    await callback.message.edit_text(f"✏️ Новое название для <b>{store['name']}</b>:", parse_mode="HTML")
    await callback.answer()


@router.message(RenameStoreState.waiting_for_new_name)
async def process_rename_store(message: Message, state: FSMContext):
    new_name = message.text.strip()
    if len(new_name) < 2:
        await message.answer("❌ Слишком короткое. Попробуйте снова:")
        return
    data = await state.get_data()
    await rename_store(data["rename_store_id"], new_name)
    await state.clear()
    await message.answer(f"✅ Магазин переименован в <b>{new_name}</b>!", parse_mode="HTML")


# ──── УДАЛЕНИЕ УЧАСТНИКА ────

@router.message(Command("kick"))
async def cmd_kick(message: Message):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])
    admin_stores = [s for s in stores if s["role"] == "admin"]

    if not admin_stores:
        await message.answer("❌ У вас нет прав администратора.")
        return

    store_id = admin_stores[0]["id"]
    members = await get_store_members(store_id)
    # Показываем всех кроме себя
    others = [m for m in members if m["telegram_id"] != message.from_user.id]

    if not others:
        await message.answer("В магазине нет других участников.")
        return

    builder = InlineKeyboardBuilder()
    for m in others:
        name = f"@{m['username']}" if m["username"] else f"ID {m['telegram_id']}"
        emoji = "👑" if m["role"] == "admin" else "👷"
        builder.button(
            text=f"{emoji} {name}",
            callback_data=f"kick_confirm:{store_id}:{m['telegram_id']}"
        )
    builder.adjust(1)
    await message.answer("👤 Кого исключить из магазина?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("kick_confirm:"))
async def cb_kick_confirm(callback: CallbackQuery):
    _, store_id_str, target_tg_id_str = callback.data.split(":")
    store_id = int(store_id_str)
    target_tg_id = int(target_tg_id_str)

    user = await get_or_create_user(callback.from_user.id)
    if await get_member_role(user["id"], store_id) != "admin":
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    members = await get_store_members(store_id)
    target = next((m for m in members if m["telegram_id"] == target_tg_id), None)
    if not target:
        await callback.answer("Участник не найден", show_alert=True)
        return

    name = f"@{target['username']}" if target["username"] else f"ID {target_tg_id}"
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, исключить", callback_data=f"kick_do:{store_id}:{target_tg_id}")
    builder.button(text="❌ Отмена",        callback_data="kick_cancel")
    builder.adjust(2)
    await callback.message.edit_text(
        f"Исключить <b>{name}</b> из магазина?",
        reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("kick_do:"))
async def cb_kick_do(callback: CallbackQuery):
    _, store_id_str, target_tg_id_str = callback.data.split(":")
    store_id = int(store_id_str)
    target_tg_id = int(target_tg_id_str)

    user = await get_or_create_user(callback.from_user.id)
    if await get_member_role(user["id"], store_id) != "admin":
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    # Найти user.id по telegram_id
    from db.database import get_or_create_user as goc
    target_user = await goc(target_tg_id)
    await remove_store_member(target_user["id"], store_id)

    members = await get_store_members(store_id)
    target_name = f"@{next((m['username'] for m in members if m['telegram_id'] == target_tg_id), None) or target_tg_id}"
    await callback.message.edit_text(f"✅ Участник исключён.")
    await callback.answer("Готово!")

    # Уведомить исключённого
    try:
        await callback.bot.send_message(
            target_tg_id,
            "❌ Вас исключили из магазина."
        )
    except Exception:
        pass


@router.callback_query(F.data == "kick_cancel")
async def cb_kick_cancel(callback: CallbackQuery):
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()


# ──── ВЫХОД ИЗ МАГАЗИНА ────

@router.message(Command("leave"))
async def cmd_leave(message: Message):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])

    if not stores:
        await message.answer("У вас нет магазинов.")
        return

    if len(stores) == 1:
        store = stores[0]
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Да, выйти",  callback_data=f"leave_confirm:{store['id']}")
        builder.button(text="❌ Отмена",      callback_data="leave_cancel")
        builder.adjust(2)
        await message.answer(
            f"Выйти из магазина <b>{store['name']}</b>?",
            reply_markup=builder.as_markup(), parse_mode="HTML"
        )
    else:
        builder = InlineKeyboardBuilder()
        for s in stores:
            builder.button(text=f"🏪 {s['name']}", callback_data=f"leave_confirm:{s['id']}")
        builder.adjust(1)
        await message.answer("Из какого магазина выйти?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("leave_confirm:"))
async def cb_leave_confirm(callback: CallbackQuery):
    store_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(callback.from_user.id)
    success = await leave_store(user["id"], store_id)

    if success:
        stores = await get_user_stores(user["id"])
        from keyboards.main import main_menu_kb
        await callback.message.edit_text("✅ Вы вышли из магазина.")
        await callback.bot.send_message(
            callback.from_user.id,
            "Выберите действие:",
            reply_markup=main_menu_kb(stores)
        )
    else:
        await callback.message.edit_text(
            "❌ Нельзя выйти — вы единственный администратор.\n"
            "Назначьте другого админа или удалите магазин."
        )
    await callback.answer()


@router.callback_query(F.data == "leave_cancel")
async def cb_leave_cancel(callback: CallbackQuery):
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()
