"""Facade for the M016 timeline, relationship graph and prioritization layer.

Uses the existing SQLite tables and (optionally) NetworkX/Plotly already in the
environment. No separate graph database and no parallel relationship model.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .metrics import summarize, to_networkx
from .priority import compute_priority, rank_documents
from .relations import RelationService
from .timeline import TimelineService


class DocumentGraph:
    def __init__(self, db: Any, *, relation_service: RelationService | None = None,
                 intel_store: Any = None, dedup_store: Any = None, tag_manager: Any = None) -> None:
        self.db = db
        self.relations = relation_service or RelationService(
            db, dedup_store=dedup_store, intel_store=intel_store, tag_manager=tag_manager)
        self.timeline = TimelineService(db, intel_store=intel_store)

    def neighborhood(self, file_id: int, *, types: Iterable[str] | None = None,
                     depth: int = 1, max_nodes: int = 50, max_edges: int = 120,
                     semantic: bool = False, with_metrics: bool = True) -> dict[str, Any]:
        result = self.relations.neighborhood(file_id, types=types, depth=depth,
                                             max_nodes=max_nodes, max_edges=max_edges,
                                             semantic=semantic)
        if with_metrics:
            graph = to_networkx(result)
            result["metrics"] = summarize(graph, center=int(file_id))
        result["bounds"] = {"depth": min(max(1, depth), 2), "max_nodes": max_nodes,
                            "max_edges": max_edges}
        return result

    def entity_graph(self, **kwargs: Any) -> dict[str, Any]:
        return self.relations.entity_graph(**kwargs)

    def priority(self, file_id: int, **kwargs: Any) -> dict[str, Any]:
        degree = None
        try:
            graph = to_networkx(self.relations.neighborhood(
                file_id, max_nodes=30, max_edges=60, semantic=False))
            degree = graph.degree(int(file_id)) if int(file_id) in graph else 0
        except Exception:
            degree = None
        return compute_priority(self.db, file_id, relation_service=self.relations,
                                degree=degree, **kwargs)

    def rank(self, file_ids: list[int], **kwargs: Any) -> list[dict[str, Any]]:
        return rank_documents(self.db, file_ids, relation_service=self.relations, **kwargs)

    def timeline_events(self, **kwargs: Any) -> dict[str, Any]:
        return self.timeline.events(**kwargs)


def plotly_network(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *,
                   max_nodes: int = 120) -> Any:
    """Build a bounded Plotly network figure (spring layout)."""
    try:
        import networkx as nx  # type: ignore[import-untyped]
        import plotly.graph_objects as go  # type: ignore[import-untyped]
    except Exception:
        return None
    nodes = nodes[:max_nodes]
    keep = {int(n["id"]) for n in nodes}
    edges = [e for e in edges if int(e["source"]) in keep and int(e["target"]) in keep]
    graph = nx.Graph()
    for n in nodes:
        graph.add_node(int(n["id"]), label=n.get("filename") or str(n["id"]))
    for e in edges:
        graph.add_edge(int(e["source"]), int(e["target"]))
    if graph.number_of_nodes() == 0:
        return None
    pos = nx.spring_layout(graph, k=0.6, iterations=30, seed=7)
    edge_x, edge_y = [], []
    for u, v in graph.edges():
        edge_x += [pos[u][0], pos[v][0], None]
        edge_y += [pos[u][1], pos[v][1], None]
    node_x = [pos[n][0] for n in graph.nodes()]
    node_y = [pos[n][1] for n in graph.nodes()]
    labels = [graph.nodes[n].get("label", str(n)) for n in graph.nodes()]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                             line={"width": 1, "color": "#888"}, hoverinfo="none"))
    fig.add_trace(go.Scatter(x=node_x, y=node_y, mode="markers+text", text=labels,
                             textposition="top center", textfont={"size": 8},
                             marker={"size": 10}))
    fig.update_layout(showlegend=False, margin={"l": 10, "r": 10, "t": 10, "b": 10},
                      xaxis={"visible": False}, yaxis={"visible": False}, height=520)
    return fig
