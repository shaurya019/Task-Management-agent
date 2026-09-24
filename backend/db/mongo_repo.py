"""MongoDB implementation – same interface, different guarantees.

How each fundamental maps from SQLite → MongoDB
───────────────────────────────────────────────
• Optimistic lock : find_one_and_update({_id, version}, {$set, $inc:{version:1}})
                    → ONE atomic operation on ONE document, no transaction needed.
• Idempotency     : deterministic _id = uuid5(owner + Idempotency-Key).  A retry produces the
                    same _id → the unique index on _id rejects the second insert
                    (DuplicateKeyError) → we return the existing doc.  No extra collection.
• Transactions    : multi-document (task + audit) atomicity needs a REPLICA SET.
                    MONGO_USE_TRANSACTIONS=true  → session.with_transaction(...)
                    false                        → best-effort, sequential writes
• Quota check     : count-then-insert is NOT atomic here (documented trade-off; use a
                    counter document inside a transaction if you need it strict).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..errors import IdempotencyKeyReused, QuotaExceeded, TaskNotFound, VersionConflict
from ..schemas import TaskCreate, TaskRecord, TaskReplace
from .base import PRIORITY_RANK, TaskQuery, TaskRepository, request_hash

_NS = uuid.UUID("6f1d3b7e-2c1a-4e8e-9d55-0b7f2f4c9a11")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _derived(fields: dict) -> dict:
    """Helper fields so Mongo can sort like SQL does (priority order, NULL due dates last)."""
    out = {}
    if "priority" in fields:
        out["priority_rank"] = PRIORITY_RANK[fields["priority"]]
    if "due_date" in fields:
        out["due_null"] = 0 if fields["due_date"] else 1
    return out


class MongoTaskRepository(TaskRepository):
    def __init__(self, uri: str = "mongodb://localhost:27017", db_name: str = "task_agent",
                 use_transactions: bool = True, max_tasks_per_user: int = 200,
                 client: MongoClient | None = None):
        self.client = client or MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)
        self.db = self.client[db_name]
        self.tasks = self.db["tasks"]
        self.events_col = self.db["task_events"]
        self.use_tx = use_transactions
        self.max_tasks = max_tasks_per_user

    def init(self) -> None:
        self.tasks.create_index([("owner_id", ASCENDING), ("status", ASCENDING)])
        self.tasks.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
        self.events_col.create_index([("task_id", ASCENDING)])

    # ── helpers ────────────────────────────────────────────────────────
    def _run(self, fn):
        """Run fn(session) atomically if transactions are enabled."""
        if self.use_tx:
            with self.client.start_session() as s:
                return s.with_transaction(lambda sess: fn(sess))   # auto-retries transient errors
        return fn(None)

    @staticmethod
    def _to_record(doc: dict) -> TaskRecord:
        d = dict(doc)
        d["id"] = d.pop("_id")
        return TaskRecord.model_validate(d)          # unknown helper fields (priority_rank…) are ignored

    def _audit(self, task_id, actor, action, detail=None, session=None):
        self.events_col.insert_one({"task_id": task_id, "actor_id": actor, "action": action,
                                    "at": _now(), "detail": detail or {}}, session=session)

    # ── CREATE ─────────────────────────────────────────────────────────
    def create(self, owner_id, data: TaskCreate, idempotency_key=None):
        body_hash = request_hash(data)
        task_id = ("t_" + uuid.uuid5(_NS, f"{owner_id}:{idempotency_key}").hex[:12]
                   if idempotency_key else "t_" + uuid.uuid4().hex[:12])

        if idempotency_key:                               # fast path for an obvious replay
            existing = self.tasks.find_one({"_id": task_id})
            if existing:
                return self._replay(existing, body_hash)

        if self.tasks.count_documents({"owner_id": owner_id, "deleted_at": None}) >= self.max_tasks:
            raise QuotaExceeded()

        now = _now()
        doc = {"_id": task_id, "owner_id": owner_id, "title": data.title,
               "description": data.description, "status": "todo", "priority": data.priority.value,
               "due_date": data.due_date.isoformat() if data.due_date else None,
               "tags": data.tags, "version": 1, "created_at": now, "updated_at": now,
               "deleted_at": None, "idem_hash": body_hash}
        doc.update(_derived(doc))

        def txn(session):
            self.tasks.insert_one(doc, session=session)
            self._audit(task_id, owner_id, "created", {"title": data.title}, session)

        try:
            self._run(txn)
        except DuplicateKeyError:                         # lost a race with an identical retry
            return self._replay(self.tasks.find_one({"_id": task_id}), body_hash)
        return self._to_record(doc), False

    def _replay(self, existing: dict, body_hash: str):
        if existing.get("idem_hash") != body_hash:
            raise IdempotencyKeyReused()
        return self._to_record(existing), True

    # ── READ ───────────────────────────────────────────────────────────
    def get(self, task_id, include_deleted=False):
        flt = {"_id": task_id} if include_deleted else {"_id": task_id, "deleted_at": None}
        doc = self.tasks.find_one(flt)
        return self._to_record(doc) if doc else None

    def list(self, q: TaskQuery):
        f: dict = {"deleted_at": None}
        if q.owner_id:
            f["owner_id"] = q.owner_id
        if q.status:
            f["status"] = q.status.value
        if q.priority:
            f["priority"] = q.priority.value
        if q.tag:
            f["tags"] = q.tag.lower()
        if q.text:
            f["title"] = {"$regex": re.escape(q.text), "$options": "i"}
        if q.due_before:
            f["due_date"] = {"$ne": None, "$lt": q.due_before.isoformat()}
        d = ASCENDING if q.order == "asc" else DESCENDING
        sort = {"created_at": [("created_at", d), ("_id", 1)],
                "updated_at": [("updated_at", d), ("_id", 1)],
                "due_date": [("due_null", 1), ("due_date", d), ("_id", 1)],
                "priority": [("priority_rank", d), ("_id", 1)]}.get(q.sort_by, [("created_at", d)])
        total = self.tasks.count_documents(f)
        docs = list(self.tasks.find(f).sort(sort).skip(q.offset).limit(q.limit))
        return [self._to_record(x) for x in docs], total

    # ── UPDATE ─────────────────────────────────────────────────────────
    def _update(self, task_id, changes: dict, expected_version, actor_id, action):
        flt: dict = {"_id": task_id, "deleted_at": None}
        if expected_version is not None:
            flt["version"] = expected_version                 # ← the optimistic lock lives in the filter
        setter = {**changes, **_derived(changes), "updated_at": _now()}

        def txn(session):
            doc = self.tasks.find_one_and_update(
                flt, {"$set": setter, "$inc": {"version": 1}},
                return_document=ReturnDocument.AFTER, session=session)
            if doc is not None:
                self._audit(task_id, actor_id, action, {"fields": sorted(changes)}, session)
            return doc

        doc = self._run(txn)
        if doc is None:                                       # decide: missing, or stale version?
            current = self.tasks.find_one({"_id": task_id, "deleted_at": None})
            if current is None:
                raise TaskNotFound()
            raise VersionConflict(current=current["version"])
        return self._to_record(doc)

    def replace(self, task_id, data: TaskReplace, expected_version, actor_id):
        return self._update(task_id, data.model_dump(mode="json"), expected_version, actor_id, "replaced")

    def patch(self, task_id, changes, expected_version, actor_id):
        return self._update(task_id, changes, expected_version, actor_id, "patched")

    # ── DELETE ─────────────────────────────────────────────────────────
    def delete(self, task_id, actor_id):
        def txn(session):
            now = _now()
            res = self.tasks.update_one({"_id": task_id, "deleted_at": None},
                                        {"$set": {"deleted_at": now, "updated_at": now},
                                         "$inc": {"version": 1}}, session=session)
            if res.modified_count == 1:
                self._audit(task_id, actor_id, "deleted", session=session)
            return res.modified_count == 1

        if self._run(txn):
            return True
        if self.tasks.find_one({"_id": task_id}) is None:
            raise TaskNotFound()
        return False                                          # already deleted → idempotent success

    def events(self, task_id):
        return [{k: d[k] for k in ("action", "actor_id", "at", "detail")}
                for d in self.events_col.find({"task_id": task_id}).sort("_id", 1)]
