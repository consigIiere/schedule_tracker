import asyncpg
from datetime import date
import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "schedule_db"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432))
}

pool: asyncpg.Pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(**DB_CONFIG)
    
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                title VARCHAR(255) NOT NULL,
                rule VARCHAR(20) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                task_date DATE NOT NULL,
                title VARCHAR(255) NOT NULL,
                is_done BOOLEAN DEFAULT FALSE,
                CONSTRAINT unique_user_task_day UNIQUE (user_id, task_date, title)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_user_date ON task_logs(user_id, task_date);
        """)

async def ensure_day_tasks(user_id: int, target_date: date, day_rule: str):
    async with pool.acquire() as conn:
        templates = await conn.fetch(
            "SELECT title FROM templates WHERE user_id = $1 AND (rule = 'daily' OR rule = $2)",
            user_id, day_rule
        )
        for tpl in templates:
            await conn.execute("""
                INSERT INTO task_logs (user_id, task_date, title, is_done)
                VALUES ($1, $2, $3, FALSE)
                ON CONFLICT (user_id, task_date, title) DO NOTHING
            """, user_id, target_date, tpl["title"])

async def get_day_tasks_with_type(user_id: int, target_date: date):
    async with pool.acquire() as conn:
        return await conn.fetch("""
            SELECT l.id, l.title, l.is_done, t.rule, t.id AS template_id
            FROM task_logs l
            LEFT JOIN templates t ON l.user_id = t.user_id AND l.title = t.title
            WHERE l.user_id = $1 AND l.task_date = $2
            ORDER BY l.id
        """, user_id, target_date)

async def toggle_task(task_id: int, user_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE task_logs SET is_done = NOT is_done WHERE id = $1 AND user_id = $2",
            task_id, user_id
        )

async def delete_task_completely(task_id: int, user_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT title FROM task_logs WHERE id = $1 AND user_id = $2",
            task_id, user_id
        )
        if row:
            title = row["title"]
            await conn.execute("DELETE FROM templates WHERE user_id = $1 AND title = $2", user_id, title)
            await conn.execute("DELETE FROM task_logs WHERE user_id = $1 AND title = $2", user_id, title)

async def add_single_task(user_id: int, target_date: date, title: str):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO task_logs (user_id, task_date, title, is_done)
            VALUES ($1, $2, $3, FALSE)
            ON CONFLICT (user_id, task_date, title) DO NOTHING
        """, user_id, target_date, title)

async def add_template(user_id: int, title: str, rule: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO templates (user_id, title, rule) VALUES ($1, $2, $3)",
            user_id, title, rule
        )

async def get_daily_templates(user_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, title FROM templates WHERE user_id = $1 AND rule = 'daily' ORDER BY id",
            user_id
        )

async def get_workout_day_templates(user_id: int, rule: str):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, title FROM templates WHERE user_id = $1 AND rule = $2 ORDER BY id",
            user_id, rule
        )

async def clear_workout_day_templates(user_id: int, rule: str):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT title FROM templates WHERE user_id = $1 AND rule = $2", user_id, rule)
        titles = [r["title"] for r in rows]
        
        await conn.execute("DELETE FROM templates WHERE user_id = $1 AND rule = $2", user_id, rule)
        if titles:
            await conn.execute(
                "DELETE FROM task_logs WHERE user_id = $1 AND title = ANY($2::text[])",
                user_id, titles
            )