import pytest
from skillos.flow import SkillFlow
from skillos.sdk import Context

def test_flow_linear_execution():
    flow = SkillFlow("linear_flow")
    
    @flow.start
    def start_node(state):
        state["count"] = state.get("count", 0) + 1
        return state
        
    @flow.node("step2")
    def step2(state):
        state["count"] += 10
        return state
        
    flow.add_edge("start", lambda s: "step2")
    flow.add_edge("step2", lambda s: "__end__")
    
    result = flow.run({"count": 0})
    assert result["count"] == 11

def test_flow_cycle_execution():
    """Test a loop (e.g. while count < 3)"""
    flow = SkillFlow("cycle_flow")
    
    @flow.start
    def loop_body(state):
        state["iterations"] = state.get("iterations", 0) + 1
        return state
        
    def loop_condition(state):
        if state["iterations"] < 3:
            return "start" # Loop back
        return "__end__"
        
    flow.add_edge("start", loop_condition)
    
    result = flow.run({"iterations": 0})
    assert result["iterations"] == 3

def test_flow_max_steps_safety():
    """Test infinite loop protection"""
    flow = SkillFlow("infinite")
    
    @flow.start
    def node(state):
        return state
        
    flow.add_edge("start", lambda s: "start")
    
    # Expect error after max steps
    with pytest.raises(RecursionError, match="exceeded maximum steps"):
        flow.run({})
