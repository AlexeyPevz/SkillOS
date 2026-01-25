import pytest
from pathlib import Path
from skillos.orchestrator import Orchestrator
from skillos.sdk import skill, Context

# Define a simple skill using the new SDK
@skill(name="hello-world", description="A simple hello world skill")
def hello_world(payload: str, ctx: Context = None):
    return f"Hello, {payload}!"

@pytest.fixture
def dev_root(tmp_path):
    root = tmp_path / "skillos_root"
    root.mkdir()
    (root / "metadata").mkdir()
    (root / "implementations").mkdir()
    return root

def test_run_simple_flow(dev_root):
    """
    Test that Orchestrator.run_simple works in dev_mode without complex setup.
    """
    # Create a dummy skill to verify routing (since we mocked router in dev_mode, 
    # we might need to manually inject skill or just test the mechanism)
    
    # Actually, run_simple mocks the router in dev_mode to return 'low_confidence' or empty
    # unless we configure it.
    # But wait, in my implementation of run_simple, I instantiated Orchestrator(dev_mode=True).
    # And in __init__, if dev_mode=True, I mocked the router: 
    # self.router = build_router_from_env(self.skills_metadata) 
    
    # If the skill registry is empty, router won't find anything.
    # run_simple is intended for "local dev", so it expects files on disk.
    
    # Write a Python-only skill (Zero YAML)
    skill_file = dev_root / "implementations" / "greet.py"
    skill_file.write_text("""
from skillos.sdk import skill

@skill(name="Greet", description="Greets the user", tags=["hello"])
def greet(payload: str):
    return f"Greetings, {payload}"
""")
    
    # NOTE: We do NOT create any YAML file here. 
    # This verifies the "Zero YAML" discovery feature.

    # Now run simple
    # We pass root_path to ensure correct discovery
    # Use "hello" to match the tag explicitly
    output = Orchestrator.run_simple("hello", dev_root)
    
    # Verify exact output
    assert output == "Greetings, hello"
