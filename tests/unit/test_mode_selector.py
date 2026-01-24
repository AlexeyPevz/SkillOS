from skillos.mode_selector import select_mode, split_query


def test_select_mode_prefers_pipeline() -> None:
    assert select_mode("Do this then that") == "pipeline"


def test_select_mode_parallel() -> None:
    assert select_mode("Do this and that") == "parallel"


def test_split_query_pipeline() -> None:
    parts = split_query("First then second", "pipeline")
    assert parts == ["First", "second"]


def test_split_query_parallel() -> None:
    parts = split_query("Alpha and beta", "parallel")
    assert parts == ["Alpha", "beta"]


def test_split_query_auto_single() -> None:
    parts = split_query("Just one task", "auto")
    assert parts == ["Just one task"]
