from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db.database import (
    get_or_create_user, create_store, get_user_stores,
    get_member_role, create_invite_code, get_store_members
)

router = Router()


class NewStoreState(StatesGroup):
    waiting_for_name = State()


@router.message(Command("newstore"))
@router.message(F.text == "🏪 Создать магазин")
async def cmd_new_store(message: Message, state: FSMContext):
    await state.set_state(NewStoreState.waiting_for_name)
    await message.answer(
        "🏪 Введите название нового магазина:"
    )


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
        await message.answer(
            "У вас нет магазинов.\n"
            "/newstore — создать\n"
            "/join — присоединиться"
        )
        return

    text = "🏪 <b>Ваши магазины:</b>\n\n"
    for i, s in enumerate(stores, 1):
        role_emoji = "👑" if s["role"] == "admin" else "👷"
        text += f"{i}. {role_emoji} <b>{s['name']}</b> (ID: {s['id']})\n"

    await message.answer(text, parse_mode="HTML")


@router.message(Command("invite"))
@router.message(F.text == "🔗 Пригласить")
async def cmd_invite(message: Message):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])

    admin_stores = [s for s in stores if s["role"] == "admin"]

    if not admin_stores:
        await message.answer("❌ У вас нет прав администратора ни в одном магазине.")
        return

    store = admin_stores[0]
    code = await create_invite_code(store["id"], user["id"])
    await message.answer(
        f"🔗 Invite-код для магазина <b>{store['name']}</b>:\n\n"
        f"<code>{code}</code>\n\n"
        f"Действителен 7 дней. Отправьте сотруднику — пусть введёт /join",
        parse_mode="HTML"
    )


@router.message(Command("members"))
async def cmd_members(message: Message):
    user = await get_or_create_user(message.from_user.id)
    stores = await get_user_stores(user["id"])

    if not stores:
        await message.answer("У вас нет магазинов.")
        return

    store_id = stores[0]["id"]
    members = await get_store_members(store_id)
    text = f"👥 <b>Сотрудники магазина:</b>\n\n"
    for m in members:
        emoji = "👑" if m["role"] == "admin" else "👷"
        name = f"@{m['username']}" if m["username"] else f"ID {m['telegram_id']}"
        text += f"{emoji} {name} — {m['role']}\n"

    await message.answer(text, parse_mode="HTML")
