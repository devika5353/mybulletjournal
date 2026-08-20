from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="MeetMind API")

# Allow a browser-based frontend (running on any origin, e.g. a local file
# or a dev server on a different port) to call this API. In production
# you'd lock allow_origins down to your real frontend's address.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- DATA MODELS ----------
# These replace your old __init__ methods.
# Pydantic models double as "what shape of data do I expect in a request"
# AND "what shape of data do I return".

class Meeting:
    def __init__(self, id, title, date):
        self.id = id
        self.title = title
        self.date = date
        self.is_completed = False


class BacklogItem:
    def __init__(self, id, task, meeting_id, priority):
        self.id = id
        self.task = task
        self.meeting_id = meeting_id
        self.priority = priority
        self.is_resolved = False


# What the API expects the CLIENT (mobile app) to SEND when creating a meeting
class MeetingCreate(BaseModel):
    title: str
    date: str


class BacklogItemCreate(BaseModel):
    task: str
    meeting_id: int
    priority: int


# ---------- "DATABASE" (still just in-memory lists, for now) ----------
meetings = []
backlog = []
next_meeting_id = 1
next_backlog_id = 1


# ---------- HELPER ----------
def meeting_to_dict(m: Meeting):
    return {
        "id": m.id,
        "title": m.title,
        "date": m.date,
        "is_completed": m.is_completed,
    }


def backlog_to_dict(b: BacklogItem):
    return {
        "id": b.id,
        "task": b.task,
        "meeting_id": b.meeting_id,
        "priority": b.priority,
        "is_resolved": b.is_resolved,
    }


# ---------- MEETING ENDPOINTS ----------

@app.post("/meetings")
def add_meeting(payload: MeetingCreate):
    global next_meeting_id
    m = Meeting(next_meeting_id, payload.title, payload.date)
    meetings.append(m)
    next_meeting_id += 1
    return meeting_to_dict(m)


@app.get("/meetings")
def list_meetings():
    return [meeting_to_dict(m) for m in meetings]


@app.patch("/meetings/{meeting_id}/complete")
def mark_meeting_complete(meeting_id: int):
    for m in meetings:
        if m.id == meeting_id:
            m.is_completed = True
            return meeting_to_dict(m)
    raise HTTPException(status_code=404, detail="Meeting not found")


# ---------- BACKLOG ENDPOINTS ----------

@app.post("/backlog")
def add_backlog_item(payload: BacklogItemCreate):
    global next_backlog_id
    # make sure the meeting exists, same rule as your CLI had
    if not any(m.id == payload.meeting_id for m in meetings):
        raise HTTPException(status_code=400, detail="Meeting ID does not exist")

    b = BacklogItem(next_backlog_id, payload.task, payload.meeting_id, payload.priority)
    backlog.append(b)
    next_backlog_id += 1
    return backlog_to_dict(b)


@app.get("/backlog")
def list_backlog():
    return [backlog_to_dict(b) for b in backlog]


@app.patch("/backlog/{item_id}/resolve")
def mark_backlog_resolved(item_id: int):
    for b in backlog:
        if b.id == item_id:
            b.is_resolved = True
            return backlog_to_dict(b)
    raise HTTPException(status_code=404, detail="Backlog item not found")