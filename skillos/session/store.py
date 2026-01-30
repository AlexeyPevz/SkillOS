from __future__ import annotations
import sqlite3
import json
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from skillos.session.models import Session, Message
from skillos.tenancy import resolve_tenant_root

class SessionStore:
    def __init__(self, root_path: Path):
        self.root_path = resolve_tenant_root(root_path)
        self.db_path = self.root_path / "runtime" / "sessions.db"
        self._ensure_db()

    def _ensure_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    context TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    timestamp TEXT,
                    metadata TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
            """)
            conn.commit()

    def create_session(self, user_id: Optional[str] = None, session_id: Optional[str] = None) -> Session:
        session = Session(id=session_id, user_id=user_id) if session_id else Session(user_id=user_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (id, user_id, context, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (
                    session.id,
                    session.user_id,
                    json.dumps(session.context),
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            
            # id, user_id, context, created, updated
            session_id, user_id, context_json, created_at, updated_at = row
            
            # Fetch messages
            # session_id, role, content, timestamp, metadata
            msg_rows = conn.execute(
                "SELECT role, content, timestamp, metadata FROM messages WHERE session_id = ? ORDER BY timestamp", 
                (session_id,)
            ).fetchall()
            
            messages = []
            for r_role, r_content, r_ts, r_meta in msg_rows:
                messages.append(Message(
                    role=r_role,
                    content=r_content,
                    timestamp=datetime.fromisoformat(r_ts),
                    metadata=json.loads(r_meta) if r_meta else {}
                ))

            # Reconstruct session
            session = Session(
                id=session_id,
                user_id=user_id,
                messages=messages,
                context=json.loads(context_json) if context_json else {},
                created_at=datetime.fromisoformat(created_at),
                updated_at=datetime.fromisoformat(updated_at)
            )
            return session

    def save_session(self, session: Session) -> None:
        # Full save (upsert session, update messages)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET user_id = ?, context = ?, updated_at = ? WHERE id = ?",
                (
                    session.user_id,
                    json.dumps(session.context),
                    session.updated_at.isoformat(),
                    session.id,
                )
            )
            
            # Simple sync strategy: clear and re-insert all messages for the session
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session.id,))
            for msg in session.messages:
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?)",
                    (
                        session.id,
                        msg.role,
                        msg.content,
                        msg.timestamp.isoformat(),
                        json.dumps(msg.metadata),
                    )
                )
            conn.commit()

    def add_message(self, session_id: str, message: Message) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    message.role,
                    message.content,
                    message.timestamp.isoformat(),
                    json.dumps(message.metadata),
                )
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (message.timestamp.isoformat(), session_id)
            )
