from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db.database import get_or_create_user, get_user_stores, use_invite_code
from keyboards.main import main_menu_kb

router = Router()


class JoinStoreState(StatesGroup):
    waiting_for_code = State()


from db.database import get_or_create_user, get_user_stores, use_invite_code, get_store_stats  # добавить get_store_stats

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username
    )
    stores = await get_user_stores(user["id"])

    text = (
        "🌿 <b>FreshBot</b> — контроль сроков годности\n\n"
        f"Привет, <b>{message.from_user.first_name}</b>!\n"
    )

    if stores:
        text += f"Ваши магазины ({len(stores)}):\n"
        for s in stores:
            text += f"  • {s['name']} [{s['role']}]\n"

        # Напоминание о просроченных
        warnings = []
        for s in stores:
            stats = await get_store_stats(s["id"])
            expired = stats.get("expired") or 0
            expires_3d = stats.get("expires_3d") or 0
            if expired:
                warnings.append(f"❌ <b>{s['name']}</b>: {expired} просрочено")
            if expires_3d:
                warnings.append(f"⚠️ <b>{s['name']}</b>: {expires_3d} истекают в ближайшие 3 дня")

        if warnings:
            text += "\n⚠️ <b>Внимание:</b>\n" + "\n".join(warnings) + "\n"

        text += "\nВыберите действие:"
    else:
        text += "У вас пока нет магазинов. Создайте первый или присоединитесь по коду."

    await message.answer(text, reply_markup=main_menu_kb(stores), parse_mode="HTML")


@router.message(F.text == "❓ Помощь")
@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📋 <b>Команды FreshBot</b>\n\n"
        "/start — главное меню\n"
        "/newstore — создать магазин\n"
        "/join — войти по invite-коду\n"
        "/leave — покинуть магазин\n"
        "/products — список товаров\n"
        "/add — добавить товар\n"
        "/invite — создать приглашение\n"
        "/members — сотрудники магазина\n"
        "/kick — исключить сотрудника\n"
        "/rename — переименовать магазин\n"
        "/stats — статистика\n"
        "/help — эта справка",
        parse_mode="HTML"
    )


@router.message(F.text == "🔑 Войти по коду")
@router.message(Command("join"))
async def cmd_join(message: Message, state: FSMContext):
    await state.set_state(JoinStoreState.waiting_for_code)
    await message.answer(
        "🔗 Введите invite-код для присоединения к магазину:"
    )


@router.message(JoinStoreState.waiting_for_code)
async def process_invite_code(message: Message, state: FSMContext):
    code = message.text.strip()
    user = await get_or_create_user(message.from_user.id)

    result = await use_invite_code(code, user["id"])
    await state.clear()

    if result:
        stores = await get_user_stores(user["id"])
        await message.answer(
            f"✅ Вы успешно присоединились к магазину!\n"
            f"Роль: <b>{result['role']}</b>\n\n"
            "Используйте кнопку «📦 Товары» или команду /products.",
            reply_markup=main_menu_kb(stores),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "❌ Код недействителен или уже использован.\n"
            "Попросите администратора сгенерировать новый."
        )
