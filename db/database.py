import aiosqlite
from datetime import datetime
from config import DATABASE_URL

DB = DATABASE_URL


async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.executescript("""
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS store_members (
                user_id INTEGER NOT NULL REFERENCES users(id),
                store_id INTEGER NOT NULL REFERENCES stores(id),
                role TEXT NOT NULL CHECK(role IN ('admin', 'worker')),
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, store_id)
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL REFERENCES stores(id),
                name TEXT NOT NULL,
                category TEXT DEFAULT 'Общее',
                article TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL DEFAULT 1,
                expiry_date DATE NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL REFERENCES batches(id),
                notify_at TIMESTAMP NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('3d','1d','0d','expired')),
                sent INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS invite_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                store_id INTEGER NOT NULL REFERENCES stores(id),
                role TEXT NOT NULL DEFAULT 'worker',
                created_by INTEGER REFERENCES users(id),
                expires_at TIMESTAMP,
                used INTEGER NOT NULL DEFAULT 0
            );
        """)
        try:
            await db.execute("ALTER TABLE products ADD COLUMN article TEXT DEFAULT ''")
        except Exception:
            pass  # колонка уже есть
        await db.commit()


async def get_or_create_user(telegram_id: int, username: str = None) -> dict:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            user = await cur.fetchone()
        if user:
            return dict(user)
        await db.execute(
            "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
            (telegram_id, username)
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            return dict(await cur.fetchone())


async def create_store(name: str, user_id: int) -> dict:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "INSERT INTO stores (name, created_by) VALUES (?, ?)", (name, user_id)
        )
        store_id = cur.lastrowid
        await db.execute(
            "INSERT INTO store_members (user_id, store_id, role) VALUES (?, ?, 'admin')",
            (user_id, store_id)
        )
        await db.commit()
        async with db.execute("SELECT * FROM stores WHERE id = ?", (store_id,)) as c:
            return dict(await c.fetchone())


async def get_user_stores(user_id: int) -> list:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT s.*, sm.role FROM stores s
            JOIN store_members sm ON s.id = sm.store_id
            WHERE sm.user_id = ?
            ORDER BY s.created_at DESC
        """, (user_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_member_role(user_id: int, store_id: int) -> str | None:
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT role FROM store_members WHERE user_id = ? AND store_id = ?",
            (user_id, store_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_store_members(store_id: int) -> list:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT u.telegram_id, u.username, sm.role
            FROM store_members sm
            JOIN users u ON u.id = sm.user_id
            WHERE sm.store_id = ?
        """, (store_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def add_product_batch(store_id: int, name: str, quantity: int, expiry_date: str, article: str = "") -> int:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "INSERT INTO products (store_id, name, article) VALUES (?, ?, ?)", (store_id, name, article)
        )
        product_id = cur.lastrowid
        cur2 = await db.execute(
            "INSERT INTO batches (product_id, quantity, expiry_date) VALUES (?, ?, ?)",
            (product_id, quantity, expiry_date)
        )
        batch_id = cur2.lastrowid
        await db.commit()
        return batch_id


async def get_store_products(store_id: int, search: str = "") -> list:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT p.id as product_id, p.name, p.article, b.id as batch_id, b.quantity, b.expiry_date,
                   CAST(julianday(b.expiry_date) - julianday('now') AS INTEGER) as days_left
            FROM products p
            JOIN batches b ON b.product_id = p.id
            WHERE p.store_id = ?
        """
        params = [store_id]
        if search:
            query += " AND (p.name LIKE ? OR p.article LIKE ?)"
            params += [f"%{search}%", f"%{search}%"]
        query += " ORDER BY b.expiry_date ASC"
        async with db.execute(query, params) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def create_notifications_for_batch(batch_id: int, expiry_date: str):
    from datetime import datetime, timedelta
    expiry = datetime.strptime(expiry_date, "%Y-%m-%d")
    notify_schedule = [
        ("3d", expiry - timedelta(days=3)),
        ("1d", expiry - timedelta(days=1)),
        ("0d", expiry),
        ("expired", expiry + timedelta(days=1)),
    ]
    async with aiosqlite.connect(DB) as db:
        for ntype, notify_at in notify_schedule:
            if notify_at > datetime.now():
                await db.execute(
                    "INSERT INTO notifications (batch_id, notify_at, type) VALUES (?, ?, ?)",
                    (batch_id, notify_at.strftime("%Y-%m-%d %H:%M:%S"), ntype)
                )
        await db.commit()


async def get_pending_notifications() -> list:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT n.id, n.type, n.batch_id,
                   b.quantity, b.expiry_date,
                   p.name as product_name,
                   s.id as store_id
            FROM notifications n
            JOIN batches b ON b.id = n.batch_id
            JOIN products p ON p.id = b.product_id
            JOIN stores s ON s.id = p.store_id
            WHERE n.sent = 0 AND n.notify_at <= datetime('now')
        """) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def mark_notification_sent(notif_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE notifications SET sent = 1 WHERE id = ?", (notif_id,))
        await db.commit()


async def create_invite_code(store_id: int, created_by: int, role: str = "worker") -> str:
    import secrets
    from datetime import datetime, timedelta
    code = secrets.token_urlsafe(8)
    expires_at = datetime.now() + timedelta(days=7)
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO invite_codes (code, store_id, role, created_by, expires_at) VALUES (?, ?, ?, ?, ?)",
            (code, store_id, role, created_by, expires_at.strftime("%Y-%m-%d %H:%M:%S"))
        )
        await db.commit()
    return code


async def use_invite_code(code: str, user_id: int) -> dict | None:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM invite_codes
            WHERE code = ? AND used = 0 AND expires_at > datetime('now')
        """, (code,)) as cur:
            invite = await cur.fetchone()
        if not invite:
            return None
        invite = dict(invite)
        try:
            await db.execute(
                "INSERT INTO store_members (user_id, store_id, role) VALUES (?, ?, ?)",
                (user_id, invite["store_id"], invite["role"])
            )
            await db.execute("UPDATE invite_codes SET used = 1 WHERE id = ?", (invite["id"],))
            await db.commit()
            return invite
        except Exception:
            return None
async def update_batch(batch_id: int, quantity: int, expiry_date: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE batches SET quantity = ?, expiry_date = ? WHERE id = ?",
            (quantity, expiry_date, batch_id)
        )
        await db.commit()


async def update_product_name(product_id: int, name: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE products SET name = ? WHERE id = ?",
            (name, product_id)
        )
        await db.commit()


async def delete_batch(batch_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM notifications WHERE batch_id = ?", (batch_id,))
        await db.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
        await db.commit()


async def get_batch_by_id(batch_id: int) -> dict | None:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT b.id as batch_id, b.quantity, b.expiry_date, b.product_id,
                   p.name as product_name
            FROM batches b
            JOIN products p ON p.id = b.product_id
            WHERE b.id = ?
        """, (batch_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
