import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")


def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


@contextmanager
def get_connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS exercises (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    exercise_name TEXT NOT NULL,
                    reps INTEGER NOT NULL DEFAULT 0,
                    sets INTEGER NOT NULL DEFAULT 0,
                    time INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )


def get_user(username: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, created_at FROM users WHERE username = %s",
                (username,),
            )
            return cur.fetchone()


def create_user(username: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username)
                VALUES (%s)
                RETURNING id, username, created_at
                """,
                (username,),
            )
            return cur.fetchone()


def get_or_create_user(username: str):
    user = get_user(username)
    if user is None:
        user = create_user(username)
    return user


def add_exercise(user_id, exercise_name, reps, sets, time):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM exercises
                WHERE user_id = %s
                  AND exercise_name = %s
                  AND created_at::date = CURRENT_DATE
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, exercise_name),
            )
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """
                    UPDATE exercises
                    SET reps = reps + %s,
                        sets = sets + %s,
                        time = time + %s
                    WHERE id = %s
                    """,
                    (reps, sets, time, existing["id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO exercises (user_id, exercise_name, reps, sets, time)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (user_id, exercise_name, reps, sets, time),
                )


def get_users_exercises(user_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, exercise_name, reps, sets, time, created_at
                FROM exercises
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            return cur.fetchall()