import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL", "freshbot.db")

# Уведомлять за N дней до истечения
NOTIFY_DAYS_BEFORE = [3, 1, 0]  # 0 = в день истечения
