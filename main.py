import asyncio
import logging
import os
import random
import time
from datetime import datetime, timedelta

import aiohttp
import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# ============================================================================
# 1. ENVIRONMENT & LOGGING CONFIGURATION
# ============================================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8874772514:AAENhQ-XqlISfycu0snhAnyx8JI85qjhhlA")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
GEMINI_API_KEYS_RAW = os.getenv("GEMINI_API_KEYS", "")
DB_PATH = os.getenv("DB_PATH", "bot_database.db")
ADMIN_PASSWORD = "mhdvmim"
FREE_DAILY_LIMIT = 100
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. .env faylida BOT_TOKEN ni belgilang.")
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS topilmadi. .env faylida ADMIN_IDS ni belgilang (vergul bilan).")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("mhdv_bot")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

router = Router(name="main_router")
dp.include_router(router)

# In-memory runtime state (RAM cache) that admin can flush from the admin panel.
RUNTIME_CACHE: dict = {
    "bot_enabled": True,
    "bridge_targets": {},        # admin_id -> target_user_id
    "admin_awaiting_reply_from": {},  # target_user_id -> admin_id (for reverse lookup)
}

# ============================================================================
# 2. DEFAULT EXPERT SECTIONS (20 TA TAYYOR BO'LIM)
# ============================================================================

DEFAULT_SECTIONS = [
    (
        "🇬🇧 Ingliz tili repetitori",
        "Siz professional ingliz tili o'qituvchisisiz. Foydalanuvchiga grammatika, so'z boyligi, "
        "talaffuz va nutq amaliyoti bo'yicha yordam bering. Xatolarini muloyimlik bilan tuzating, "
        "misollar keltiring va darajasiga mos oddiy tildan foydalaning.",
    ),
    (
        "🔤 Inglizcha-o'zbekcha tarjimon",
        "Siz professional tarjimonsiz. Foydalanuvchi yuborgan matnni ingliz tilidan o'zbek tiliga yoki "
        "o'zbek tilidan ingliz tiliga aniq, tabiiy va kontekstga mos tarzda tarjima qiling. Zarur bo'lsa "
        "muqobil variantlarni ham taklif eting.",
    ),
    (
        "🗓️ Kunlik shaxsiy reja tuzuvchi",
        "Siz shaxsiy vaqt boshqaruvi bo'yicha maslahatchisiz. Foydalanuvchining maqsadlari va vaqtiga "
        "asoslanib, kunlik, amaliy va bajarish mumkin bo'lgan reja tuzib bering, ustuvorliklarni belgilang.",
    ),
    (
        "💪 Fitness va Salomatlik murabbiyi",
        "Siz sertifikatlangan fitness murabbiysisiz. Foydalanuvchining maqsadi, jismoniy holati va "
        "sharoitiga mos mashqlar va sog'lom turmush tarzi bo'yicha maslahatlar bering. Tibbiy tashxis "
        "qo'ymang, jiddiy holatlarda shifokorga murojaat qilishni tavsiya eting.",
    ),
    (
        "💻 IT va Dasturlash maslahatchisi",
        "Siz tajribali IT arxitektorisiz. Dasturlash tillari, texnologiyalar, arxitektura qarorlari va "
        "karyera yo'nalishi bo'yicha aniq va amaliy maslahatlar bering, kod misollari bilan tushuntiring.",
    ),
    (
        "🐞 Kod xatolarini (Bug) to'g'rilovchi",
        "Siz debugging bo'yicha ekspertsiz. Foydalanuvchi yuborgan kod va xato matnini tahlil qiling, "
        "xatoning sababini aniqlang va to'g'irlangan kod bilan tushuntirish bering.",
    ),
    (
        "📚 Kitoblar va asarlar tahlili",
        "Siz adabiyotshunossiz. Foydalanuvchi so'ragan kitob yoki asarni chuqur tahlil qiling: syujet, "
        "g'oya, qahramonlar va uslub haqida ma'lumot bering.",
    ),
    (
        "💡 Biznes g'oyalar generatori",
        "Siz biznes strategi va startap maslahatchisisiz. Foydalanuvchining qiziqishlari va resurslariga "
        "mos innovatsion, amalga oshiriladigan biznes g'oyalarini taklif qiling, ularning afzallik va "
        "xavflarini tushuntiring.",
    ),
    (
        "📱 SMM va Kontent reja yozuvchi",
        "Siz SMM mutaxassisisiz. Ijtimoiy tarmoqlar uchun kontent reja, post g'oyalari va o'sish "
        "strategiyalarini tuzib bering, targetauditoriyaga mos ohang tanlang.",
    ),
    (
        "💰 Moliyaviy maslahatchi",
        "Siz shaxsiy moliya bo'yicha maslahatchisiz. Byudjetlashtirish, tejamkorlik va moliyaviy "
        "rejalashtirish bo'yicha umumiy va tushunarli maslahatlar bering. Bu professional investitsiya "
        "maslahati emasligini eslatib turing.",
    ),
    (
        "📄 Rezyume va Cover Letter yozuvchi",
        "Siz HR va karyera konsultantisiz. Foydalanuvchi ma'lumotlariga asoslanib professional rezyume "
        "va cover letter matnlarini tuzib bering, ish beruvchiga jozibali qiling.",
    ),
    (
        "🍲 Mazali retseptlar generatori",
        "Siz oshpazsiz. Foydalanuvchining mavjud mahsulotlari yoki xohishiga mos oson va mazali "
        "retseptlarni bosqichma-bosqich yozib bering.",
    ),
    (
        "📖 Uy vazifalarini tushuntiruvchi",
        "Siz sabrli o'qituvchisiz. Foydalanuvchining uy vazifasini tushuntiring, javobni to'g'ridan-to'g'ri "
        "berish o'rniga mavzuni bosqichma-bosqich tushunishiga yordam bering.",
    ),
    (
        "🧠 Psixologik va motivatsion yordamchi",
        "Siz empatik motivatsion yordamchisiz. Foydalanuvchini diqqat bilan tinglang, qo'llab-quvvatlang "
        "va ijobiy fikrlashga undang. Siz professional terapevt emasligingizni va jiddiy holatlarda "
        "mutaxassisga murojaat qilish kerakligini eslatib turing.",
    ),
    (
        "✍️ Imlo va matn tahrirchisi",
        "Siz professional muharrirsiz. Foydalanuvchi yuborgan matnni imlo, punktuatsiya va uslub "
        "jihatidan tahrirlang, tuzatilgan variantni taqdim eting.",
    ),
    (
        "🎨 Brend nomi va LOGO g'oyalari",
        "Siz brending mutaxassisisiz. Foydalanuvchining biznes sohasiga mos original brend nomlari va "
        "logotip konsepsiyalari (rang, shakl, uslub) bo'yicha g'oyalar taklif qiling.",
    ),
    (
        "⏰ Time Management (Vaqtni boshqarish)",
        "Siz samaradorlik bo'yicha koutchsiz. Foydalanuvchiga vaqtni boshqarish texnikalari (Pomodoro, "
        "Eisenhower matritsasi va h.k.) asosida amaliy tavsiyalar bering.",
    ),
    (
        "🎁 Sovg'a g'oyalari generatori",
        "Siz sovg'a tanlash bo'yicha maslahatchisiz. Foydalanuvchi bergan ma'lumotlar (kim uchun, byudjet, "
        "tadbir) asosida ijodiy sovg'a g'oyalarini taklif qiling.",
    ),
    (
        "✈️ Sayohat va marshrut rejalashtiruvchi",
        "Siz sayohat konsultantisiz. Foydalanuvchining manzili, byudjeti va qiziqishlariga mos sayohat "
        "marshrutini kun-bakun tuzib bering.",
    ),
    (
        "🌍 Umumiy bilimlar ensiklopediyasi",
        "Siz keng bilimga ega ensiklopedik yordamchisiz. Foydalanuvchi so'ragan har qanday mavzuda aniq, "
        "ishonchli va tushunarli ma'lumot bering.",
    ),
]

# ============================================================================
# 3. DATABASE LAYER (aiosqlite)
# ============================================================================


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                is_prime INTEGER DEFAULT 0,
                prime_expires_at TEXT,
                daily_requests INTEGER DEFAULT 0,
                last_reset_date TEXT,
                is_blocked INTEGER DEFAULT 0,
                created_at TEXT
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_string TEXT UNIQUE,
                is_active INTEGER DEFAULT 1,
                last_error_time TEXT,
                usage_count INTEGER DEFAULT 0
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT,
                channel_title TEXT,
                channel_link TEXT
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                section_name TEXT,
                system_prompt TEXT,
                created_at TEXT
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                section_id TEXT,
                role TEXT,
                content TEXT,
                timestamp TEXT
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                order_type TEXT,
                details TEXT,
                status TEXT DEFAULT 'pending',
                receipt_file_id TEXT,
                created_at TEXT
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        await db.commit()

    await seed_default_settings()
    await seed_default_sections()
    await seed_api_keys_from_env()


async def seed_default_settings() -> None:
    defaults = {
        "admin_password": ADMIN_PASSWORD,
        "bot_status": "on",
        "admin_card": "4880 0000 0000 0000",
        "admin_contact_link": "https://t.me/admin",
        "mhdv_info": (
            "👤 <b>MHDV haqida</b>\n\n"
            "Mahmudxonov Ibrohimxon — 2010-yil 5-dekabrda Namangan viloyati Kosonsoy tumanida tug'ilgan, "
            "dasturchi va MHDV brendining asoschisi."
        ),
        "about_bot": "🤖 Ushbu bot sun'iy intellekt asosida ishlovchi ko'p funksiyali yordamchidir.",
        "rules": "📜 Botdan foydalanish qoidalari: hurmatli muloqot qiling, spam yubormang.",
        "socials": "🌐 Ijtimoiy tarmoqlarimiz: Telegram | Instagram | YouTube",
        "quick_tips": "⚡ Tezkor maslahat: bo'limlar orqali AI bilan istalgan mavzuda suhbatlashing!",
        "daily_quote": "💬 “Muvaffaqiyat — har kuni kichik qadamlar qo'yishdan boshlanadi.” — MHDV",
    }
    async with aiosqlite.connect(DB_PATH) as db:
        for key, value in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
        await db.commit()


async def seed_default_sections() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM user_sections WHERE user_id = 0"
        )
        row = await cursor.fetchone()
        if row and row[0] > 0:
            return
        now = datetime.utcnow().isoformat()
        for name, prompt in DEFAULT_SECTIONS:
            await db.execute(
                "INSERT INTO user_sections (user_id, section_name, system_prompt, created_at) "
                "VALUES (0, ?, ?, ?)",
                (name, prompt, now),
            )
        await db.commit()
        logger.info("20 ta standart ekspert bo'lim muvaffaqiyatli qo'shildi.")


