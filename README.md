# 🌿 FreshBot — Контроль сроков годности

Telegram-бот для управления сроками годности товаров в магазинах.

## Быстрый старт

```bash
# 1. Клонировать / скопировать проект
cd freshbot

# 2. Создать виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить переменные окружения
cp .env.example .env
# Открыть .env и вставить токен бота

# 5. Запустить
python bot.py
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Главное меню |
| `/newstore` | Создать магазин |
| `/join` | Войти по invite-коду |
| `/products` | Список товаров |
| `/add` | Добавить товар |
| `/invite` | Создать приглашение |
| `/mystores` | Мои магазины |
| `/members` | Сотрудники магазина |

## Структура проекта

```
freshbot/
├── bot.py              # Точка входа
├── config.py           # Конфиг
├── requirements.txt
├── .env.example
├── db/
│   └── database.py     # Модели БД + все запросы
├── handlers/
│   ├── start.py        # /start, /join
│   ├── store.py        # /newstore, /invite, /members
│   └── products.py     # /products, /add
├── services/
│   └── scheduler.py    # Планировщик уведомлений
└── keyboards/
    └── main.py         # Клавиатуры
```

## Этапы разработки

- [x] **Этап 1 (MVP)** — 1 магазин, товары, уведомления
- [ ] **Этап 2** — роли, invite-коды ✅ частично готово
- [ ] **Этап 3** — несколько магазинов, улучшенный UX
- [ ] **Этап 4** — аналитика, PostgreSQL, масштабирование

## Деплой на Railway

1. Создать проект на [railway.app](https://railway.app)
2. Подключить GitHub репозиторий
3. Добавить переменную `BOT_TOKEN` в Settings → Variables
4. Deploy 🚀
