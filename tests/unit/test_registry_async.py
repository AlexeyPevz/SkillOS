import pytest
import asyncio
import threading
import time
from unittest.mock import MagicMock, patch
from skillos.skills.registry import SkillRegistry, SkillRecord
from skillos.skills.models import SkillMetadata

def sync_skill(payload):
    time.sleep(0.1)  # Simulate blocking work
    return f"sync-result-{threading.get_ident()}-{payload}"

async def async_skill(payload):
    await asyncio.sleep(0.1)
    return f"async-result-{threading.get_ident()}-{payload}"

@pytest.fixture
def registry():
    # Helper to create a registry with mocked internal storage
    reg = SkillRegistry("dummy_root")
    reg._skills = {}
    return reg

@pytest.mark.asyncio
async def test_execute_async_with_sync_function(registry):
    """
    Verify that a synchronous skill is executed in a separate thread
    to avoid blocking the main event loop.
    """
    # Mock resolve_entrypoint to return our sync function
    with patch("skillos.skills.registry.resolve_entrypoint", return_value=sync_skill):
        # Register a dummy skill
        meta = SkillMetadata(
            id="test/sync", 
            name="Sync Skill", 
            version="1.0.0", 
            entrypoint="mod:func",
            description="A test sync skill"
        )
        registry._skills["test/sync"] = SkillRecord(metadata=meta, source="dummy")

        # Capture main thread ID
        main_thread_id = threading.get_ident()

        # Execute
        result = await registry.execute_async("test/sync", payload="test")

        # Parse result to check thread ID
        parts = result.split("-")
        thread_id = parts[2]
        
        # Verify it ran in a DIFFERENT thread
        assert int(thread_id) != main_thread_id
        assert result.endswith("-test")

@pytest.mark.asyncio
async def test_execute_async_with_async_function(registry):
    """
    Verify that an asynchronous skill is executed natively (awaited)
    in the SAME thread (event loop thread).
    """
    # Mock resolve_entrypoint to return our async function
    with patch("skillos.skills.registry.resolve_entrypoint", return_value=async_skill):
        # Register a dummy skill
        meta = SkillMetadata(
            id="test/async", 
            name="Async Skill", 
            version="1.0.0", 
            entrypoint="mod:func",
            description="A test async skill"
        )
        registry._skills["test/async"] = SkillRecord(metadata=meta, source="dummy")

        # Capture main thread ID
        main_thread_id = threading.get_ident()

        # Execute
        result = await registry.execute_async("test/async", payload="test")

        # Parse result to check thread ID
        parts = result.split("-")
        thread_id = parts[2]
        
        # Verify it ran in the SAME thread (because it's async)
        assert int(thread_id) == main_thread_id
        assert result.endswith("-test")