async def seed_api_keys_from_env() -> None:
    keys = [k.strip() for k in GEMINI_API_KEYS_RAW.split(",") if k.strip()]
    if not keys:
        logger.warning("GEMINI_API_KEYS .env faylida topilmadi. AI funksiyalari ishlamasligi mumkin.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        for key in keys:
            await db.execute(
                "INSERT OR IGNORE INTO api_keys (key_string, is_active, usage_count) VALUES (?, 1, 0)",
                (key,),
            )
        await db.commit()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return await cursor.fetchone()


async def create_user_if_not_exists(user_id: int, full_name: str, username: str) -> None:
    existing = await get_user(user_id)
    if existing:
        return
    now = datetime.utcnow().isoformat()
    today = datetime.utcnow().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (id, full_name, username, is_prime, prime_expires_at, "
            "daily_requests, last_reset_date, is_blocked, created_at) "
            "VALUES (?, ?, ?, 0, NULL, 0, ?, 0, ?)",
            (user_id, full_name, username or "", today, now),
        )
        await db.commit()


async def reset_daily_if_needed(user_id: int) -> None:
    today = datetime.utcnow().date().isoformat()
    user = await get_user(user_id)
    if not user:
        return
    if user["last_reset_date"] != today:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET daily_requests = 0, last_reset_date = ? WHERE id = ?",
                (today, user_id),
            )
            await db.commit()


async def expire_prime_if_needed(user_id: int) -> None:
    user = await get_user(user_id)
    if not user or not user["is_prime"] or not user["prime_expires_at"]:
        return
    try:
        expires = datetime.fromisoformat(user["prime_expires_at"])
    except ValueError:
        return
    if expires < datetime.utcnow():
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET is_prime = 0, prime_expires_at = NULL WHERE id = ?",
                (user_id,),
            )
            await db.commit()


async def increment_daily_requests(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET daily_requests = daily_requests + 1 WHERE id = ?", (user_id,)
        )
        await db.commit()


async def set_block_status(user_id: int, blocked: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET is_blocked = ? WHERE id = ?", (1 if blocked else 0, user_id)
        )
        await db.commit()


async def grant_prime(user_id: int, months: int) -> None:
    user = await get_user(user_id)
    base = datetime.utcnow()
    if user and user["is_prime"] and user["prime_expires_at"]:
        try:
            existing_expiry = datetime.fromisoformat(user["prime_expires_at"])
            if existing_expiry > base:
                base = existing_expiry
        except ValueError:
            pass
    new_expiry = base + timedelta(days=30 * months)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET is_prime = 1, prime_expires_at = ? WHERE id = ?",
            (new_expiry.isoformat(), user_id),
        )
        await db.commit()


async def revoke_prime(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET is_prime = 0, prime_expires_at = NULL WHERE id = ?", (user_id,)
        )
        await db.commit()


async def get_users_page(page: int, page_size: int = 10):
    offset = page * page_size
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        return await cursor.fetchall()


async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_all_active_user_ids():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM users WHERE is_blocked = 0")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# API keys (Gemini rotatsiya)
# ---------------------------------------------------------------------------


async def get_active_api_keys():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM api_keys WHERE is_active = 1 ORDER BY usage_count ASC"
        )
        return await cursor.fetchall()


async def mark_key_usage(key_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE api_keys SET usage_count = usage_count + 1 WHERE id = ?", (key_id,)
        )
        await db.commit()


async def mark_key_error(key_id: int, deactivate: bool = False) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        if deactivate:
            await db.execute(
                "UPDATE api_keys SET last_error_time = ?, is_active = 0 WHERE id = ?",
                (now, key_id),
            )
        else:
            await db.execute(
                "UPDATE api_keys SET last_error_time = ? WHERE id = ?", (now, key_id)
            )
        await db.commit()


async def add_api_key(key_string: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO api_keys (key_string, is_active, usage_count) VALUES (?, 1, 0)",
                (key_string,),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def count_active_keys() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM api_keys WHERE is_active = 1")
        row = await cursor.fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# Channels (Force subscribe)
# ---------------------------------------------------------------------------


async def get_channels():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM channels")
        return await cursor.fetchall()


async def add_channel(channel_id: str, channel_title: str, channel_link: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO channels (channel_id, channel_title, channel_link) VALUES (?, ?, ?)",
            (channel_id, channel_title, channel_link),
        )
        await db.commit()


async def remove_channel(channel_db_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channels WHERE id = ?", (channel_db_id,))
        await db.commit()


# ---------------------------------------------------------------------------
# Sections (CRUD)
# ---------------------------------------------------------------------------


async def get_visible_sections(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM user_sections WHERE user_id = 0 OR user_id = ? ORDER BY id ASC",
            (user_id,),
        )
        return await cursor.fetchall()


async def get_section_by_id(section_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM user_sections WHERE id = ?", (section_id,))
        return await cursor.fetchone()


async def create_section(user_id: int, name: str, system_prompt: str) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO user_sections (user_id, section_name, system_prompt, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, name, system_prompt, now),
        )
        await db.commit()
        return cursor.lastrowid


async def update_section(section_id: int, name: str = None, system_prompt: str = None) -> None:
    section = await get_section_by_id(section_id)
    if not section:
        return
    new_name = name if name is not None else section["section_name"]
    new_prompt = system_prompt if system_prompt is not None else section["system_prompt"]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_sections SET section_name = ?, system_prompt = ? WHERE id = ?",
            (new_name, new_prompt, section_id),
        )
        await db.commit()


async def delete_section(section_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_sections WHERE id = ?", (section_id,))
        await db.execute(
            "DELETE FROM chat_history WHERE section_id = ?", (str(section_id),)
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------


async def add_chat_message(user_id: int, section_id: str, role: str, content: str) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, section_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, section_id, role, content, now),
        )
        await db.commit()


async def get_section_history(user_id: int, section_id: str, limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM chat_history WHERE user_id = ? AND section_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, section_id, limit),
        )
        rows = await cursor.fetchall()
        return list(reversed(rows))


async def get_full_user_history(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM chat_history WHERE user_id = ? ORDER BY timestamp ASC",
            (user_id,),
        )
        return await cursor.fetchall()


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


async def create_order(user_id: int, order_type: str, details: str) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, order_type, details, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (user_id, order_type, details, now),
        )
        await db.commit()
        return cursor.lastrowid


async def attach_receipt(order_id: int, file_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET receipt_file_id = ? WHERE id = ?", (file_id, order_id)
        )
        await db.commit()


async def update_order_status(order_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        await db.commit()


async def get_order(order_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        return await cursor.fetchone()


async def get_latest_pending_order(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM orders WHERE user_id = ? AND status = 'pending' "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        return await cursor.fetchone()


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


async def get_statistics():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE is_prime = 1")
        total_prime = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
        total_blocked = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM chat_history")
        total_messages = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM api_keys WHERE is_active = 1")
        active_keys = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT SUM(usage_count) FROM api_keys")
        row = await cursor.fetchone()
        total_key_usage = row[0] if row and row[0] else 0

        today = datetime.utcnow().date().isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM chat_history WHERE timestamp LIKE ?", (f"{today}%",)
        )
        today_messages = (await cursor.fetchone())[0]

        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM chat_history WHERE timestamp >= ?", (week_ago,)
        )
        week_messages = (await cursor.fetchone())[0]

        month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM chat_history WHERE timestamp >= ?", (month_ago,)
        )
        month_messages = (await cursor.fetchone())[0]

    return {
        "total_users": total_users,
        "total_prime": total_prime,
        "total_blocked": total_blocked,
        "total_messages": total_messages,
        "active_keys": active_keys,
        "total_key_usage": total_key_usage,
        "today_messages": today_messages,
        "week_messages": week_messages,
        "month_messages": month_messages,
    }


# ============================================================================
# 4. GEMINI AI CALL ENGINE (MULTI-KEY ROUND-ROBIN FAILOVER)
# ============================================================================


class AIRequestError(Exception):
    pass


def _build_gemini_payload(system_prompt: str, history_rows, new_user_message: str) -> dict:
    contents = []
    for row in history_rows:
        role = "model" if row["role"] == "model" else "user"
        contents.append({"role": role, "parts": [{"text": row["content"]}]})
    contents.append({"role": "user", "parts": [{"text": new_user_message}]})
    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 2048,
        },
    }
    return payload


async def call_gemini_with_failover(
    system_prompt: str, history_rows, new_user_message: str
) -> str:
    keys = await get_active_api_keys()
    if not keys:
        raise AIRequestError(
            "Hozircha faol API kalit mavjud emas. Iltimos, keyinroq qayta urinib ko'ring."
        )

    payload = _build_gemini_payload(system_prompt, history_rows, new_user_message)
    last_error = None

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
        for key_row in keys:
            url = GEMINI_ENDPOINT_TEMPLATE.format(model=GEMINI_MODEL, key=key_row["key_string"])
            try:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        await mark_key_usage(key_row["id"])
                        try:
                            candidates = data.get("candidates", [])
                            if not candidates:
                                raise AIRequestError("AI bo'sh javob qaytardi.")
                            parts = candidates[0]["content"]["parts"]
                            text = "".join(p.get("text", "") for p in parts)
                            if not text.strip():
                                raise AIRequestError("AI bo'sh javob qaytardi.")
                            return text.strip()
                        except (KeyError, IndexError) as parse_err:
                            last_error = parse_err
                            continue
                    elif response.status == 429:
                        logger.warning(
                            "API kalit #%s uchun 429 RESOURCE_EXHAUSTED. Keyingi kalitga o'tilmoqda.",
                            key_row["id"],
                        )
                        await mark_key_error(key_row["id"], deactivate=False)
                        last_error = AIRequestError("429 RESOURCE_EXHAUSTED")
                        continue
                    else:
                        body_text = await response.text()
                        logger.warning(
                            "API kalit #%s xato qaytardi (status=%s): %s",
                            key_row["id"],
                            response.status,
                            body_text[:300],
                        )
                        await mark_key_error(key_row["id"], deactivate=False)
                        last_error = AIRequestError(f"HTTP {response.status}")
                        continue
            except (aiohttp.ClientError, asyncio.TimeoutError) as net_err:
                logger.warning("API kalit #%s bilan tarmoq xatosi: %s", key_row["id"], net_err)
                await mark_key_error(key_row["id"], deactivate=False)
                last_error = net_err
                continue

    raise AIRequestError(
        f"Barcha faol API kalitlar bilan urinish muvaffaqiyatsiz tugadi: {last_error}"
    )


# ============================================================================
# 5. FSM STATES
# ============================================================================


class SectionCreateStates(StatesGroup):
    waiting_name = State()
    waiting_purpose = State()


class SectionEditStates(StatesGroup):
    waiting_new_name = State()
    waiting_new_purpose = State()


class ChatModeStates(StatesGroup):
    in_section = State()


class WebsiteOrderStates(StatesGroup):
    waiting_site_type = State()
    waiting_requirements = State()
    waiting_budget = State()
    waiting_deadline = State()


