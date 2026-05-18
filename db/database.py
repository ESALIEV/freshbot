import asyncpg
import secrets
from datetime import datetime, timedelta, date
from config import DATABASE_URL

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS stores (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS store_members (
                user_id INTEGER NOT NULL REFERENCES users(id),
                store_id INTEGER NOT NULL REFERENCES stores(id),
                role TEXT NOT NULL CHECK(role IN ('admin', 'worker')),
                joined_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (user_id, store_id)
            );

            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                store_id INTEGER NOT NULL REFERENCES stores(id),
                name TEXT NOT NULL,
                category TEXT DEFAULT 'Общее',
                article TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS batches (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL DEFAULT 1,
                expiry_date DATE NOT NULL,
                added_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                batch_id INTEGER NOT NULL REFERENCES batches(id),
                notify_at TIMESTAMP NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('3d','1d','0d','expired')),
                sent INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS invite_codes (
                id SERIAL PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                store_id INTEGER NOT NULL REFERENCES stores(id),
                role TEXT NOT NULL DEFAULT 'worker',
                created_by INTEGER REFERENCES users(id),
                expires_at TIMESTAMP,
                used_count INTEGER NOT NULL DEFAULT 0,
                max_uses INTEGER NOT NULL DEFAULT 1
            );
        """)


async def get_or_create_user(telegram_id: int, username: str = None) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)
        if row:
            return dict(row)
        row = await db.fetchrow(
            "INSERT INTO users (telegram_id, username) VALUES ($1, $2) RETURNING *",
            telegram_id, username
        )
        return dict(row)


async def create_store(name: str, user_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        store = await db.fetchrow(
            "INSERT INTO stores (name, created_by) VALUES ($1, $2) RETURNING *",
            name, user_id
        )
        await db.execute(
            "INSERT INTO store_members (user_id, store_id, role) VALUES ($1, $2, 'admin')",
            user_id, store["id"]
        )
        return dict(store)


async def get_user_stores(user_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch("""
            SELECT s.*, sm.role FROM stores s
            JOIN store_members sm ON s.id = sm.store_id
            WHERE sm.user_id = $1
            ORDER BY s.created_at DESC
        """, user_id)
        return [dict(r) for r in rows]


async def get_member_role(user_id: int, store_id: int) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT role FROM store_members WHERE user_id = $1 AND store_id = $2",
            user_id, store_id
        )
        return row["role"] if row else None


async def get_store_members(store_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch("""
            SELECT u.telegram_id, u.username, sm.role
            FROM store_members sm
            JOIN users u ON u.id = sm.user_id
            WHERE sm.store_id = $1
        """, store_id)
        return [dict(r) for r in rows]


async def add_product_batch(store_id: int, name: str, quantity: int, expiry_date: str, article: str = "") -> int:
    pool = await get_pool()
    async with pool.acquire() as db:
        product = await db.fetchrow(
            "INSERT INTO products (store_id, name, article) VALUES ($1, $2, $3) RETURNING *",
            store_id, name, article
        )
        batch = await db.fetchrow(
            "INSERT INTO batches (product_id, quantity, expiry_date) VALUES ($1, $2, $3) RETURNING *",
            product["id"], quantity, expiry_date
        )
        return batch["id"]


async def get_store_products(store_id: int, search: str = "") -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        if search:
            rows = await db.fetch("""
                SELECT p.id as product_id, p.name, p.article,
                       b.id as batch_id, b.quantity, b.expiry_date,
                       (b.expiry_date - CURRENT_DATE)::int as days_left
                FROM products p
                JOIN batches b ON b.product_id = p.id
                WHERE p.store_id = $1
                AND (p.name ILIKE $2 OR p.article ILIKE $2)
                ORDER BY b.expiry_date ASC
            """, store_id, f"%{search}%")
        else:
            rows = await db.fetch("""
                SELECT p.id as product_id, p.name, p.article,
                       b.id as batch_id, b.quantity, b.expiry_date,
                       (b.expiry_date - CURRENT_DATE)::int as days_left
                FROM products p
                JOIN batches b ON b.product_id = p.id
                WHERE p.store_id = $1
                ORDER BY b.expiry_date ASC
            """, store_id)
        return [dict(r) for r in rows]


async def get_batch_by_id(batch_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow("""
            SELECT b.id as batch_id, b.quantity, b.expiry_date, b.product_id,
                   p.name as product_name, p.store_id
            FROM batches b
            JOIN products p ON p.id = b.product_id
            WHERE b.id = $1
        """, batch_id)
        return dict(row) if row else None


async def update_batch(batch_id: int, quantity: int, expiry_date: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE batches SET quantity = $1, expiry_date = $2 WHERE id = $3",
            quantity, expiry_date, batch_id
        )
        await db.execute(
            "DELETE FROM notifications WHERE batch_id = $1 AND sent = 0", batch_id
        )
    await create_notifications_for_batch(batch_id, expiry_date)


async def update_product_name(product_id: int, name: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("UPDATE products SET name = $1 WHERE id = $2", name, product_id)


async def delete_batch(batch_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM notifications WHERE batch_id = $1", batch_id)
        await db.execute("DELETE FROM batches WHERE id = $1", batch_id)
        await db.execute("""
            DELETE FROM products WHERE id NOT IN (SELECT DISTINCT product_id FROM batches)
        """)


async def create_notifications_for_batch(batch_id: int, expiry_date: str):
    expiry = datetime.strptime(str(expiry_date)[:10], "%Y-%m-%d")
    notify_schedule = [
        ("3d",      expiry - timedelta(days=3)),
        ("1d",      expiry - timedelta(days=1)),
        ("0d",      expiry),
        ("expired", expiry + timedelta(days=1)),
    ]
    pool = await get_pool()
    async with pool.acquire() as db:
        for ntype, notify_at in notify_schedule:
            if notify_at > datetime.now():
                await db.execute(
                    "INSERT INTO notifications (batch_id, notify_at, type) VALUES ($1, $2, $3)",
                    batch_id, notify_at, ntype
                )


async def get_pending_notifications() -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch("""
            SELECT n.id, n.type, n.batch_id,
                   b.quantity, b.expiry_date,
                   p.name as product_name,
                   s.id as store_id
            FROM notifications n
            JOIN batches b ON b.id = n.batch_id
            JOIN products p ON p.id = b.product_id
            JOIN stores s ON s.id = p.store_id
            WHERE n.sent = 0 AND n.notify_at <= NOW()
        """)
        return [dict(r) for r in rows]


async def mark_notification_sent(notif_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("UPDATE notifications SET sent = 1 WHERE id = $1", notif_id)


async def create_invite_code(store_id: int, created_by: int, role: str = "worker", max_uses: int = 1) -> str:
    code = secrets.token_urlsafe(8)
    expires_at = datetime.now() + timedelta(days=7)
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "INSERT INTO invite_codes (code, store_id, role, created_by, expires_at, max_uses) VALUES ($1,$2,$3,$4,$5,$6)",
            code, store_id, role, created_by, expires_at, max_uses
        )
    return code


async def use_invite_code(code: str, user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as db:
        invite = await db.fetchrow("""
            SELECT * FROM invite_codes
            WHERE code = $1 AND used_count < max_uses AND expires_at > NOW()
        """, code)
        if not invite:
            return None
        invite = dict(invite)
        try:
            await db.execute(
                "INSERT INTO store_members (user_id, store_id, role) VALUES ($1, $2, $3)",
                user_id, invite["store_id"], invite["role"]
            )
            await db.execute(
                "UPDATE invite_codes SET used_count = used_count + 1 WHERE id = $1",
                invite["id"]
            )
            return invite
        except Exception:
            return None


async def get_store_stats(store_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow("""
            SELECT
                COUNT(*)                                                              AS total,
                SUM(CASE WHEN b.expiry_date < CURRENT_DATE THEN 1 ELSE 0 END)        AS expired,
                SUM(CASE WHEN b.expiry_date >= CURRENT_DATE
                          AND (b.expiry_date - CURRENT_DATE) <= 3 THEN 1 ELSE 0 END) AS expires_3d,
                SUM(CASE WHEN DATE_TRUNC('month', b.expiry_date) = DATE_TRUNC('month', CURRENT_DATE)
                                                                      THEN 1 ELSE 0 END) AS expires_this_month,
                SUM(b.quantity)                                                       AS total_qty
            FROM products p
            JOIN batches b ON b.product_id = p.id
            WHERE p.store_id = $1
        """, store_id)
        return dict(row) if row else {}


async def get_store_products_filtered(store_id: int, status_filter: str = "") -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        base = """
            SELECT p.id as product_id, p.name, p.article,
                   b.id as batch_id, b.quantity, b.expiry_date,
                   (b.expiry_date - CURRENT_DATE)::int as days_left
            FROM products p
            JOIN batches b ON b.product_id = p.id
            WHERE p.store_id = $1
        """
        if status_filter == "expired":
            base += " AND b.expiry_date < CURRENT_DATE"
        elif status_filter == "warning":
            base += " AND b.expiry_date >= CURRENT_DATE AND (b.expiry_date - CURRENT_DATE) <= 3"
        elif status_filter == "month":
            base += " AND DATE_TRUNC('month', b.expiry_date) = DATE_TRUNC('month', CURRENT_DATE)"
        base += " ORDER BY b.expiry_date ASC"
        rows = await db.fetch(base, store_id)
        return [dict(r) for r in rows]
