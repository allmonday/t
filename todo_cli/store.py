from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

from .models import Todo


class TodoStore:
    def __init__(self, db_path: str = "~/.todo.db"):
        self.db_path = os.path.expanduser(db_path)
        self.conn: sqlite3.Connection | None = None

    def _require_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self.conn

    # ── lifecycle ──

    def connect(self) -> None:
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()
        self._seed_if_empty()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> TodoStore:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── schema ──

    def _create_tables(self) -> None:
        conn = self._require_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                parent INTEGER REFERENCES todos(id),
                created TEXT NOT NULL,
                done_at TEXT,
                deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                todo_id INTEGER NOT NULL,
                details TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_todos_parent ON todos(parent);
            CREATE INDEX IF NOT EXISTS idx_todos_active ON todos(deleted_at) WHERE deleted_at IS NULL;
            CREATE INDEX IF NOT EXISTS idx_audit_time ON audit(timestamp);
        """)

    def _seed_if_empty(self) -> None:
        conn = self._require_conn()
        row = conn.execute("SELECT COUNT(*) as cnt FROM todos").fetchone()
        if row["cnt"] > 0:
            return
        now = datetime.now().isoformat()
        seeds_root = [
            ("快速上手 Todo CLI", False),
            ("示例项目", False),
            ("按 d 删除此任务试试", False),
        ]
        with conn:
            root_ids: list[int] = []
            for text, done in seeds_root:
                cur = conn.execute(
                    "INSERT INTO todos (text, done, parent, created) VALUES (?, ?, NULL, ?)",
                    (text, int(done), now),
                )
                root_ids.append(cur.lastrowid)

            seed_children = [
                ("按 Space 切换完成状态", False, root_ids[0]),
                ("按 Tab 添加子任务", False, root_ids[0]),
                ("按 ←→ 折叠/展开树节点", False, root_ids[0]),
                ("设计方案", True, root_ids[1]),
                ("编码实现", False, root_ids[1]),
            ]
            for text, done, parent_id in seed_children:
                conn.execute(
                    "INSERT INTO todos (text, done, parent, created, done_at) VALUES (?, ?, ?, ?, ?)",
                    (text, int(done), parent_id, now, now if done else None),
                )

    # ── queries ──

    def _row_to_todo(self, row: sqlite3.Row) -> Todo:
        return Todo(
            id=row["id"],
            text=row["text"],
            done=bool(row["done"]),
            parent=row["parent"],
            created=row["created"],
            done_at=row["done_at"],
            deleted_at=row["deleted_at"],
        )

    def list_active(self) -> list[Todo]:
        conn = self._require_conn()
        rows = conn.execute(
            "SELECT * FROM todos WHERE deleted_at IS NULL ORDER BY id"
        ).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def list_roots(self, filter_done: bool | None = None) -> list[Todo]:
        conn = self._require_conn()
        sql = "SELECT * FROM todos WHERE parent IS NULL AND deleted_at IS NULL"
        params: list = []
        if filter_done is not None:
            sql += " AND done = ?"
            params.append(int(filter_done))
        sql += " ORDER BY id"
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def get(self, todo_id: int) -> Todo | None:
        conn = self._require_conn()
        row = conn.execute(
            "SELECT * FROM todos WHERE id = ? AND deleted_at IS NULL", (todo_id,)
        ).fetchone()
        return self._row_to_todo(row) if row else None

    def get_children(self, todo_id: int) -> list[Todo]:
        conn = self._require_conn()
        rows = conn.execute(
            "SELECT * FROM todos WHERE parent = ? AND deleted_at IS NULL ORDER BY id",
            (todo_id,),
        ).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def get_descendants(self, todo_id: int) -> list[Todo]:
        """使用递归 CTE 一次查询获取所有子孙节点。"""
        conn = self._require_conn()
        rows = conn.execute("""
            WITH RECURSIVE descendants(id) AS (
                SELECT id FROM todos WHERE parent = ? AND deleted_at IS NULL
                UNION ALL
                SELECT t.id FROM todos t
                INNER JOIN descendants d ON t.parent = d.id
                WHERE t.deleted_at IS NULL
            )
            SELECT todos.* FROM todos
            INNER JOIN descendants d ON todos.id = d.id
            ORDER BY todos.id
        """, (todo_id,)).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def has_children(self, todo_id: int) -> bool:
        conn = self._require_conn()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM todos WHERE parent = ? AND deleted_at IS NULL",
            (todo_id,),
        ).fetchone()
        return row["cnt"] > 0

    # ── mutations ──

    def add(self, text: str, parent_id: int | None = None) -> Todo:
        conn = self._require_conn()
        if parent_id is not None and self.get(parent_id) is None:
            raise ValueError(f"Parent todo #{parent_id} not found")
        now = datetime.now().isoformat()
        with conn:
            cur = conn.execute(
                "INSERT INTO todos (text, done, parent, created) VALUES (?, 0, ?, ?)",
                (text, parent_id, now),
            )
            todo_id = cur.lastrowid
            self._log_audit("add", todo_id, {"text": text, "parent": parent_id})
        return self.get(todo_id)  # type: ignore[return-value]

    def update_text(self, todo_id: int, new_text: str) -> bool:
        conn = self._require_conn()
        todo = self.get(todo_id)
        if not todo:
            return False
        with conn:
            conn.execute("UPDATE todos SET text = ? WHERE id = ?", (new_text, todo_id))
            self._log_audit("edit", todo_id, {"old_text": todo.text, "new_text": new_text})
        return True

    def toggle(self, todo_id: int) -> bool:
        conn = self._require_conn()
        todo = self.get(todo_id)
        if not todo:
            return False
        if self.has_children(todo_id):
            return False
        new_done = not todo.done
        now = datetime.now().isoformat() if new_done else None
        with conn:
            conn.execute(
                "UPDATE todos SET done = ?, done_at = ? WHERE id = ?",
                (int(new_done), now, todo_id),
            )
            self._log_audit("toggle", todo_id, {"done": new_done})
            self._bubble_up(todo_id)
        return True

    def delete(self, todo_id: int) -> int:
        conn = self._require_conn()
        todo = self.get(todo_id)
        if not todo:
            return 0
        now = datetime.now().isoformat()
        descendants = self.get_descendants(todo_id)
        ids = [todo_id] + [d.id for d in descendants]
        with conn:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE todos SET deleted_at = ? WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                [now] + ids,
            )
            self._log_audit("delete", todo_id, {
                "text": todo.text,
                "subtasks_count": len(descendants),
            })
        return len(ids)

    def _bubble_up(self, todo_id: int) -> None:
        """从当前节点向上冒泡更新祖先 done 状态。"""
        conn = self._require_conn()
        todo = self.get(todo_id)
        if not todo or not todo.parent:
            return
        parent = self.get(todo.parent)
        if not parent:
            return
        children = self.get_children(parent.id)
        all_done = len(children) > 0 and all(c.done for c in children)
        if parent.done != all_done:
            now = datetime.now().isoformat() if all_done else None
            conn.execute(
                "UPDATE todos SET done = ?, done_at = ? WHERE id = ?",
                (int(all_done), now, parent.id),
            )
            self._log_audit("auto_toggle", parent.id, {
                "done": all_done,
                "triggered_by": todo_id,
            })
            self._bubble_up(parent.id)

    # ── audit ──

    def _log_audit(self, action: str, todo_id: int, details: dict) -> None:
        conn = self._require_conn()
        conn.execute(
            "INSERT INTO audit (timestamp, action, todo_id, details) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), action, todo_id, json.dumps(details, ensure_ascii=False)),
        )

    def get_audit(self, limit: int = 50, action: str | None = None) -> list[dict]:
        conn = self._require_conn()
        sql = "SELECT * FROM audit"
        params: list = []
        if action:
            sql += " WHERE action = ?"
            params.append(action)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "action": r["action"],
                "todo_id": r["todo_id"],
                "details": json.loads(r["details"]) if r["details"] else {},
            }
            for r in rows
        ]
