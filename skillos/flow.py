from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from skillos.sdk import Context


class NodeProtocol(Protocol):
    def __call__(self, state: dict, ctx: Context) -> dict: ...


@dataclass
class FlowState:
    data: dict = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    next_node: str | None = None
    terminated: bool = False


class SkillFlow:
    """
    A lightweight state machine for defining cyclic or multi-step skills.
    Inspired by LangGraph but adapted for SkillOS's functional paradigm.
    """

    def __init__(self, name: str, entry_point: str = "start"):
        self.name = name
        self.nodes: Dict[str, NodeProtocol] = {}
        self.edges: Dict[str, Callable[[dict], str]] = {}
        self.entry_point = entry_point
        self._on_start = None

    def node(self, name: str) -> Callable:
        """Decorator to register a node function."""
        def decorator(func: NodeProtocol) -> NodeProtocol:
            self.nodes[name] = func
            return func
        return decorator

    def add_edge(self, from_node: str, condition: Callable[[dict], str]):
        """Define transition logic from a node."""
        self.edges[from_node] = condition

    def start(self, func: NodeProtocol):
        """Decorator for the entry point node."""
        self.nodes[self.entry_point] = func
        return func

    def run(self, initial_payload: Any, ctx: Context = None) -> Any:
        # Initialize state
        state = initial_payload if isinstance(initial_payload, dict) else {"payload": initial_payload}
        current_node = self.entry_point
        steps = 0
        max_steps = 50  # Safety limit

        if ctx:
            ctx.log(f"Flow {self.name} started at {current_node}")

        while current_node and steps < max_steps:
            if current_node not in self.nodes:
                raise ValueError(f"Flow terminated: Node '{current_node}' not found.")

            node_func = self.nodes[current_node]
            
            # Execute node
            # We support functions that take (state, ctx) or just (state)
            sig = inspect.signature(node_func)
            if "ctx" in sig.parameters:
                new_state = node_func(state, ctx=ctx)
            else:
                new_state = node_func(state)
            
            # Update state (merge or replace? LangGraph typically passes state. simple replace for now)
            if new_state is not None:
                if isinstance(new_state, dict):
                     state.update(new_state)
                else:
                     state["result"] = new_state

            steps += 1
            
            # Determine next node
            if current_node in self.edges:
                transition_logic = self.edges[current_node]
                next_node = transition_logic(state)
            else:
                next_node = None # End of flow

            if ctx:
                ctx.log(f"Flow step {steps}: {current_node} -> {next_node}")
            
            current_node = next_node
            
            if next_node == "__end__":
                break
        
        if steps >= max_steps:
             raise RecursionError(f"Flow '{self.name}' exceeded maximum steps ({max_steps})")

        return state
