import pytest
import sqlite3
import json
from pathlib import Path
from skillos.session.models import Session, Message
from skillos.session.store import SessionStore

@pytest.fixture
def session_store(tmp_path):
    return SessionStore(tmp_path)

def test_create_get_session(session_store):
    session = session_store.create_session(user_id="user123")
    assert session.id is not None
    assert session.user_id == "user123"

    retrieved = session_store.get_session(session.id)
    assert retrieved is not None
    assert retrieved.id == session.id
    assert retrieved.user_id == "user123"

def test_add_messages(session_store):
    session = session_store.create_session()
    
    msg1 = Message(role="user", content="hello")
    msg2 = Message(role="assistant", content="hi there")
    
    session_store.add_message(session.id, msg1)
    session_store.add_message(session.id, msg2)
    
    retrieved = session_store.get_session(session.id)
    assert len(retrieved.messages) == 2
    assert retrieved.messages[0].content == "hello"
    assert retrieved.messages[1].content == "hi there"

def test_update_context(session_store):
    session = session_store.create_session()
    session.update_context("name", "Alice")
    session_store.save_session(session)
    
    retrieved = session_store.get_session(session.id)
    assert retrieved.context.get("name") == "Alice"
