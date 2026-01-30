from __future__ import annotations
from datetime import datetime
from uuid import uuid4
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

def _utc_now() -> datetime:
    return datetime.now().astimezone()

class Message(BaseModel):
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: Dict[str, object] = Field(default_factory=dict)

class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    user_id: Optional[str] = None
    messages: List[Message] = Field(default_factory=list)
    context: Dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    def add_message(self, role: str, content: str, metadata: Dict[str, object] | None = None) -> None:
        self.messages.append(Message(role=role, content=content, metadata=metadata or {}))
        self.updated_at = _utc_now()

    def update_context(self, key: str, value: object) -> None:
        self.context[key] = value
        self.updated_at = _utc_now()
