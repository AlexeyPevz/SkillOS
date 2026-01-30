from skillos.orchestrator import Orchestrator
from skillos.session.models import Session


def _make_session(messages: list[tuple[str, str]]) -> Session:
    session = Session()
    for role, content in messages:
        session.add_message(role, content)
    return session


def test_compact_session_trims_and_summarizes(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILLOS_SESSION_MAX_TOKENS", "1")
    monkeypatch.setenv("SKILLOS_SESSION_KEEP_LAST", "2")
    monkeypatch.setenv("SKILLOS_SESSION_SUMMARY_MAX_CHARS", "500")

    orchestrator = Orchestrator(tmp_path, dev_mode=True)
    session = _make_session(
        [
            ("user", "hello world"),
            ("assistant", "ack one"),
            ("user", "next step"),
        ]
    )

    orchestrator._compact_session(session)

    assert len(session.messages) == 2
    summary = session.context.get("history_summary")
    assert summary is not None
    assert "user:" in summary


def test_compact_session_appends_existing_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILLOS_SESSION_MAX_TOKENS", "1")
    monkeypatch.setenv("SKILLOS_SESSION_KEEP_LAST", "1")
    monkeypatch.setenv("SKILLOS_SESSION_SUMMARY_MAX_CHARS", "500")

    orchestrator = Orchestrator(tmp_path, dev_mode=True)
    session = _make_session([("user", "alpha beta"), ("assistant", "gamma delta")])
    session.context["history_summary"] = "previous summary"

    orchestrator._compact_session(session)

    summary = session.context.get("history_summary")
    assert summary is not None
    assert "previous summary" in summary


def test_compact_session_noop_under_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILLOS_SESSION_MAX_TOKENS", "1000")
    monkeypatch.setenv("SKILLOS_SESSION_KEEP_LAST", "2")

    orchestrator = Orchestrator(tmp_path, dev_mode=True)
    session = _make_session([("user", "hello"), ("assistant", "ok")])
    original_messages = list(session.messages)

    orchestrator._compact_session(session)

    assert session.messages == original_messages
    assert session.context.get("history_summary") is None
