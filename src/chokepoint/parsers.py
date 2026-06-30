"""Parsers — programmable classifiers you place on a node to decode raw alerts.

Real pipelines don't receive neatly typed events; they receive *raw* logs and
have to parse them into structured, typed alerts before anything can route or
consume them. That's this device: a ``raw`` packet carries a hidden ``payload``
(the concrete kind it really is), and a parser placed on its node *decodes* it —
retyping the packet to its payload kind so the right turret can finally serve it.

The lesson mirrors consumer coverage: a parser only handles the payload kinds it
``handles``. A raw alert whose payload no placed parser can decode never becomes
typed — it flows on and leaks at the sink. So you need parse-coverage over the
raw formats you ingest, just like you need consumer-coverage over typed kinds.

Pure data + a membership test; placement (x/y -> a node) and cost are handled by
the simulation/economy, exactly like gates and quelimiters.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field

DEFAULT_PARSER_COST = 90

# the kind given to an unparsed alert; no turret accepts it — only a parser
# can turn it into its payload kind. Kept here so the device owns the contract.
RAW_KIND = "raw"


@dataclass
class Parser:
    """Decodes raw alerts whose payload is one of the kinds it ``handles``."""

    x: float
    y: float
    # author code may pass a set/list/tuple; normalized to a frozenset in __post_init__
    handles: Collection[str] = field(default_factory=frozenset)
    cost: int = DEFAULT_PARSER_COST
    node: str = ""        # node it sits on (assigned by the simulation)
    id: str = ""          # assigned by the simulation

    def __post_init__(self) -> None:
        if not isinstance(self.handles, frozenset):
            self.handles = frozenset(self.handles)

    def can_parse(self, payload: str) -> bool:
        """True if this parser knows how to decode a raw alert of ``payload``."""
        return payload in self.handles
