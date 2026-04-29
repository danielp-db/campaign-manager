"""Pydantic models for the no-code DAG."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NodeType = Literal["source_uc", "source_file", "filter", "derive", "join", "sink"]
JoinSide = Literal["left", "right"]


class Node(BaseModel):
    id: str = Field(..., min_length=1)
    type: NodeType
    label: str = ""
    config: dict = Field(default_factory=dict)


class Edge(BaseModel):
    source: str
    target: str
    side: JoinSide | None = None


class Dag(BaseModel):
    nodes: list[Node]
    edges: list[Edge]

    def by_id(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"node not found: {node_id}")

    def parents(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]

    def children(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]
