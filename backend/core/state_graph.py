import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from core.graph_state import WorkflowState


@dataclass
class GraphNode:
    name: str
    run: Callable[[WorkflowState], WorkflowState]


@dataclass
class GraphEdge:
    from_node: str
    to_node: str
    condition: Optional[Callable[[WorkflowState], bool]] = None


class StateGraphRunner:
    def __init__(self, nodes: List[GraphNode], edges: List[GraphEdge], start_node: str, max_steps: int = 20):
        self.nodes: Dict[str, GraphNode] = {node.name: node for node in nodes}
        self.edges = edges
        self.start_node = start_node
        self.max_steps = max_steps

    def run(self, state: WorkflowState) -> WorkflowState:
        current = self.start_node
        steps = 0
        while current:
            if steps >= self.max_steps:
                state.errors.append("StateGraph exceeded max steps")
                return state
            node = self.nodes.get(current)
            if not node:
                state.errors.append(f"StateGraph missing node: {current}")
                return state
            start = time.time()
            try:
                state = node.run(state)
                elapsed = time.time() - start
                state.trace.append({"node": current, "elapsed": round(elapsed, 3), "next_action": state.next_action})
            except Exception as exc:
                elapsed = time.time() - start
                state.errors.append(f"{current}: {exc}")
                state.trace.append({"node": current, "elapsed": round(elapsed, 3), "error": str(exc)})
                return state
            steps += 1
            current = self._next_node(current, state)
        return state

    def _next_node(self, current: str, state: WorkflowState) -> Optional[str]:
        for edge in self.edges:
            if edge.from_node != current:
                continue
            if edge.condition is None or edge.condition(state):
                return edge.to_node
        return None