class LogoOrderStates(StatesGroup):
    waiting_style = State()
    waiting_requirements = State()
    waiting_budget = State()
    waiting_deadline = State()


class PaymentStates(StatesGroup):
    waiting_receipt = State()


class FeedbackStates(StatesGroup):
    waiting_text = State()


class PrimeContactStates(StatesGroup):
    waiting_contact = State()


class AdminAuthStates(StatesGroup):
    waiting_password = State()


class AdminBroadcastStates(StatesGroup):
    waiting_content = State()
    waiting_confirm = State()


class AdminBridgeStates(StatesGroup):
    active = State()


class AdminAddChannelStates(StatesGroup):
    waiting_id = State()
    waiting_title = State()
    waiting_link = State()


class AdminAddApiKeyStates(StatesGroup):
    waiting_key = State()


class AdminEditTextStates(StatesGroup):
    waiting_key_choice = State()
    waiting_new_value = State()


class AdminPrimeStates(StatesGroup):
    waiting_user_id = State()
    waiting_months = State()


class AdminBlockStates(StatesGroup):
    waiting_user_id = State()


class AdminSettingsStates(StatesGroup):
    waiting_card = State()
    waiting_contact = State()


# ============================================================================
# 6. KEYBOARDS
# ============================================================================


def main_reply_menu() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="🧠 Bo'limlar"), KeyboardButton(text="➕ Yangi bo'lim qo'shish")],
        [KeyboardButton(text="🌐 Veb-sayt zakaz"), KeyboardButton(text="🎨 Logo/Dizayn zakaz")],
        [KeyboardButton(text="⭐ Prime olish"), KeyboardButton(text="📊 Mening rejimim")],
        [KeyboardButton(text="⚡ Tezkor maslahatlar"), KeyboardButton(text="💬 Kundalik motivatsiya")],
        [KeyboardButton(text="👤 MHDV haqida"), KeyboardButton(text="🤖 Bot haqida")],
        [KeyboardButton(text="📜 Qoidalar"), KeyboardButton(text="🌐 Ijtimoiy tarmoqlar")],
        [KeyboardButton(text="✍️ Admin bilan muloqot"), KeyboardButton(text="💡 Taklif va shikoyatlar")],
        [
            KeyboardButton(text="📊 Kunlik hisobot"),
            KeyboardButton(text="📊 Haftalik hisobot"),
            KeyboardButton(text="📊 Oylik hisobot"),
        ],
        [KeyboardButton(text="🚪 Chiqish")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Kontaktni yuborish", request_contact=True)],
            [KeyboardButton(text="🚪 Chiqish")],
        ],
        resize_keyboard=True,
    )


def exit_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚪 Chiqish")]],
        resize_keyboard=True,
    )


def cancel_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_fsm")]]
    )


def sections_list_keyboard(sections, user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for section in sections:
        rows.append(
            [InlineKeyboardButton(text=section["section_name"], callback_data=f"open_sec:{section['id']}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def section_actions_keyboard(section_id: int, owned_by_user: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="💬 Suhbatni boshlash", callback_data=f"chat_sec:{section_id}")]]
    if owned_by_user:
        rows.append(
            [
                InlineKeyboardButton(text="✏️ Bo'limni tahrirlash", callback_data=f"edit_sec:{section_id}"),
                InlineKeyboardButton(text="🗑️ Bo'limni o'chirish", callback_data=f"del_sec:{section_id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_sections")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_section_menu_keyboard(section_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Nomini yangilash", callback_data=f"edit_name:{section_id}")],
            [InlineKeyboardButton(text="🎯 Vazifasini yangilash", callback_data=f"edit_purpose:{section_id}")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"open_sec:{section_id}")],
        ]
    )


def confirm_delete_keyboard(section_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"confirm_del:{section_id}"),
                InlineKeyboardButton(text="❌ Yo'q", callback_data=f"open_sec:{section_id}"),
            ]
        ]
    )


def force_subscribe_keyboard(channels) -> InlineKeyboardMarkup:
    rows = []
    for channel in channels:
        rows.append([InlineKeyboardButton(text=f"📢 {channel['channel_title']}", url=channel["channel_link"])])
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_admin_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"pay_ok:{order_id}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"pay_no:{order_id}"),
            ]
        ]
    )


def admin_panel_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="👥 Foydalanuvchilar"), KeyboardButton(text="📊 Statistika")],
        [KeyboardButton(text="📢 Broadcast"), KeyboardButton(text="🔄 Force Update yuborish")],
        [KeyboardButton(text="📺 Kanallar boshqaruvi"), KeyboardButton(text="➕ Kanal qo'shish")],
        [KeyboardButton(text="✏️ Matnlarni tahrirlash"), KeyboardButton(text="🔑 API kalit qo'shish")],
        [KeyboardButton(text="💳 Karta raqamini o'zgartirish"), KeyboardButton(text="🔗 Admin shaxsiy chat linki")],
        [KeyboardButton(text="🧹 RAM keshni tozalash"), KeyboardButton(text="🔌 Botni yoqish/o'chirish")],
        [KeyboardButton(text="🚪 Chiqish")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def admin_users_pagination_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="< Orqaga", callback_data=f"adm_users:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Keyingi >", callback_data=f"adm_users:{page + 1}"))
    rows = []
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm_back_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_users_list_with_buttons(users_page, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    for user_row in users_page:
        label = f"{user_row['full_name']} ({user_row['id']})"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm_profile:{user_row['id']}:{page}")])
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="< Orqaga", callback_data=f"adm_users:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Keyingi >", callback_data=f"adm_users:{page + 1}"))
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm_back_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_profile_keyboard(target_id: int, is_blocked: bool, is_prime: bool, back_page: int) -> InlineKeyboardMarkup:
    block_btn = (
        InlineKeyboardButton(text="🔓 Blokdan chiqarish", callback_data=f"adm_unblock:{target_id}:{back_page}")
        if is_blocked
        else InlineKeyboardButton(text="🔒 Bloklash", callback_data=f"adm_block:{target_id}:{back_page}")
    )
    rows = [
        [InlineKeyboardButton(text="💬 Barcha yozishmalarni ko'rish", callback_data=f"adm_history:{target_id}:{back_page}")],
        [InlineKeyboardButton(text="✍️ Shaxsiy xabar yozish (Bridge)", callback_data=f"adm_bridge:{target_id}:{back_page}")],
        [block_btn],
        [InlineKeyboardButton(text="⭐ Prime berish", callback_data=f"adm_give_prime:{target_id}:{back_page}")],
    ]
    if is_prime:
        rows.append([InlineKeyboardButton(text="🚫 Prime'ni olib qo'yish", callback_data=f"adm_take_prime:{target_id}:{back_page}")])
    rows.append([InlineKeyboardButton(text="⬅️ Ro'yxatga qaytish", callback_data=f"adm_users:{back_page}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def prime_months_keyboard(target_id: int, back_page: int) -> InlineKeyboardMarkup:
    months_options = [1, 3, 6, 12]
    rows = [
        [InlineKeyboardButton(text=f"{m} oy", callback_data=f"adm_set_prime:{target_id}:{m}:{back_page}") for m in months_options]
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"adm_profile:{target_id}:{back_page}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_channels_keyboard(channels) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        rows.append(
            [InlineKeyboardButton(text=f"🗑️ {ch['channel_title']}", callback_data=f"adm_del_channel:{ch['id']}")]
        )
    rows.append([InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="adm_add_channel")])
    rows.append([InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm_back_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_texts_choice_keyboard() -> InlineKeyboardMarkup:
    keys = [
        ("mhdv_info", "👤 MHDV haqida"),
        ("about_bot", "🤖 Bot haqida"),
        ("rules", "📜 Qoidalar"),
        ("socials", "🌐 Ijtimoiy tarmoqlar"),
        ("quick_tips", "⚡ Tezkor maslahatlar"),
        ("daily_quote", "💬 Kundalik motivatsiya"),
    ]
    rows = [[InlineKeyboardButton(text=label, callback_data=f"adm_edit_key:{key}")] for key, label in keys]
    rows.append([InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm_back_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bridge_end_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🛑 Bridge'ni tugatish", callback_data="adm_bridge_stop")]]
    )


def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yuborish", callback_data="adm_broadcast_send"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm_broadcast_cancel"),
            ]
        ]
    )


# ============================================================================
# 7. HELPER FUNCTIONS
# ============================================================================


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def is_user_subscribed(user_id: int) -> bool:
    channels = await get_channels()
    if not channels:
        return True
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel["channel_id"], user_id=user_id)
            if member.status in (
                ChatMemberStatus.LEFT,
                ChatMemberStatus.KICKED,
            ):
                return False
        except (TelegramBadRequest, TelegramForbiddenError) as err:
            logger.warning("Obuna tekshiruvida xato (%s): %s", channel["channel_id"], err)
            return False
    return True


async def ensure_registered_and_active(message: Message) -> bool:
    user = message.from_user
    await create_user_if_not_exists(user.id, user.full_name or "Noma'lum", user.username or "")
    await reset_daily_if_needed(user.id)
    await expire_prime_if_needed(user.id)

    db_user = await get_user(user.id)
    if db_user and db_user["is_blocked"]:
        await message.answer("🚫 Siz botdan foydalanishdan bloklangansiz.")
        return False

    if not RUNTIME_CACHE["bot_enabled"] and not is_admin(user.id):
        await message.answer("🔧 Bot hozirda texnik ishlar tufayli vaqtincha o'chirilgan. Iltimos, keyinroq urinib ko'ring.")
        return False

    if not is_admin(user.id):
        subscribed = await is_user_subscribed(user.id)
        if not subscribed:
            channels = await get_channels()
            await message.answer(
                "📢 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling, so'ng "
                "\"✅ Tekshirish\" tugmasini bosing:",
                reply_markup=force_subscribe_keyboard(channels),
            )
            return False
    return True


def format_user_profile(db_user) -> str:
    prime_status = "❌ Yo'q"
    if db_user["is_prime"]:
        try:
            expires = datetime.fromisoformat(db_user["prime_expires_at"])
            prime_status = f"✅ Ha (tugash sanasi: {expires.strftime('%Y-%m-%d')})"
        except (ValueError, TypeError):
            prime_status = "✅ Ha"
    block_status = "🔒 Bloklangan" if db_user["is_blocked"] else "🔓 Bloklanmagan"
    text = (
        f"👤 <b>Foydalanuvchi profili</b>\n\n"
        f"🆔 ID: <code>{db_user['id']}</code>\n"
        f"📛 Ism: {db_user['full_name']}\n"
        f"🔗 Username: @{db_user['username'] if db_user['username'] else '—'}\n"
        f"⭐ Prime: {prime_status}\n"
        f"📊 Bugungi so'rovlar: {db_user['daily_requests']}\n"
        f"🚦 Holat: {block_status}\n"
        f"📅 Ro'yxatdan o'tgan: {db_user['created_at'][:10]}"
    )
    return text


