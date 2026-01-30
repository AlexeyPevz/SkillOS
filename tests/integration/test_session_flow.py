import pytest
import os
from pathlib import Path
from skillos.orchestrator import Orchestrator
from skillos.session import SessionStore

@pytest.fixture
def orchestrator(tmp_path):
    # Setup a dummy skill for testing
    skills_root = tmp_path / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    metadata_dir = skills_root / "metadata" / "test"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    impl_dir = skills_root / "implementations"
    impl_dir.mkdir(parents=True, exist_ok=True)
    
    with open(impl_dir / "hello.py", "w") as f:
        f.write("def say_hello(payload='world', **kwargs): return 'Hello, ' + payload")

    with open(impl_dir / "context.py", "w") as f:
        f.write(
            "def echo_context(payload='ok', **kwargs):\n"
            "    ctx = kwargs.get('session_context') or {}\n"
            "    recent = ctx.get('recent_messages') or []\n"
            "    summary = ctx.get('summary')\n"
            "    return f\"summary={summary};recent={len(recent)}\""
        )
    
    with open(metadata_dir / "hello.yaml", "w") as f:
        f.write(
            "id: test/hello\n"
            "name: Hello\n"
            "description: test\n"
            "version: 1.0.0\n"
            "entrypoint: implementations.hello:say_hello\n"
        )

    with open(metadata_dir / "context.yaml", "w") as f:
        f.write(
            "id: test/context\n"
            "name: Context\n"
            "description: test\n"
            "version: 1.0.0\n"
            "entrypoint: implementations.context:echo_context\n"
        )
        
    return Orchestrator(skills_root, dev_mode=True)

def test_orchestrator_session_persistence(orchestrator):
    session_id = "test-session-1"
    # Use exact skill ID as query to help the router if needed, 
    # but Orchestrator might still use the router.
    # We will mock the router if needed, but let's try with a clear query first.
    query = "test/hello"
    
    # Force reload registry to pick up the skill
    orchestrator._maybe_reload_registry()
    
    # Mock routing for the test
    from skillos.routing import RoutingResult, SkillCandidate
    original_route = orchestrator.router.route
    def mock_route(q, **kwargs):
        if q == "test/hello":
             return RoutingResult(
                 status="selected",
                 skill_id="test.hello",
                 internal_skill_id="test/hello",
                 confidence=1.0,
                 candidates=[],
                 alternatives=[]
             )
        return original_route(q, **kwargs)
    orchestrator.router.route = mock_route

    # Turn 1
    resp1 = orchestrator.run_query(query, execute=True, mode="single", session_id=session_id)
    assert resp1["status"] == "success"
    assert resp1["session_id"] == session_id
    
    # Verify store
    store = SessionStore(orchestrator.root_path)
    session = store.get_session(session_id)
    assert session is not None
    assert len(session.messages) == 2 # User + Assistant
    assert session.messages[0].role == "user"
    assert session.messages[1].role == "assistant"
    assert "Hello" in session.messages[1].content

def test_orchestrator_session_history_turn2(orchestrator):
    session_id = "multi-turn-session"
    
    # Mock routing for the test
    from skillos.routing import RoutingResult
    orchestrator._maybe_reload_registry()
    def mock_route(q, **kwargs):
        return RoutingResult(
            status="selected",
            skill_id="test.hello",
            internal_skill_id="test/hello",
            confidence=1.0,
            candidates=[],
            alternatives=[]
        )
    orchestrator.router.route = mock_route

    # Turn 1
    orchestrator.run_query("test/hello", execute=True, session_id=session_id)
    
    # Turn 2
    orchestrator.run_query("test/hello", execute=True, session_id=session_id)
    
    store = SessionStore(orchestrator.root_path)
    session = store.get_session(session_id)
    assert session is not None
    assert len(session.messages) == 4 # (U+A) * 2

def test_session_context_injected(orchestrator, monkeypatch):
    monkeypatch.setenv("SKILLOS_SESSION_RECENT_MESSAGES", "2")
    session_id = "context-session"

    from skillos.routing import RoutingResult
    orchestrator._maybe_reload_registry()
    def mock_route(q, **kwargs):
        return RoutingResult(
            status="selected",
            skill_id="test.context",
            internal_skill_id="test/context",
            confidence=1.0,
            candidates=[],
            alternatives=[]
        )
    orchestrator.router.route = mock_route

    resp = orchestrator.run_query("anything", execute=True, session_id=session_id)
    assert resp["status"] == "success"
    assert "recent=1" in resp["output"]

def test_session_compaction_summary(orchestrator, monkeypatch):
    monkeypatch.setenv("SKILLOS_SESSION_MAX_TOKENS", "1")
    monkeypatch.setenv("SKILLOS_SESSION_KEEP_LAST", "1")
    monkeypatch.setenv("SKILLOS_SESSION_SUMMARY_MAX_CHARS", "200")

    session_id = "compact-session"
    from skillos.routing import RoutingResult
    orchestrator._maybe_reload_registry()
    def mock_route(q, **kwargs):
        return RoutingResult(
            status="selected",
            skill_id="test.hello",
            internal_skill_id="test/hello",
            confidence=1.0,
            candidates=[],
            alternatives=[]
        )
    orchestrator.router.route = mock_route

    resp = orchestrator.run_query("one two three", execute=True, session_id=session_id)
    assert resp["status"] == "success"

    store = SessionStore(orchestrator.root_path)
    session = store.get_session(session_id)
    assert session is not None
    assert session.context.get("history_summary") is not None
    assert len(session.messages) <= 1
