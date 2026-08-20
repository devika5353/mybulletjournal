from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
from dotenv import load_dotenv

load_dotenv()  # reads the .env file and makes DATABASE_URL available

app = FastAPI(title="MyBulletJournal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ["DATABASE_URL"]
STATUS_CYCLE = ["open", "done", "cancelled", "migrated", "note"]

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
def get_days():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT id, date, text, status, carried FROM tasks;")
        rows = cur.fetchall()
    release_connection(conn)
    return build_days(rows)


@app.post("/tasks")
def add_task(payload: TaskCreate):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO tasks (date, text, status, carried)
               VALUES (%s, %s, 'open', false)
               RETURNING id, date, text, status, carried;""",
            (payload.date, payload.text),
        )
        new_task = cur.fetchone()
    conn.commit()
    release_connection(conn)
    return new_task


@app.patch("/tasks/{task_id}/cycle")
def cycle_task(task_id: int):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM tasks WHERE id = %s;", (task_id,))
        row = cur.fetchone()
        if row is None:
            release_connection(conn)
            raise HTTPException(status_code=404, detail="Task not found")

        current_index = STATUS_CYCLE.index(row["status"])
        next_status = STATUS_CYCLE[(current_index + 1) % len(STATUS_CYCLE)]

        cur.execute(
            """UPDATE tasks SET status = %s WHERE id = %s
               RETURNING id, date, text, status, carried;""",
            (next_status, task_id),
        )
        updated = cur.fetchone()
    conn.commit()
    release_connection(conn)
    return updated


@app.patch("/tasks/{task_id}/mark-carried")
def mark_carried(task_id: int):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE tasks SET carried = true WHERE id = %s
               RETURNING id, date, text, status, carried;""",
            (task_id,),
        )
        updated = cur.fetchone()
    conn.commit()
    release_connection(conn)
    if updated is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return updated


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE id = %s RETURNING id;", (task_id,))
        deleted = cur.fetchone()
    conn.commit()
    release_connection(conn)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": task_id}