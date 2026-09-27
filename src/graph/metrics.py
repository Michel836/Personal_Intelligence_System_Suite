"""Bounded graph metrics (M016).

All metrics run on the *bounded* neighborhood returned by the relation service,
never over the whole corpus. No accidental O(N^2), no expensive whole-corpus
centrality.
"""
from __future__ import annotations

from typing import Any


def to_networkx(neighborhood: dict[str, Any]) -> Any:
    import networkx as nx  # type: ignore[import-untyped]

    graph = nx.DiGraph()
    for node in neighborhood.get("nodes", []):
        graph.add_node(int(node["id"]), **{k: v for k, v in node.items() if k != "id"})
    for edge in neighborhood.get("edges", []):
        graph.add_edge(int(edge["source"]), int(edge["target"]),
                       type=edge.get("type"), score=float(edge.get("score") or 0.0),
                       evidence=edge.get("evidence"), directed=edge.get("directed", False))
    return graph


def degree_metrics(graph: Any) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for node in graph.nodes():
        out[int(node)] = {"degree": float(graph.degree(node)),
                          "weighted_degree": float(sum(
                              graph[u][v].get("score", 0.0) for u, v in graph.edges(node)))}
    return out


def connected_components(graph: Any) -> list[list[int]]:
    import networkx as nx
    undirected = graph.to_undirected() if graph.is_directed() else graph
    return [sorted(int(n) for n in comp) for comp in nx.connected_components(undirected)]


def local_pagerank(graph: Any, center: int, *, alpha: float = 0.85, iterations: int = 30,
                   max_nodes: int = 200) -> dict[int, float]:
    """PageRank on the bounded subgraph only (safe for small neighborhoods)."""
    import networkx as nx
    if graph.number_of_nodes() > max_nodes:
        # Keep the bounded subgraph around the center.
        nodes = [center] + [n for n in graph.nodes() if n != center][: max_nodes - 1]
        graph = graph.subgraph(nodes).copy()
    if graph.number_of_nodes() == 0 or center not in graph:
        return {}
    try:
        pr = nx.pagerank(graph.to_undirected(), alpha=alpha, max_iter=max(iterations, 100), tol=1e-4)
    except Exception:
        # Fall back to a cheap bounded degree centrality if PageRank does not
        # converge on the small subgraph.
        pr = nx.degree_centrality(graph.to_undirected())
    return {int(k): round(float(v), 6) for k, v in pr.items()}


def summarize(graph: Any, *, center: int | None = None) -> dict[str, Any]:
    if graph.number_of_nodes() == 0:
        return {"nodes": 0, "edges": 0, "components": 0, "max_degree": 0,
                "center_degree": 0, "center_pagerank": 0.0}
    degrees = [d for _, d in graph.degree()]
    out = {"nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
           "components": len(connected_components(graph)), "max_degree": int(max(degrees)),
           "mean_degree": round(sum(degrees) / len(degrees), 3)}
    if center is not None and center in graph:
        pr = local_pagerank(graph, center)
        out["center_degree"] = int(graph.degree(center))
        out["center_pagerank"] = pr.get(int(center), 0.0)
    return out
