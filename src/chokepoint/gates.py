"""Gates — typed routers placed at a branching node.

A gate is the pre-filter / router of the pipeline: at a fork it decides which
branch each alert kind goes down, so expensive consumers only ever see the
traffic meant for them. That's the Lambda event-source filter / EventBridge
rule / SNS filter-policy idea — route by type instead of fanning everything
everywhere.

Pure data + a routing decision; no pygame, no network. Placement (x/y -> a
branching node) and cost are handled like turrets, by the simulation/economy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_GATE_COST = 80


@dataclass
class Gate:
    """Routes kinds among a node's outgoing branches by index.

    ``routes`` maps a kind to a branch index (0-based, into the node's outgoing
    edges); anything not listed falls through to ``default_branch``.
    """

    x: float
    y: float
    routes: dict[str, int] = field(default_factory=dict)
    default_branch: int = 0
    cost: int = DEFAULT_GATE_COST
    node: str = ""        # branching node it sits on (assigned by the simulation)
    id: str = ""          # assigned by the simulation

    def branch_for(self, kind: str, n_branches: int) -> int:
        """Which outgoing branch this kind takes, clamped to a valid index."""
        idx = self.routes.get(kind, self.default_branch)
        return idx if 0 <= idx < n_branches else 0
