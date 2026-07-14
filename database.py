from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

BJT = timezone(timedelta(hours=8))
def _now_bjt() -> str:
    """Return current Beijing time as ISO string without tz suffix."""
    return datetime.now(BJT).replace(tzinfo=None).isoformat()

DB_PATH = Path(__file__).parent / "data" / "members.db"


def _ensure_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                nickname TEXT DEFAULT '',
                points INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_login TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                points_cost INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                detail TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                title TEXT DEFAULT '',
                final_list TEXT DEFAULT '[]',
                all_reports TEXT DEFAULT '[]',
                market TEXT DEFAULT '{}',
                news_summary TEXT DEFAULT '',
                disclaimer TEXT DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user TEXT NOT NULL,
                action_type TEXT NOT NULL,
                target_user TEXT DEFAULT '',
                detail TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        _migrate_db(conn)
    finally:
        conn.close()


def _migrate_db(conn: sqlite3.Connection):
    """Add missing columns to existing tables."""
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "nickname" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN nickname TEXT DEFAULT ''")
            conn.commit()
    except Exception:
        pass


def get_conn() -> sqlite3.Connection:
    """Return SQLite connection with row_factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def log_admin_action(admin_user: str, action_type: str, target_user: str = "", detail: str = "") -> None:
    """Log an admin operation."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO admin_logs (admin_user, action_type, target_user, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (admin_user, action_type, target_user, detail, _now_bjt())
        )
        conn.commit()
    finally:
        conn.close()


def get_admin_logs(limit: int = 500) -> List[Dict[str, Any]]:
    """Get admin operation logs."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM admin_logs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def hash_password(password: str) -> str:
    """SHA256 hash a password."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def create_user(username: str, password: str, points: int = 0, is_admin: bool = False) -> Dict[str, Any]:
    """Create a new user and return user dict."""
    now = _now_bjt()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, points, is_admin, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?)",
            (username, hash_password(password), points, int(is_admin), now, None)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Verify credentials and update last_login. Return user dict or None."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            return None
        if row["password_hash"] != hash_password(password):
            return None
        now = _now_bjt()
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, row["id"]))
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Fetch user by ID."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_points(user_id: int) -> Optional[int]:
    """Fetch user's points balance."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT points FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["points"] if row else None
    finally:
        conn.close()


def deduct_points(user_id: int, amount: int, action_type: str, detail: str = "") -> bool:
    """Check balance, deduct points, and log usage. Return True on success."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT points FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or row["points"] < amount:
            return False
        conn.execute("UPDATE users SET points = points - ? WHERE id = ?", (amount, user_id))
        now = _now_bjt()
        conn.execute(
            "INSERT INTO usage_logs (user_id, action_type, points_cost, created_at, detail) VALUES (?, ?, ?, ?, ?)",
            (user_id, action_type, amount, now, detail)
        )
        conn.commit()
        return True
    finally:
        conn.close()


def add_points(user_id: int, amount: int) -> bool:
    """Add points to user balance. Return True on success."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE users SET points = points + ? WHERE id = ?", (amount, user_id))
        conn.commit()
        return True
    finally:
        conn.close()


def list_users() -> List[Dict[str, Any]]:
    """List all users."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_usage_logs(user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch usage logs with username."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT l.*, u.username
            FROM usage_logs l
            JOIN users u ON l.user_id = u.id
            WHERE l.user_id = ?
            ORDER BY l.created_at DESC
            LIMIT ?
            """,
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_user(user_id: int) -> bool:
    """Delete user and their usage logs. Return True on success."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM usage_logs WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def update_user_points(user_id: int, points: int) -> bool:
    """Set user points directly. Return True on success."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE users SET points = ? WHERE id = ?", (points, user_id))
        conn.commit()
        return True
    finally:
        conn.close()


def update_user_password(user_id: int, new_password: str) -> bool:
    """Update user password. Return True on success."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))
        conn.commit()
        return True
    finally:
        conn.close()


def init_admin(username: str = "admin", password: str = "admin123", points: int = 100) -> Dict[str, Any]:
    """Create default admin if not exists. Return admin user dict."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is not None:
            return dict(row)
        return create_user(username, password, points, is_admin=True)
    finally:
        conn.close()


def save_analysis(user_id: int, title: str, final_list: str, all_reports: str, market: str, news_summary: str, disclaimer: str) -> int:
    """Save analysis result to history. Return history id."""
    conn = get_conn()
    try:
        cursor = conn.execute(
            """INSERT INTO analysis_history (user_id, created_at, title, final_list, all_reports, market, news_summary, disclaimer)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, _now_bjt(), title, final_list, all_reports, market, news_summary, disclaimer)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_analysis_history(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Get user's analysis history list with points cost."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT a.id, a.created_at, a.title, a.disclaimer
               FROM analysis_history a
               WHERE a.user_id = ? ORDER BY a.created_at DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        result = []
        for row in rows:
            r = dict(row)
            analysis_time = r["created_at"]
            log_row = conn.execute(
                """SELECT points_cost FROM usage_logs
                   WHERE user_id = ? AND action_type = 'analysis'
                     AND created_at <= ?
                   ORDER BY created_at DESC LIMIT 1""",
                (user_id, analysis_time)
            ).fetchone()
            r["points_cost"] = log_row["points_cost"] if log_row else 0
            result.append(r)
        return result
    finally:
        conn.close()


def get_analysis_detail(history_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """Get full analysis detail by history id."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM analysis_history WHERE id = ? AND user_id = ?",
            (history_id, user_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_analysis(history_id: int, user_id: int) -> bool:
    """Delete an analysis history entry."""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM analysis_history WHERE id = ? AND user_id = ?", (history_id, user_id))
        conn.commit()
        return True
    finally:
        conn.close()


def get_user_usage_logs(user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """Get user's point usage logs."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT action_type, points_cost, created_at, detail FROM usage_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


_ensure_db()