async def build_chat_response(user_id: int, section, user_message: str) -> str:
    section_id_str = str(section["id"])
    history_rows = await get_section_history(user_id, section_id_str, limit=20)
    reply_text = await call_gemini_with_failover(
        system_prompt=section["system_prompt"],
        history_rows=history_rows,
        new_user_message=user_message,
    )
    await add_chat_message(user_id, section_id_str, "user", user_message)
    await add_chat_message(user_id, section_id_str, "model", reply_text)
    await increment_daily_requests(user_id)
    return reply_text


# ============================================================================
# 8. USER HANDLERS — START & FORCE SUBSCRIBE & EXIT
# ============================================================================


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    allowed = await ensure_registered_and_active(message)
    if not allowed:
        return
    await message.answer(
        "👋 Assalomu alaykum! MHDV AI botiga xush kelibsiz.\n\n"
        "Quyidagi menyudan kerakli bo'limni tanlang:",
        reply_markup=main_reply_menu(),
    )


@router.message(F.text == "🚪 Chiqish")
async def handle_global_exit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())


@router.callback_query(F.data == "check_subscription")
async def handle_check_subscription(callback: CallbackQuery) -> None:
    subscribed = await is_user_subscribed(callback.from_user.id)
    if subscribed:
        await callback.message.delete()
        await callback.message.answer(
            "✅ Obuna tasdiqlandi! Botdan foydalanishingiz mumkin.",
            reply_markup=main_reply_menu(),
        )
    else:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz.", show_alert=True)


