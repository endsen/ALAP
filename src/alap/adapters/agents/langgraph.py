"""LangGraph routing with ALAP transactional PostgreSQL checkpoints.

ALAP commits checkpoints, proposals and invocation ledgers together. Resuming the
logical graph never implicitly repeats an uncommitted provider call or dispatches
a physical command. Only run identity and routing state enter the graph itself.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context


class StepState(TypedDict):
    run_id: str
    actor: str
    revision: int
    status: str
    stage: str


class LangGraphAgentRunner:
    def __init__(self, runtime):
        self.runtime = runtime

    def _invoke(self, actor, identity, cancel, *, continuous):
        with self.runtime.store.exclusive(identity), tracing_context(enabled=False):

            def inspect(state):
                run = self.runtime.store.load(state["actor"], state["run_id"])
                return {
                    "revision": run["revision"],
                    "status": run["checkpoint"]["status"],
                    "stage": run["checkpoint"]["stage"],
                }

            def advance(state):
                run = self.runtime.step(state["actor"], state["run_id"], cancel)
                return {
                    "revision": run["revision"],
                    "status": run["checkpoint"]["status"],
                    "stage": run["checkpoint"]["stage"],
                }

            def route(state):
                if state["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                    return END
                return {"model": "model", "tools": "tools", "inflight": "recover"}[state["stage"]]

            builder = StateGraph(StepState)
            builder.add_node("inspect", inspect)
            builder.add_edge(START, "inspect")
            builder.add_conditional_edges("inspect", route)
            for node in ("model", "tools", "recover"):
                builder.add_node(node, advance)
                builder.add_edge(node, "inspect" if continuous else END)
            graph = builder.compile()
            return graph.invoke(
                {"run_id": identity, "actor": actor, "revision": -1, "status": "", "stage": ""},
                {"recursion_limit": 1000},
            )

    def advance(self, actor, identity, cancel=None):
        return self._invoke(actor, identity, cancel, continuous=False)

    def run(self, actor, identity, cancel=None):
        self._invoke(actor, identity, cancel, continuous=True)
        return self.runtime.store.load(actor, identity)
