from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb(stores: list = None) -> ReplyKeyboardMarkup:
    buttons = []

    if stores:
        buttons.append([KeyboardButton(text="📦 Товары"), KeyboardButton(text="➕ Добавить")])
        buttons.append([KeyboardButton(text="🏪 Мои магазины"), KeyboardButton(text="🔗 Пригласить")])
    else:
        buttons.append([KeyboardButton(text="🏪 Создать магазин"), KeyboardButton(text="🔑 Войти по коду")])

    buttons.append([KeyboardButton(text="❓ Помощь")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def stores_list_kb(stores: list) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"🏪 {s['name']}", callback_data=f"store:{s['id']}")]
        for s in stores
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
