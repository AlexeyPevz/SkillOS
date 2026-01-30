import pytest
from skillos.kernel import get_kernel
from skillos.kernel.local import LocalExecutionKernel
from skillos.skills.models import SkillMetadata

def test_kernel_factory_selection():
    # Test local
    meta_local = SkillMetadata(
        id="test/local",
        name="Local Skill",
        description="test",
        version="1.0.0",
        entrypoint="impl:func",
        execution_mode="local"
    )
    kernel_local = get_kernel(meta_local)
    assert isinstance(kernel_local, LocalExecutionKernel)

    # Test default (local)
    meta_default = SkillMetadata(
        id="test/default",
        name="Default Skill",
        description="test",
        version="1.0.0",
        entrypoint="impl:func"
    )
    kernel_default = get_kernel(meta_default)
    assert isinstance(kernel_default, LocalExecutionKernel)

    # Test docker (not implemented)
    meta_docker = SkillMetadata(
        id="test/docker",
        name="Docker Skill",
        description="test",
        version="1.0.0",
        entrypoint="impl:func",
        execution_mode="docker"
    )
    with pytest.raises(NotImplementedError, match="Docker execution kernel is not yet implemented"):
        get_kernel(meta_docker)

def test_kernel_factory_caching():
    meta1 = SkillMetadata(id="a/b", name="n", description="d", version="1.0.0", entrypoint="m:f")
    meta2 = SkillMetadata(id="c/d", name="n", description="d", version="1.0.0", entrypoint="m:f")
    
    k1 = get_kernel(meta1)
    k2 = get_kernel(meta2)
    
    # In my current implementation, it's a singleton per mode
    assert k1 is k2  
