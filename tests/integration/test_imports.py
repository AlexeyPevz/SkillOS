import pytest
import sys
from skillos.orchestrator import Orchestrator
from skillos.skills.registry import SkillRegistry

@pytest.fixture
def import_test_root(tmp_path):
    root = tmp_path / "skillos_import_test"
    root.mkdir()
    
    # Create implementations package structure
    impl = root / "implementations"
    impl.mkdir()
    (impl / "__init__.py").write_text("")
    
    # Create a shared utility module
    (impl / "utils.py").write_text("def helper(): return 'helper_called'")
    
    # Create a skill that uses relative import
    (impl / "consumer.py").write_text("""
from skillos.sdk import skill
from . import utils

@skill(name="Consumer", description="Uses relative import")
def consumer(payload: str):
    return f"Consumed: {utils.helper()}"
""")

    # Create a subpackage skill
    sub = impl / "sub"
    sub.mkdir()
    (sub / "__init__.py").write_text("")
    (sub / "deep.py").write_text("""
from skillos.sdk import skill
from ..utils import helper

@skill(name="DeepConsumer", description="Uses parent relative import")
def deep(payload: str):
    return f"Deep: {helper()}"
""")

    return root

def test_relative_import_execution(import_test_root):
    # Setup orchestrator
    orc = Orchestrator.run_simple("foo", import_test_root) # warmup logic
    
    # Direct registry check
    registry = SkillRegistry(import_test_root)
    skills = registry.load_all()
    
    # Verify both skills loaded despite relative imports
    assert "local/Consumer" in skills
    assert "local/DeepConsumer" in skills
    
    # Verify execution works (meaning module resolution was correct at runtime)
    # Orchestrator run_simple wraps execution
    result_consumer = Orchestrator.run_simple("Consumer", import_test_root)
    assert result_consumer == "Consumed: helper_called"
    
    result_deep = Orchestrator.run_simple("DeepConsumer", import_test_root)
    assert result_deep == "Deep: helper_called"

def test_import_cleanup_on_failure(import_test_root):
    """Verify sys.modules is not poisoned by partial loads"""
    bad = import_test_root / "implementations" / "bad.py"
    bad.write_text("""
from . import non_existent
""")
    
    registry = SkillRegistry(import_test_root)
    skills = registry.load_all() # Should interpret bad.py failure gracefully
    
    # Verify registry didn't crash and "bad" is not in skills
    assert "local/Bad" not in skills
    
    # Verify module is NOT in sys.modules
    assert "implementations.bad" not in sys.modules
