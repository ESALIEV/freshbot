from aiogram import Router, F
from aiogram.types import Message
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


class InviteState(StatesGroup):
    waiting_for_max_uses = State()


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


# ──── INVITE с выбором max_uses (пункт 3) ────

@router.message(Command("invite"))
@router.message(F.text == "🔗 Пригласить")
async def cmd_invite(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])
    admin_stores = [s for s in stores if s["role"] == "admin"]

    if not admin_stores:
        await message.answer("❌ У вас нет прав администратора ни в одном магазине.")
        return

    # Если несколько магазинов-admin — спрашиваем какой
    if len(admin_stores) > 1:
        builder = InlineKeyboardBuilder()
        for s in admin_stores:
            builder.button(text=f"🏪 {s['name']}", callback_data=f"invite_store:{s['id']}")
        builder.adjust(1)
        await message.answer("Для какого магазина создать ссылку?", reply_markup=builder.as_markup())
        return

    await state.update_data(invite_store_id=admin_stores[0]["id"], invite_store_name=admin_stores[0]["name"])
    await _ask_max_uses(message, state)


@router.callback_query(F.data.startswith("invite_store:"))
async def cb_invite_store(callback, state: FSMContext):
    store_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(callback.from_user.id)
    role = await get_member_role(user["id"], store_id)
    if role != "admin":
        await callback.answer("❌ Нет прав администратора", show_alert=True)
        return
    stores = await get_user_stores(user["id"])
    store = next((s for s in stores if s["id"] == store_id), None)
    await state.update_data(invite_store_id=store_id, invite_store_name=store["name"] if store else "")
    await _ask_max_uses(callback.message, state)
    await callback.answer()


async def _ask_max_uses(message: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="1 человек", callback_data="invite_uses:1")
    builder.button(text="5 человек", callback_data="invite_uses:5")
    builder.button(text="10 человек", callback_data="invite_uses:10")
    builder.button(text="Без ограничений", callback_data="invite_uses:999")
    builder.adjust(2)
    await message.answer(
        "👥 На сколько человек рассчитана ссылка?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("invite_uses:"))
async def cb_invite_uses(callback, state: FSMContext):
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