@router.callback_query(F.data == "cancel_fsm")
async def handle_cancel_fsm(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Amal bekor qilindi.")
    await callback.answer()


# ============================================================================
# 9. USER HANDLERS — STATIC MENU ITEMS & PRIME FEATURE
# ============================================================================


@router.message(F.text == "👤 MHDV haqida")
async def handle_mhdv_info(message: Message) -> None:
    if not await ensure_registered_and_active(message):
        return
    text = await get_setting("mhdv_info")
    await message.answer(text)


@router.message(F.text == "🤖 Bot haqida")
async def handle_about_bot(message: Message) -> None:
    if not await ensure_registered_and_active(message):
        return
    text = await get_setting("about_bot")
    await message.answer(text)


@router.message(F.text == "📜 Qoidalar")
async def handle_rules(message: Message) -> None:
    if not await ensure_registered_and_active(message):
        return
    text = await get_setting("rules")
    await message.answer(text)


@router.message(F.text == "🌐 Ijtimoiy tarmoqlar")
async def handle_socials(message: Message) -> None:
    if not await ensure_registered_and_active(message):
        return
    text = await get_setting("socials")
    await message.answer(text)


@router.message(F.text == "⚡ Tezkor maslahatlar")
async def handle_quick_tips(message: Message) -> None:
    if not await ensure_registered_and_active(message):
        return
    text = await get_setting("quick_tips")
    await message.answer(text)


@router.message(F.text == "💬 Kundalik motivatsiya")
async def handle_daily_quote(message: Message) -> None:
    if not await ensure_registered_and_active(message):
        return
    text = await get_setting("daily_quote")
    await message.answer(text)


@router.message(F.text == "📊 Mening rejimim")
async def handle_my_profile(message: Message) -> None:
    if not await ensure_registered_and_active(message):
        return
    db_user = await get_user(message.from_user.id)
    if not db_user:
        await message.answer("Profil topilmadi.")
        return
    limit_text = "♾️ Cheksiz (Prime)" if db_user["is_prime"] else f"{db_user['daily_requests']}/{FREE_DAILY_LIMIT}"
    prime_label = "✅ Faol" if db_user["is_prime"] else "❌ Yo'q"
    text = (
        f"📊 <b>Mening rejimim</b>\n\n"
        f"🆔 ID: <code>{db_user['id']}</code>\n"
        f"⭐ Prime: {prime_label}\n"
        f"📈 Bugungi so'rovlar: {limit_text}\n"
        f"📅 Ro'yxatdan o'tgan sana: {db_user['created_at'][:10]}"
    )
    await message.answer(text)


@router.message(F.text == "⭐ Prime olish")
async def handle_prime_request_start(message: Message, state: FSMContext) -> None:
    if not await ensure_registered_and_active(message):
        return
    await state.set_state(PrimeContactStates.waiting_contact)
    await message.answer(
        "⭐ Prime tarifini rasmiylashtirish uchun kontaktingizni yuboring:",
        reply_markup=contact_keyboard(),
    )


@router.message(StateFilter(PrimeContactStates.waiting_contact), F.contact)
async def handle_prime_contact_received(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    contact = message.contact

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_contact(
                admin_id,
                phone_number=contact.phone_number,
                first_name=contact.first_name,
                last_name=contact.last_name or "",
            )
            await bot.send_message(
                admin_id,
                f"⭐ <b>Prime uchun zayavka!</b>\n\n"
                f"👤 {user.full_name} (<code>{user.id}</code>, @{user.username or '—'})\n"
                f"📱 Tel: {contact.phone_number}\n\n"
                f"<i>prime uchun</i>",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as err:
            logger.warning("Adminga contact yuborishda xato: %s", err)

    await message.answer(
        "✅ Kontaktingiz adminga yuborildi! Tez orada siz bilan bog'lanamiz.",
        reply_markup=main_reply_menu(),
    )


@router.message(F.text.in_({"📊 Kunlik hisobot", "📊 Haftalik hisobot", "📊 Oylik hisobot"}))
async def handle_reports(message: Message) -> None:
    if not await ensure_registered_and_active(message):
        return
    user_id = message.from_user.id
    if message.text == "📊 Kunlik hisobot":
        since = datetime.utcnow().date().isoformat()
        label = "Kunlik"
    elif message.text == "📊 Haftalik hisobot":
        since = (datetime.utcnow() - timedelta(days=7)).isoformat()
        label = "Haftalik"
    else:
        since = (datetime.utcnow() - timedelta(days=30)).isoformat()
        label = "Oylik"

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM chat_history WHERE user_id = ? AND timestamp >= ? AND role = 'user'",
            (user_id, since),
        )
        count = (await cursor.fetchone())[0]

    await message.answer(f"📊 <b>{label} hisobot</b>\n\nSiz yuborgan so'rovlar soni: {count} ta")


@router.message(F.text == "✍️ Admin bilan muloqot")
async def handle_admin_contact_prompt(message: Message, state: FSMContext) -> None:
    if not await ensure_registered_and_active(message):
        return
    await state.set_state(FeedbackStates.waiting_text)
    await message.answer(
        "✍️ Adminga yubormoqchi bo'lgan xabaringizni yozing yoki kontaktingizni ulashing:",
        reply_markup=contact_keyboard(),
    )


@router.message(F.text == "💡 Taklif va shikoyatlar")
async def handle_feedback_prompt(message: Message, state: FSMContext) -> None:
    if not await ensure_registered_and_active(message):
        return
    await state.set_state(FeedbackStates.waiting_text)
    await message.answer("💡 Taklif yoki shikoyatingizni yozing, adminga yuboriladi:", reply_markup=exit_keyboard())


@router.message(StateFilter(FeedbackStates.waiting_text), F.contact)
async def handle_feedback_contact(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    contact = message.contact

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_contact(
                admin_id,
                phone_number=contact.phone_number,
                first_name=contact.first_name,
                last_name=contact.last_name or "",
            )
            await bot.send_message(
                admin_id,
                f"📩 <b>Admin bilan muloqot (Kontakt yuborildi)</b>\n\n"
                f"👤 {user.full_name} (<code>{user.id}</code>, @{user.username or '—'})\n"
                f"📱 Tel: {contact.phone_number}",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as err:
            logger.warning("Adminga contact yuborishda xato: %s", err)

    await message.answer("✅ Kontaktingiz adminga yuborildi. Tez orada javob olasiz!", reply_markup=main_reply_menu())


@router.message(StateFilter(FeedbackStates.waiting_text), F.text)
async def handle_feedback_text(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return

    await state.clear()
    user = message.from_user
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📩 <b>Yangi xabar</b>\n\n👤 {user.full_name} (<code>{user.id}</code>, @{user.username or '—'})\n\n"
                f"💬 {message.text}",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as err:
            logger.warning("Adminga xabar yuborishda xato: %s", err)
    await message.answer("✅ Xabaringiz adminga yuborildi. Tez orada javob olasiz!", reply_markup=main_reply_menu())


# ============================================================================
# 10. USER HANDLERS — SECTIONS (LIST / CHAT / CREATE / EDIT / DELETE)
# ============================================================================


@router.message(F.text == "🧠 Bo'limlar")
async def handle_sections_list(message: Message, state: FSMContext) -> None:
    if not await ensure_registered_and_active(message):
        return
    await state.clear()
    sections = await get_visible_sections(message.from_user.id)
    if not sections:
        await message.answer("Hozircha hech qanday bo'lim mavjud emas.")
        return
    await message.answer(
        "🧠 Quyidagi bo'limlardan birini tanlang:",
        reply_markup=sections_list_keyboard(sections, message.from_user.id),
    )


@router.callback_query(F.data == "back_to_sections")
async def handle_back_to_sections(callback: CallbackQuery) -> None:
    sections = await get_visible_sections(callback.from_user.id)
    await callback.message.edit_text(
        "🧠 Quyidagi bo'limlardan birini tanlang:",
        reply_markup=sections_list_keyboard(sections, callback.from_user.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("open_sec:"))
async def handle_open_section(callback: CallbackQuery) -> None:
    section_id = int(callback.data.split(":")[1])
    section = await get_section_by_id(section_id)
    if not section:
        await callback.answer("Bo'lim topilmadi.", show_alert=True)
        return
    owned_by_user = section["user_id"] == callback.from_user.id
    await callback.message.edit_text(
        f"📂 <b>{section['section_name']}</b>\n\n🎯 Vazifasi:\n{section['system_prompt'][:500]}",
        reply_markup=section_actions_keyboard(section_id, owned_by_user),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("chat_sec:"))
async def handle_chat_section_start(callback: CallbackQuery, state: FSMContext) -> None:
    section_id = int(callback.data.split(":")[1])
    section = await get_section_by_id(section_id)
    if not section:
        await callback.answer("Bo'lim topilmadi.", show_alert=True)
        return
    await state.set_state(ChatModeStates.in_section)
    await state.update_data(section_id=section_id)
    await callback.message.answer(
        f"💬 <b>{section['section_name']}</b> bo'limi bilan suhbat boshlandi.\n"
        f"Chiqish uchun pastdagi menyudan \"🚪 Chiqish\" yoki boshqa tugmani bosing.",
        reply_markup=exit_keyboard(),
    )
    await callback.answer()


@router.message(StateFilter(ChatModeStates.in_section), F.text)
async def handle_chat_section_message(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Suhbat yakunlandi. Asosiy menyu:", reply_markup=main_reply_menu())
        return

    menu_texts = {
        "🧠 Bo'limlar", "➕ Yangi bo'lim qo'shish", "🌐 Veb-sayt zakaz", "🎨 Logo/Dizayn zakaz",
        "⭐ Prime olish", "📊 Mening rejimim", "⚡ Tezkor maslahatlar", "💬 Kundalik motivatsiya",
        "👤 MHDV haqida", "🤖 Bot haqida", "📜 Qoidalar", "🌐 Ijtimoiy tarmoqlar",
        "✍️ Admin bilan muloqot", "💡 Taklif va shikoyatlar", "📊 Kunlik hisobot",
        "📊 Haftalik hisobot", "📊 Oylik hisobot",
    }
    if message.text in menu_texts:
        await state.clear()
        await route_menu_text_after_state_clear(message, state)
        return

    if not await ensure_registered_and_active(message):
        return

    data = await state.get_data()
    section_id = data.get("section_id")
    section = await get_section_by_id(section_id)
    if not section:
        await state.clear()
        await message.answer("Bo'lim topilmadi. Menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return

    db_user = await get_user(message.from_user.id)
    if not db_user["is_prime"] and db_user["daily_requests"] >= FREE_DAILY_LIMIT:
        await message.answer(
            f"⚠️ Kunlik limitingiz ({FREE_DAILY_LIMIT} ta so'rov) tugadi. "
            f"Prime tarifga o'tib, cheksiz foydalanishingiz mumkin."
        )
        return

    thinking_msg = await message.answer("⏳ AI javob tayyorlamoqda...")
    try:
        reply_text = await build_chat_response(message.from_user.id, section, message.text)
        await thinking_msg.edit_text(reply_text)
    except AIRequestError as err:
        logger.error("AI so'rovida xato: %s", err)
        await thinking_msg.edit_text(
            "❌ Afsuski, hozirda AI xizmatidan javob olishning imkoni bo'lmadi. "
            "Iltimos, birozdan so'ng qayta urinib ko'ring."
        )
    except Exception as err:  # noqa: BLE001
        logger.exception("Kutilmagan xato: %s", err)
        await thinking_msg.edit_text("❌ Kutilmagan xatolik yuz berdi. Administratsiya xabardor qilindi.")


async def route_menu_text_after_state_clear(message: Message, state: FSMContext) -> None:
    text_to_handler = {
        "🧠 Bo'limlar": lambda: handle_sections_list(message, state),
        "➕ Yangi bo'lim qo'shish": lambda: handle_new_section_start(message, state),
        "🌐 Veb-sayt zakaz": lambda: handle_website_order_start(message, state),
        "🎨 Logo/Dizayn zakaz": lambda: handle_logo_order_start(message, state),
        "⭐ Prime olish": lambda: handle_prime_request_start(message, state),
        "📊 Mening rejimim": lambda: handle_my_profile(message),
        "⚡ Tezkor maslahatlar": lambda: handle_quick_tips(message),
        "💬 Kundalik motivatsiya": lambda: handle_daily_quote(message),
        "👤 MHDV haqida": lambda: handle_mhdv_info(message),
        "🤖 Bot haqida": lambda: handle_about_bot(message),
        "📜 Qoidalar": lambda: handle_rules(message),
        "🌐 Ijtimoiy tarmoqlar": lambda: handle_socials(message),
        "✍️ Admin bilan muloqot": lambda: handle_admin_contact_prompt(message, state),
        "💡 Taklif va shikoyatlar": lambda: handle_feedback_prompt(message, state),
        "📊 Kunlik hisobot": lambda: handle_reports(message),
        "📊 Haftalik hisobot": lambda: handle_reports(message),
        "📊 Oylik hisobot": lambda: handle_reports(message),
    }
    handler_coro_factory = text_to_handler.get(message.text)
    if handler_coro_factory:
        await handler_coro_factory()


@router.message(F.text == "➕ Yangi bo'lim qo'shish")
async def handle_new_section_start(message: Message, state: FSMContext) -> None:
    if not await ensure_registered_and_active(message):
        return
    await state.set_state(SectionCreateStates.waiting_name)
    await message.answer(
        "📝 Yangi bo'lim nomini kiriting (masalan: \"Kulinariya maslahatchisi\"):",
        reply_markup=exit_keyboard(),
    )


@router.message(StateFilter(SectionCreateStates.waiting_name), F.text)
async def handle_new_section_name(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    await state.update_data(section_name=message.text.strip())
    await state.set_state(SectionCreateStates.waiting_purpose)
    await message.answer(
        "🎯 Endi ushbu bo'limning vazifasi yoki maqsadini batafsil yozib bering "
        "(AI shu asosida maxsus ko'rsatma tayyorlaydi):",
        reply_markup=exit_keyboard(),
    )


@router.message(StateFilter(SectionCreateStates.waiting_purpose), F.text)
async def handle_new_section_purpose(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    data = await state.get_data()
    section_name = data.get("section_name", "Yangi bo'lim")
    purpose_text = message.text.strip()

    thinking_msg = await message.answer("⏳ AI ushbu bo'lim uchun maxsus system prompt tayyorlamoqda...")

    generation_instruction = (
        "Siz AI tizim prompt generatoridasiz. Foydalanuvchi quyida bo'lim nomi va uning vazifasini "
        "tasvirlab berdi. Shu asosida, ushbu bo'lim uchun professional, aniq va batafsil 'system prompt' "
        f"(ingliz yoki o'zbek tilida, mazmuniga qarab) tayyorlang. Faqat tayyor system promptning "
        f"o'zini qaytaring, boshqa hech qanday izoh yozmang.\n\n"
        f"Bo'lim nomi: {section_name}\nVazifasi: {purpose_text}"
    )

    try:
        generated_prompt = await call_gemini_with_failover(
            system_prompt="Siz professional prompt-muhandissiz.",
            history_rows=[],
            new_user_message=generation_instruction,
        )
    except AIRequestError as err:
        logger.error("System prompt generatsiyasida xato: %s", err)
        generated_prompt = (
            f"Siz '{section_name}' bo'yicha professional maslahatchisiz. Vazifangiz: {purpose_text}. "
            f"Foydalanuvchiga aniq, foydali va tushunarli javoblar bering."
        )

    section_id = await create_section(message.from_user.id, section_name, generated_prompt)
    await state.clear()
    await thinking_msg.edit_text(
        f"✅ \"{section_name}\" bo'limi muvaffaqiyatli yaratildi!\n\n"
        f"🎯 Yaratilgan system prompt:\n{generated_prompt[:500]}"
    )
    await message.answer("Menyuga qaytdingiz.", reply_markup=main_reply_menu())


@router.callback_query(F.data.startswith("edit_sec:"))
async def handle_edit_section_menu(callback: CallbackQuery) -> None:
    section_id = int(callback.data.split(":")[1])
    section = await get_section_by_id(section_id)
    if not section or section["user_id"] != callback.from_user.id:
        await callback.answer("Bu bo'limni tahrirlash huquqingiz yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        f"✏️ \"{section['section_name']}\" bo'limini tahrirlash:",
        reply_markup=edit_section_menu_keyboard(section_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_name:"))
async def handle_edit_name_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    section_id = int(callback.data.split(":")[1])
    await state.set_state(SectionEditStates.waiting_new_name)
    await state.update_data(section_id=section_id)
    await callback.message.answer("📝 Yangi nomni kiriting:", reply_markup=exit_keyboard())
    await callback.answer()


@router.message(StateFilter(SectionEditStates.waiting_new_name), F.text)
async def handle_edit_name_save(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    data = await state.get_data()
    section_id = data.get("section_id")
    await update_section(section_id, name=message.text.strip())
    await state.clear()
    await message.answer("✅ Bo'lim nomi yangilandi.", reply_markup=main_reply_menu())


@router.callback_query(F.data.startswith("edit_purpose:"))
async def handle_edit_purpose_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    section_id = int(callback.data.split(":")[1])
    await state.set_state(SectionEditStates.waiting_new_purpose)
    await state.update_data(section_id=section_id)
    await callback.message.answer(
        "🎯 Yangi vazifa/maqsad tavsifini kiriting (AI system promptni qayta generatsiya qiladi):",
        reply_markup=exit_keyboard(),
    )
    await callback.answer()


@router.message(StateFilter(SectionEditStates.waiting_new_purpose), F.text)
async def handle_edit_purpose_save(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    data = await state.get_data()
    section_id = data.get("section_id")
    section = await get_section_by_id(section_id)
    purpose_text = message.text.strip()

    thinking_msg = await message.answer("⏳ AI yangilangan system promptni tayyorlamoqda...")
    generation_instruction = (
        "Siz AI tizim prompt generatoridasiz. Quyida bo'lim nomi va uning yangilangan vazifasi berilgan. "
        "Shu asosida professional 'system prompt' tayyorlang. Faqat tayyor promptni qaytaring.\n\n"
        f"Bo'lim nomi: {section['section_name']}\nYangi vazifa: {purpose_text}"
    )
    try:
        generated_prompt = await call_gemini_with_failover(
            system_prompt="Siz professional prompt-muhandissiz.",
            history_rows=[],
            new_user_message=generation_instruction,
        )
    except AIRequestError:
        generated_prompt = f"Siz '{section['section_name']}' bo'yicha maslahatchisiz. Vazifangiz: {purpose_text}."

    await update_section(section_id, system_prompt=generated_prompt)
    await state.clear()
    await thinking_msg.edit_text("✅ Bo'lim vazifasi va system prompt yangilandi.")
    await message.answer("Menyuga qaytdingiz.", reply_markup=main_reply_menu())


@router.callback_query(F.data.startswith("del_sec:"))
async def handle_delete_section_confirm(callback: CallbackQuery) -> None:
    section_id = int(callback.data.split(":")[1])
    section = await get_section_by_id(section_id)
    if not section or section["user_id"] != callback.from_user.id:
        await callback.answer("Bu bo'limni o'chirish huquqingiz yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        f"🗑️ \"{section['section_name']}\" bo'limini rostdan ham o'chirmoqchimisiz?",
        reply_markup=confirm_delete_keyboard(section_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del:"))
async def handle_delete_section_execute(callback: CallbackQuery) -> None:
    section_id = int(callback.data.split(":")[1])
    section = await get_section_by_id(section_id)
    if not section or section["user_id"] != callback.from_user.id:
        await callback.answer("Bu bo'limni o'chirish huquqingiz yo'q.", show_alert=True)
        return
    await delete_section(section_id)
    sections = await get_visible_sections(callback.from_user.id)
    if sections:
        await callback.message.edit_text(
            "✅ Bo'lim o'chirildi.\n\n🧠 Qolgan bo'limlar:",
            reply_markup=sections_list_keyboard(sections, callback.from_user.id),
        )
    else:
        await callback.message.edit_text("✅ Bo'lim o'chirildi. Hozircha boshqa bo'limlar yo'q.")
    await callback.answer()


# ============================================================================
# 11. USER HANDLERS — COMMERCE (WEBSITE / LOGO ORDERS + PAYMENTS)
# ============================================================================


@router.message(F.text == "🌐 Veb-sayt zakaz")
async def handle_website_order_start(message: Message, state: FSMContext) -> None:
    if not await ensure_registered_and_active(message):
        return
    admin_card = await get_setting("admin_card", "4880 0000 0000 0000")
    admin_link = await get_setting("admin_contact_link", "https://t.me/admin")
    await state.set_state(WebsiteOrderStates.waiting_site_type)
    await message.answer(
        f"🌐 Veb-sayt buyurtmasi.\n\n"
        f"💳 Karta raqam: <code>{admin_card}</code>\n"
        f"📩 Admin bilan bog'lanish: {admin_link}\n\n"
        f"1️⃣ Qanday turdagi sayt kerak? "
        f"(masalan: landing page, onlayn do'kon, korporativ sayt va h.k.)",
        reply_markup=exit_keyboard(),
    )


@router.message(StateFilter(WebsiteOrderStates.waiting_site_type), F.text)
async def handle_website_site_type(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    await state.update_data(site_type=message.text.strip())
    await state.set_state(WebsiteOrderStates.waiting_requirements)
    await message.answer("2️⃣ Saytga qo'yiladigan asosiy talablarni yozing:", reply_markup=exit_keyboard())


@router.message(StateFilter(WebsiteOrderStates.waiting_requirements), F.text)
async def handle_website_requirements(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    await state.update_data(requirements=message.text.strip())
    await state.set_state(WebsiteOrderStates.waiting_budget)
    await message.answer("3️⃣ Loyiha uchun byudjetingiz qancha?", reply_markup=exit_keyboard())


@router.message(StateFilter(WebsiteOrderStates.waiting_budget), F.text)
async def handle_website_budget(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    await state.update_data(budget=message.text.strip())
    await state.set_state(WebsiteOrderStates.waiting_deadline)
    await message.answer("4️⃣ Qaysi muddatgacha tayyor bo'lishi kerak?", reply_markup=exit_keyboard())


@router.message(StateFilter(WebsiteOrderStates.waiting_deadline), F.text)
async def handle_website_deadline(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    data = await state.get_data()
    deadline = message.text.strip()
    await state.clear()

    tz_instruction = (
        "Siz professional biznes-analitiksiz. Quyidagi ma'lumotlar asosida mijoz uchun mukammal "
        "Texnik Topshiriq (TZ) tuzing. Aniq, tuzilgan va professional formatda yozing.\n\n"
        f"Sayt turi: {data.get('site_type')}\n"
        f"Talablar: {data.get('requirements')}\n"
        f"Byudjet: {data.get('budget')}\n"
        f"Muddat: {deadline}"
    )
    thinking_msg = await message.answer("⏳ AI Texnik Topshiriqni tayyorlamoqda...")
    try:
        tz_text = await call_gemini_with_failover(
            system_prompt="Siz professional Texnik Topshiriq (TZ) tuzuvchi analitiksiz.",
            history_rows=[],
            new_user_message=tz_instruction,
        )
    except AIRequestError:
        tz_text = (
            f"Sayt turi: {data.get('site_type')}\nTalablar: {data.get('requirements')}\n"
            f"Byudjet: {data.get('budget')}\nMuddat: {deadline}"
        )

    order_id = await create_order(message.from_user.id, "website", tz_text)
    await thinking_msg.edit_text(
        f"✅ Buyurtmangiz qabul qilindi (№{order_id})!\n\n📋 Texnik Topshiriq:\n{tz_text[:800]}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🌐 <b>Yangi veb-sayt buyurtmasi (№{order_id})</b>\n\n"
                f"👤 {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n\n"
                f"{tz_text[:1500]}",
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    await state.set_state(PaymentStates.waiting_receipt)
    await state.update_data(order_id=order_id)
    await message.answer(
        "💳 Buyurtmani tasdiqlash uchun to'lov chekining skrinshotini yuboring.",
        reply_markup=exit_keyboard(),
    )


@router.message(F.text == "🎨 Logo/Dizayn zakaz")
async def handle_logo_order_start(message: Message, state: FSMContext) -> None:
    if not await ensure_registered_and_active(message):
        return
    admin_card = await get_setting("admin_card", "4880 0000 0000 0000")
    admin_link = await get_setting("admin_contact_link", "https://t.me/admin")
    await state.set_state(LogoOrderStates.waiting_style)
    await message.answer(
        f"🎨 Logo/Dizayn buyurtmasi.\n\n"
        f"💳 Karta raqam: <code>{admin_card}</code>\n"
        f"📩 Admin bilan bog'lanish: {admin_link}\n\n"
        f"1️⃣ Qanday uslubda logo xohlaysiz? "
        f"(minimalist, zamonaviy, klassik va h.k.)",
        reply_markup=exit_keyboard(),
    )


@router.message(StateFilter(LogoOrderStates.waiting_style), F.text)
async def handle_logo_style(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    await state.update_data(style=message.text.strip())
    await state.set_state(LogoOrderStates.waiting_requirements)
    await message.answer("2️⃣ Brend/kompaniyangiz haqida va logo talablarini yozing:", reply_markup=exit_keyboard())


@router.message(StateFilter(LogoOrderStates.waiting_requirements), F.text)
async def handle_logo_requirements(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    await state.update_data(requirements=message.text.strip())
    await state.set_state(LogoOrderStates.waiting_budget)
    await message.answer("3️⃣ Byudjetingiz qancha?", reply_markup=exit_keyboard())


@router.message(StateFilter(LogoOrderStates.waiting_budget), F.text)
async def handle_logo_budget(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    await state.update_data(budget=message.text.strip())
    await state.set_state(LogoOrderStates.waiting_deadline)
    await message.answer("4️⃣ Qaysi muddatgacha tayyor bo'lishi kerak?", reply_markup=exit_keyboard())


@router.message(StateFilter(LogoOrderStates.waiting_deadline), F.text)
async def handle_logo_deadline(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return
    data = await state.get_data()
    deadline = message.text.strip()
    await state.clear()

    tz_instruction = (
        "Siz professional dizayn-brif tuzuvchisiz. Quyidagi ma'lumotlar asosida logo/dizayn loyihasi "
        "uchun mukammal Texnik Topshiriq (TZ) tuzing.\n\n"
        f"Uslub: {data.get('style')}\nTalablar: {data.get('requirements')}\n"
        f"Byudjet: {data.get('budget')}\nMuddat: {deadline}"
    )
    thinking_msg = await message.answer("⏳ AI Texnik Topshiriqni tayyorlamoqda...")
    try:
        tz_text = await call_gemini_with_failover(
            system_prompt="Siz professional Texnik Topshiriq (TZ) tuzuvchi dizayn-analitiksiz.",
            history_rows=[],
            new_user_message=tz_instruction,
        )
    except AIRequestError:
        tz_text = (
            f"Uslub: {data.get('style')}\nTalablar: {data.get('requirements')}\n"
            f"Byudjet: {data.get('budget')}\nMuddat: {deadline}"
        )

    order_id = await create_order(message.from_user.id, "logo", tz_text)
    await thinking_msg.edit_text(
        f"✅ Buyurtmangiz qabul qilindi (№{order_id})!\n\n📋 Texnik Topshiriq:\n{tz_text[:800]}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🎨 <b>Yangi logo/dizayn buyurtmasi (№{order_id})</b>\n\n"
                f"👤 {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n\n"
                f"{tz_text[:1500]}",
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    await state.set_state(PaymentStates.waiting_receipt)
    await state.update_data(order_id=order_id)
    await message.answer(
        "💳 Buyurtmani tasdiqlash uchun to'lov chekining skrinshotini yuboring.",
        reply_markup=exit_keyboard(),
    )


@router.message(StateFilter(PaymentStates.waiting_receipt), F.photo)
async def handle_payment_receipt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        order = await get_latest_pending_order(message.from_user.id)
        order_id = order["id"] if order else None
    if not order_id:
        await message.answer("❌ Faol buyurtma topilmadi.")
        await state.clear()
        return

    file_id = message.photo[-1].file_id
    await attach_receipt(order_id, file_id)
    await state.clear()
    await message.answer(
        "✅ To'lov cheki qabul qilindi va admin ko'rib chiqishi uchun yuborildi. "
        "Tasdiqlangach sizga xabar beriladi.",
        reply_markup=main_reply_menu(),
    )

    order = await get_order(order_id)
    caption = (
        f"💰 <b>YANGI TO'LOV KELDI! (Buyurtma №{order_id})</b>\n\n"
        f"👤 Foydalanuvchi: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
        f"📦 Turi: {order['order_type']}\n"
        f"⏱️ Vaqti: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"<i>To'lovni tasdiqlaysizmi?</i>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                photo=file_id,
                caption=caption,
                reply_markup=payment_admin_keyboard(order_id),
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass


@router.callback_query(F.data.startswith("pay_ok:"))
async def handle_payment_approve(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    order_id = int(callback.data.split(":")[1])
    order = await get_order(order_id)
    if not order:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return
    await update_order_status(order_id, "approved")
    await callback.message.edit_caption(
        caption=(callback.message.caption or "") + "\n\n✅ <b>TASDIQLANDI VA QABUL QILINDI</b>"
    )
    try:
        await bot.send_message(
            order["user_id"],
            f"✅ Buyurtmangiz (№{order_id}) to'lovi admin tomonidan tasdiqlandi va qabul qilindi! "
            f"Tez orada siz bilan bog'lanamiz.",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    await callback.answer("Tasdiqlandi va qabul qilindi.")


@router.callback_query(F.data.startswith("pay_no:"))
async def handle_payment_reject(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    order_id = int(callback.data.split(":")[1])
    order = await get_order(order_id)
    if not order:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return
    await update_order_status(order_id, "rejected")
    await callback.message.edit_caption(
        caption=(callback.message.caption or "") + "\n\n❌ <b>RAD ETILDI</b>"
    )
    try:
        await bot.send_message(
            order["user_id"],
            f"❌ Buyurtmangiz (№{order_id}) to'lovi rad etildi. Iltimos, admin bilan bog'laning.",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    await callback.answer("Rad etildi.")


# ============================================================================
# 12. ADMIN — AUTHENTICATION (/adminOpen)
# ============================================================================


@router.message(Command("adminopen"))
async def handle_admin_open(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminAuthStates.waiting_password)
    await message.answer("🔐 Admin panelga kirish uchun parolni kiriting:", reply_markup=exit_keyboard())


@router.message(StateFilter(AdminAuthStates.waiting_password), F.text)
async def handle_admin_password(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Asosiy menyuga qaytdingiz.", reply_markup=main_reply_menu())
        return

    correct_password = await get_setting("admin_password", ADMIN_PASSWORD)
    if message.text.strip() == correct_password:
        await state.clear()
        await message.answer("✅ Xush kelibsiz, Admin!", reply_markup=admin_panel_reply_keyboard())
    else:
        await message.answer("❌ Noto'g'ri parol. Qaytadan urinib ko'ring:")


# ============================================================================
# 13. ADMIN — MAIN PANEL NAVIGATION & NEW ADMIN FEATURES
# ============================================================================


@router.message(F.text == "🔄 Force Update yuborish", F.from_user.id.func(is_admin))
async def handle_admin_force_update(message: Message) -> None:
    user_ids = await get_all_active_user_ids()
    update_text = "🔄 <b>Botga yangilanish keldi!</b>\n\nIltimos, botga qayta /start bering."
    sent_count = 0

    status_msg = await message.answer(f"⏳ {len(user_ids)} ta foydalanuvchiga yangilanish habari yuborilmoqda...")

    for uid in user_ids:
        try:
            await bot.send_message(uid, update_text)
            sent_count += 1
            await asyncio.sleep(0.04)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    await status_msg.edit_text(f"✅ Force Update yakunlandi!\n\n📨 Muvaffaqiyatli yuborildi: {sent_count}/{len(user_ids)}")


@router.message(F.text == "💳 Karta raqamini o'zgartirish", F.from_user.id.func(is_admin))
async def handle_admin_change_card_prompt(message: Message, state: FSMContext) -> None:
    current_card = await get_setting("admin_card", "4880 0000 0000 0000")
    await state.set_state(AdminSettingsStates.waiting_card)
    await message.answer(
        f"💳 Hozirgi karta raqam: <code>{current_card}</code>\n\nYangi karta raqamini kiriting:",
        reply_markup=exit_keyboard(),
    )


@router.message(StateFilter(AdminSettingsStates.waiting_card), F.text)
async def handle_admin_change_card_save(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Admin panelga qaytdingiz.", reply_markup=admin_panel_reply_keyboard())
        return
    new_card = message.text.strip()
    await set_setting("admin_card", new_card)
    await state.clear()
    await message.answer(f"✅ Karta raqami yangilandi: <code>{new_card}</code>", reply_markup=admin_panel_reply_keyboard())


@router.message(F.text == "🔗 Admin shaxsiy chat linki", F.from_user.id.func(is_admin))
async def handle_admin_change_contact_prompt(message: Message, state: FSMContext) -> None:
    current_link = await get_setting("admin_contact_link", "https://t.me/admin")
    await state.set_state(AdminSettingsStates.waiting_contact)
    await message.answer(
        f"🔗 Hozirgi shaxsiy chat linki: {current_link}\n\nYangi Telegram profil linkini kiriting (masalan: https://t.me/username):",
        reply_markup=exit_keyboard(),
    )


@router.message(StateFilter(AdminSettingsStates.waiting_contact), F.text)
async def handle_admin_change_contact_save(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Admin panelga qaytdingiz.", reply_markup=admin_panel_reply_keyboard())
        return
    new_link = message.text.strip()
    await set_setting("admin_contact_link", new_link)
    await state.clear()
    await message.answer(f"✅ Admin shaxsiy chat linki yangilandi: {new_link}", reply_markup=admin_panel_reply_keyboard())


@router.message(F.text == "📢 Broadcast", F.from_user.id.func(is_admin))
async def handle_admin_broadcast_prompt(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminBroadcastStates.waiting_content)
    await message.answer("📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni kiriting:", reply_markup=exit_keyboard())


@router.message(StateFilter(AdminBroadcastStates.waiting_content), F.text)
async def handle_admin_broadcast_confirm(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Admin panelga qaytdingiz.", reply_markup=admin_panel_reply_keyboard())
        return
    await state.update_data(broadcast_text=message.text)
    await state.set_state(AdminBroadcastStates.waiting_confirm)
    await message.answer(
        f"📢 Quyidagi xabar barchaga yuborilsinmi?\n\n{message.text}",
        reply_markup=broadcast_confirm_keyboard(),
    )


@router.callback_query(F.data == "adm_broadcast_send")
async def handle_admin_broadcast_execute(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    data = await state.get_data()
    text = data.get("broadcast_text")
    await state.clear()

    user_ids = await get_all_active_user_ids()
    sent_count = 0
    await callback.message.edit_text(f"⏳ {len(user_ids)} ta foydalanuvchiga xabar yuborilmoqda...")

    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent_count += 1
            await asyncio.sleep(0.04)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    await callback.message.answer(f"✅ Broadcast yakunlandi! Muvaffaqiyatli yuborildi: {sent_count}/{len(user_ids)}", reply_markup=admin_panel_reply_keyboard())
    await callback.answer()


@router.callback_query(F.data == "adm_broadcast_cancel")
async def handle_admin_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Broadcast bekor qilindi.")
    await callback.answer()


@router.message(F.text == "➕ Kanal qo'shish", F.from_user.id.func(is_admin))
async def handle_admin_add_channel_prompt(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminAddChannelStates.waiting_id)
    await message.answer("📺 Kanal ID sini kiriting (masalan: -100123456789):", reply_markup=exit_keyboard())


@router.message(StateFilter(AdminAddChannelStates.waiting_id), F.text)
async def handle_admin_add_channel_id(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Admin panelga qaytdingiz.", reply_markup=admin_panel_reply_keyboard())
        return
    await state.update_data(channel_id=message.text.strip())
    await state.set_state(AdminAddChannelStates.waiting_title)
    await message.answer("📺 Kanal nomini kiriting:", reply_markup=exit_keyboard())


@router.message(StateFilter(AdminAddChannelStates.waiting_title), F.text)
async def handle_admin_add_channel_title(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Admin panelga qaytdingiz.", reply_markup=admin_panel_reply_keyboard())
        return
    await state.update_data(channel_title=message.text.strip())
    await state.set_state(AdminAddChannelStates.waiting_link)
    await message.answer("📺 Kanal havolasini (link) kiriting (masalan: https://t.me/mhdv_channel):", reply_markup=exit_keyboard())


@router.message(StateFilter(AdminAddChannelStates.waiting_link), F.text)
async def handle_admin_add_channel_link(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Admin panelga qaytdingiz.", reply_markup=admin_panel_reply_keyboard())
        return
    data = await state.get_data()
    await add_channel(data.get("channel_id"), data.get("channel_title"), message.text.strip())
    await state.clear()
    await message.answer("✅ Kanal majburiy obuna ro'yxatiga muvaffaqiyatli qo'shildi!", reply_markup=admin_panel_reply_keyboard())


@router.message(F.text == "📺 Kanallar boshqaruvi", F.from_user.id.func(is_admin))
async def handle_admin_channels_list_menu(message: Message) -> None:
    channels = await get_channels()
    await message.answer("📺 majburiy obuna kanallari:", reply_markup=admin_channels_keyboard(channels))


@router.callback_query(F.data.startswith("adm_del_channel:"))
async def handle_admin_del_channel(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    ch_id = int(callback.data.split(":")[1])
    await remove_channel(ch_id)
    channels = await get_channels()
    await callback.message.edit_text("📺 majburiy obuna kanallari:", reply_markup=admin_channels_keyboard(channels))
    await callback.answer("Kanal o'chirildi.")


@router.callback_query(F.data == "adm_add_channel")
async def handle_admin_add_channel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminAddChannelStates.waiting_id)
    await callback.message.answer("📺 Kanal ID sini kiriting (masalan: -100123456789):", reply_markup=exit_keyboard())
    await callback.answer()


@router.message(F.text == "🔑 API kalit qo'shish", F.from_user.id.func(is_admin))
async def handle_admin_add_key_prompt(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminAddApiKeyStates.waiting_key)
    await message.answer("🔑 Yangi Gemini API kalitini kiriting:", reply_markup=exit_keyboard())


@router.message(StateFilter(AdminAddApiKeyStates.waiting_key), F.text)
async def handle_admin_add_key_save(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Admin panelga qaytdingiz.", reply_markup=admin_panel_reply_keyboard())
        return
    success = await add_api_key(message.text.strip())
    await state.clear()
    if success:
        await message.answer("✅ API kalit muvaffaqiyatli qo'shildi!", reply_markup=admin_panel_reply_keyboard())
    else:
        await message.answer("⚠️ Bu API kalit allaqachon mavjud.", reply_markup=admin_panel_reply_keyboard())


@router.message(F.text == "✏️ Matnlarni tahrirlash", F.from_user.id.func(is_admin))
async def handle_admin_edit_texts_menu(message: Message) -> None:
    await message.answer("✏️ Qaysi bo'lim matnini tahrirlamoqchisiz?", reply_markup=edit_texts_choice_keyboard())


@router.callback_query(F.data.startswith("adm_edit_key:"))
async def handle_admin_edit_key_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.split(":")[1]
    current_val = await get_setting(key)
    await state.set_state(AdminEditTextStates.waiting_new_value)
    await state.update_data(edit_key=key)
    await callback.message.answer(
        f"📝 Hozirgi matn:\n\n{current_val}\n\nYangi matnni kiriting (HTML teglar qo'llanilishi mumkin):",
        reply_markup=exit_keyboard(),
    )
    await callback.answer()


@router.message(StateFilter(AdminEditTextStates.waiting_new_value), F.text)
async def handle_admin_edit_key_save(message: Message, state: FSMContext) -> None:
    if message.text == "🚪 Chiqish":
        await state.clear()
        await message.answer("🚪 Admin panelga qaytdingiz.", reply_markup=admin_panel_reply_keyboard())
        return
    data = await state.get_data()
    key = data.get("edit_key")
    await set_setting(key, message.text.strip())
    await state.clear()
    await message.answer("✅ Matn muvaffaqiyatli yangilandi!", reply_markup=admin_panel_reply_keyboard())


@router.message(F.text == "👥 Foydalanuvchilar", F.from_user.id.func(is_admin))
async def handle_admin_users_menu_button(message: Message) -> None:
    total = await count_users()
    total_pages = max(1, (total + 9) // 10)
    users_page = await get_users_page(0)
    text = f"👥 <b>Foydalanuvchilar</b> ({total} ta)\nSahifa: 1/{total_pages}"
    await message.answer(text, reply_markup=admin_users_list_with_buttons(users_page, 0, total_pages))


@router.message(F.text == "📊 Statistika", F.from_user.id.func(is_admin))
async def handle_admin_stats_button(message: Message) -> None:
    stats = await get_statistics()
    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {stats['total_users']}\n"
        f"⭐ Prime foydalanuvchilar: {stats['total_prime']}\n"
        f"🔒 Bloklanganlar: {stats['total_blocked']}\n"
        f"💬 Jami xabarlar (token o'rniga): {stats['total_messages']}\n"
        f"🔑 Faol API kalitlar: {stats['active_keys']}\n"
        f"📈 Kalitlar umumiy ishlatilishi: {stats['total_key_usage']}\n\n"
        f"📅 Bugungi xabarlar: {stats['today_messages']}\n"
        f"📅 Haftalik xabarlar: {stats['week_messages']}\n"
        f"📅 Oylik xabarlar: {stats['month_messages']}"
    )
    await message.answer(text)


@router.message(F.text == "🧹 RAM keshni tozalash", F.from_user.id.func(is_admin))
async def handle_admin_clear_cache_button(message: Message) -> None:
    RUNTIME_CACHE["bridge_targets"].clear()
    RUNTIME_CACHE["admin_awaiting_reply_from"].clear()
    await message.answer("🧹 RAM kesh tozalandi.")


@router.message(F.text == "🔌 Botni yoqish/o'chirish", F.from_user.id.func(is_admin))
async def handle_admin_toggle_bot_button(message: Message) -> None:
    RUNTIME_CACHE["bot_enabled"] = not RUNTIME_CACHE["bot_enabled"]
    new_status = "on" if RUNTIME_CACHE["bot_enabled"] else "off"
    await set_setting("bot_status", new_status)
    status_text = "🟢 YOQILDI" if RUNTIME_CACHE["bot_enabled"] else "🔴 O'CHIRILDI"
    await message.answer(f"Bot holati: {status_text}")


@router.callback_query(F.data == "adm_back_panel")
async def handle_admin_back_panel(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text("🔐 Admin panel:")
    await callback.message.answer("Menu:", reply_markup=admin_panel_reply_keyboard())
    await callback.answer()


@router.callback_query(F.data == "adm_stats")
async def handle_admin_stats(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    stats = await get_statistics()
    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {stats['total_users']}\n"
        f"⭐ Prime foydalanuvchilar: {stats['total_prime']}\n"
        f"🔒 Bloklanganlar: {stats['total_blocked']}\n"
        f"💬 Jami xabarlar (token o'rniga): {stats['total_messages']}\n"
        f"🔑 Faol API kalitlar: {stats['active_keys']}\n"
        f"📈 Kalitlar umumiy ishlatilishi: {stats['total_key_usage']}\n\n"
        f"📅 Bugungi xabarlar: {stats['today_messages']}\n"
        f"📅 Haftalik xabarlar: {stats['week_messages']}\n"
        f"📅 Oylik xabarlar: {stats['month_messages']}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm_back_panel")]]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "adm_clear_cache")
async def handle_admin_clear_cache(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    RUNTIME_CACHE["bridge_targets"].clear()
    RUNTIME_CACHE["admin_awaiting_reply_from"].clear()
    await callback.answer("🧹 RAM kesh tozalandi.", show_alert=True)


@router.callback_query(F.data == "adm_toggle_bot")
async def handle_admin_toggle_bot(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    RUNTIME_CACHE["bot_enabled"] = not RUNTIME_CACHE["bot_enabled"]
    new_status = "on" if RUNTIME_CACHE["bot_enabled"] else "off"
    await set_setting("bot_status", new_status)
    status_text = "🟢 YOQILDI" if RUNTIME_CACHE["bot_enabled"] else "🔴 O'CHIRILDI"
    await callback.answer(f"Bot holati: {status_text}", show_alert=True)


# ============================================================================
# 14. ADMIN — USERS LIST, PROFILE, BLOCK/UNBLOCK, PRIME
# ============================================================================


@router.callback_query(F.data.startswith("adm_users:"))
async def handle_admin_users_list(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    page = int(callback.data.split(":")[1])
    total = await count_users()
    total_pages = max(1, (total + 9) // 10)
    users_page = await get_users_page(page)
    text = f"👥 <b>Foydalanuvchilar</b> ({total} ta)\nSahifa: {page + 1}/{total_pages}"
    await callback.message.edit_text(
        text, reply_markup=admin_users_list_with_buttons(users_page, page, total_pages)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_profile:"))
async def handle_admin_user_profile(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, target_id_str, back_page_str = callback.data.split(":")
    target_id = int(target_id_str)
    back_page = int(back_page_str)
    db_user = await get_user(target_id)
    if not db_user:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    text = format_user_profile(db_user)
    await callback.message.edit_text(
        text,
        reply_markup=admin_profile_keyboard(
            target_id, bool(db_user["is_blocked"]), bool(db_user["is_prime"]), back_page
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_block:"))
async def handle_admin_block_user(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, target_id_str, back_page_str = callback.data.split(":")
    target_id = int(target_id_str)
    back_page = int(back_page_str)
    await set_block_status(target_id, True)
    db_user = await get_user(target_id)
    await callback.message.edit_text(
        format_user_profile(db_user),
        reply_markup=admin_profile_keyboard(target_id, True, bool(db_user["is_prime"]), back_page),
    )
    await callback.answer("Foydalanuvchi bloklandi.")


@router.callback_query(F.data.startswith("adm_unblock:"))
async def handle_admin_unblock_user(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, target_id_str, back_page_str = callback.data.split(":")
    target_id = int(target_id_str)
    back_page = int(back_page_str)
    await set_block_status(target_id, False)
    db_user = await get_user(target_id)
    await callback.message.edit_text(
        format_user_profile(db_user),
        reply_markup=admin_profile_keyboard(target_id, False, bool(db_user["is_prime"]), back_page),
    )
    await callback.answer("Foydalanuvchi blokdan chiqarildi.")


@router.callback_query(F.data.startswith("adm_give_prime:"))
async def handle_admin_give_prime_menu(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, target_id_str, back_page_str = callback.data.split(":")
    target_id = int(target_id_str)
    back_page = int(back_page_str)
    await callback.message.edit_text(
        "⭐ Necha oylik Prime bermoqchisiz?",
        reply_markup=prime_months_keyboard(target_id, back_page),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set_prime:"))
async def handle_admin_set_prime(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, target_id_str, months_str, back_page_str = callback.data.split(":")
    target_id = int(target_id_str)
    months = int(months_str)
    back_page = int(back_page_str)
    await grant_prime(target_id, months)
    db_user = await get_user(target_id)
    await callback.message.edit_text(
        format_user_profile(db_user),
        reply_markup=admin_profile_keyboard(target_id, bool(db_user["is_blocked"]), True, back_page),
    )
    try:
        await bot.send_message(target_id, f"🎉 Sizga {months} oylik Prime tarif berildi!")
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    await callback.answer("Prime berildi.")


@router.callback_query(F.data.startswith("adm_take_prime:"))
async def handle_admin_take_prime(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, target_id_str, back_page_str = callback.data.split(":")
    target_id = int(target_id_str)
    back_page = int(back_page_str)
    await revoke_prime(target_id)
    db_user = await get_user(target_id)
    await callback.message.edit_text(
        format_user_profile(db_user),
        reply_markup=admin_profile_keyboard(target_id, bool(db_user["is_blocked"]), False, back_page),
    )
    try:
        await bot.send_message(target_id, "ℹ️ Sizning Prime tarifingiz bekor qilindi.")
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    await callback.answer("Prime olib qo'yildi.")


@router.callback_query(F.data.startswith("adm_history:"))
async def handle_admin_view_history(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, target_id_str, back_page_str = callback.data.split(":")
    target_id = int(target_id_str)
    rows = await get_full_user_history(target_id)
    if not rows:
        await callback.answer("Yozishmalar topilmadi.", show_alert=True)
        return
    await callback.answer("Yozishmalar yuborilmoqda...")
    chunk = ""
    for row in rows:
        role_label = "👤 Foydalanuvchi" if row["role"] == "user" else "🤖 AI"
        line = f"[{row['timestamp'][:16]}] {role_label} (bo'lim: {row['section_id']}):\n{row['content']}\n\n"
        if len(chunk) + len(line) > 3500:
            await bot.send_message(callback.from_user.id, chunk)
            chunk = ""
        chunk += line
    if chunk:
        await bot.send_message(callback.from_user.id, chunk)


@router.callback_query(F.data.startswith("adm_bridge:"))
async def handle_admin_bridge_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, target_id_str, back_page_str = callback.data.split(":")
    target_id = int(target_id_str)
    RUNTIME_CACHE["bridge_targets"][callback.from_user.id] = target_id
    RUNTIME_CACHE["admin_awaiting_reply_from"][target_id] = callback.from_user.id
    await state.set_state(AdminBridgeStates.active)
    await callback.message.answer(
        f"✍️ Bridge rejimi yoqildi. Endi yozgan xabarlaringiz to'g'ridan-to'g'ri "
        f"foydalanuvchiga (<code>{target_id}</code>) yuboriladi.",
        reply_markup=bridge_end_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "adm_bridge_stop")
async def handle_admin_bridge_stop(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    target_id = RUNTIME_CACHE["bridge_targets"].pop(callback.from_user.id, None)
    if target_id:
        RUNTIME_CACHE["admin_awaiting_reply_from"].pop(target_id, None)
    await state.clear()
    await callback.message.edit_text("🛑 Bridge rejimi tugatildi.")
    await callback.answer()


@router.message(StateFilter(AdminBridgeStates.active), F.contact)
async def handle_admin_bridge_contact(message: Message) -> None:
    admin_id = message.from_user.id
    target_id = RUNTIME_CACHE["bridge_targets"].get(admin_id)
    if not target_id:
        await message.answer("Bridge rejimi faol emas.")
        return
    try:
        contact = message.contact
        await bot.send_contact(
            target_id,
            phone_number=contact.phone_number,
            first_name=contact.first_name,
            last_name=contact.last_name or "",
        )
        await message.answer("✅ Kontakt yuborildi.")
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.answer("❌ Foydalanuvchiga kontakt yuborib bo'lmadi.")


@router.message(StateFilter(AdminBridgeStates.active), F.text)
async def handle_admin_bridge_message(message: Message) -> None:
    admin_id = message.from_user.id
    target_id = RUNTIME_CACHE["bridge_targets"].get(admin_id)
    if not target_id:
        await message.answer("Bridge rejimi faol emas.")
        return
    try:
        await bot.send_message(target_id, f"✍️ <b>Admin:</b>\n\n{message.text}")
        await message.answer("✅ Yuborildi.")
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.answer("❌ Foydalanuvchiga xabar yuborib bo'lmadi.")


@router.message(F.text, F.from_user.id.func(lambda uid: uid in RUNTIME_CACHE["admin_awaiting_reply_from"]))
async def handle_user_reply_to_bridge(message: Message) -> None:
    admin_id = RUNTIME_CACHE["admin_awaiting_reply_from"].get(message.from_user.id)
    if not admin_id:
        return
    try:
        await bot.send_message(
            admin_id,
            f"👤 <b>{message.from_user.full_name}</b> (<code>{message.from_user.id}</code>) javobi:\n\n{message.text}",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


# ============================================================================
# 15. MAIN STARTUP & BOT ENTRYPOINT
# ============================================================================


async def main() -> None:
    logger.info("MHDV AI Bot ishga tushmoqda...")
    await init_db()
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")