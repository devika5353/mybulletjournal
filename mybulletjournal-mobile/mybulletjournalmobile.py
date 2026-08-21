from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import jwt
from dotenv import load_dotenv

load_dotenv()  # reads the .env file and makes DATABASE_URL available

app = FastAPI(title="MyBulletJournal Mobile API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ["DATABASE_URL"]
SUPABASE_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]
STATUS_CYCLE = ["open", "done", "cancelled", "migrated", "note"]


def get_current_user_id(authorization: str = Header(...)) -> str:
    """Every request must include an 'Authorization: Bearer <token>' header.
    We verify the token was really signed by Supabase, then pull out the
    user's id (the 'sub' claim) so we know whose tasks to show."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.replace("Bearer ", "")

    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload["sub"]  # this is the user's unique id


# A connection pool keeps a handful of connections open and ready to reuse,
# instead of paying the cost of a fresh handshake to Tokyo on every request.
# min 1, max 5 connections is plenty for a personal app.
connection_pool = psycopg2.pool.SimpleConnectionPool(
    1, 5, DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor
)


def get_connection():
    return connection_pool.getconn()


def release_connection(conn):
    connection_pool.putconn(conn)


class TaskCreate(BaseModel):
    date: str  # "YYYY-MM-DD"
    text: str


def build_days(all_tasks):
    """Group the flat task list (from the DB) into day objects, each with a
    computed 'complete' flag: true only if the day has at least one task AND
    none of them are still 'open'."""
    by_date = {}
    for t in all_tasks:
        by_date.setdefault(t["date"], []).append(dict(t))

    days = []
    for date, day_tasks in by_date.items():
        complete = len(day_tasks) > 0 and all(t["status"] != "open" for t in day_tasks)
        days.append({
            "date": date,
            "complete": complete,
            "tasks": sorted(day_tasks, key=lambda t: t["id"]),
        })

    return sorted(days, key=lambda d: d["date"], reverse=True)


@app.get("/days")
def get_days(user_id: str = Header(default=None), authorization: str = Header(default=None)):
    current_user_id = get_current_user_id(authorization)

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, date, text, status, carried FROM tasks WHERE user_id = %s;",
            (current_user_id,),
        )
        rows = cur.fetchall()
    release_connection(conn)
    return build_days(rows)


@app.post("/tasks")
def add_task(payload: TaskCreate, authorization: str = Header(default=None)):
    current_user_id = get_current_user_id(authorization)

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO tasks (date, text, status, carried, user_id)
               VALUES (%s, %s, 'open', false, %s)
               RETURNING id, date, text, status, carried;""",
            (payload.date, payload.text, current_user_id),
        )
        new_task = cur.fetchone()
    conn.commit()
    release_connection(conn)
    return new_task


@app.patch("/tasks/{task_id}/cycle")
def cycle_task(task_id: int, authorization: str = Header(default=None)):
    current_user_id = get_current_user_id(authorization)

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM tasks WHERE id = %s AND user_id = %s;",
            (task_id, current_user_id),
        )
        row = cur.fetchone()
        if row is None:
            release_connection(conn)
            raise HTTPException(status_code=404, detail="Task not found")

        current_index = STATUS_CYCLE.index(row["status"])
        next_status = STATUS_CYCLE[(current_index + 1) % len(STATUS_CYCLE)]

        cur.execute(
            """UPDATE tasks SET status = %s WHERE id = %s AND user_id = %s
               RETURNING id, date, text, status, carried;""",
            (next_status, task_id, current_user_id),
        )
        updated = cur.fetchone()
    conn.commit()
    release_connection(conn)
    return updated


@app.patch("/tasks/{task_id}/mark-carried")
def mark_carried(task_id: int, authorization: str = Header(default=None)):
    current_user_id = get_current_user_id(authorization)

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE tasks SET carried = true WHERE id = %s AND user_id = %s
               RETURNING id, date, text, status, carried;""",
            (task_id, current_user_id),
        )
        updated = cur.fetchone()
    conn.commit()
    release_connection(conn)
    if updated is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return updated


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, authorization: str = Header(default=None)):
    current_user_id = get_current_user_id(authorization)

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM tasks WHERE id = %s AND user_id = %s RETURNING id;",
            (task_id, current_user_id),
        )
        deleted = cur.fetchone()
    conn.commit()
    release_connection(conn)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": task_id}