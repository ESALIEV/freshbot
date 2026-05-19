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


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username
    )
    stores = await get_user_stores(user["id"])
    name = message.from_user.first_name

    if not stores:
        text = (
            f"🌿 <b>Добро пожаловать в FreshBot!</b>\n\n"
            f"Привет, <b>{name}</b>! 👋\n\n"
            f"Я помогу вам контролировать сроки годности товаров "
            f"и никогда не забывать о просроченной продукции.\n\n"
            f"<b>Что я умею:</b>\n"
            f"📦 Вести список товаров с датами\n"
            f"🔔 Напоминать за 3 дня, 1 день и в день истечения\n"
            f"👥 Работать с командой сотрудников\n"
            f"📊 Показывать статистику и экспортировать отчёты\n\n"
            f"<b>Чтобы начать:</b>\n"
            f"➡️ Создайте свой магазин — кнопка ниже\n"
            f"➡️ Или войдите по invite-коду от администратора"
        )
    else:
        text = (
            f"🌿 <b>FreshBot</b>\n\n"
            f"С возвращением, <b>{name}</b>! 👋\n\n"
        )
        text += f"🏪 Ваши магазины ({len(stores)}):\n"
        for s in stores:
            role_emoji = "👑" if s["role"] == "admin" else "👷"
            text += f"  {role_emoji} {s['name']}\n"
        text += "\nВыберите действие в меню ниже 👇"

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
