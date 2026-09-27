"""Bounded graph metric tests (M016)."""
from __future__ import annotations

import networkx as nx

from src.graph import connected_components, degree_metrics, local_pagerank, summarize


def _star(n: int):
    g = nx.Graph()
    for i in range(1, n + 1):
        g.add_edge(0, i, score=0.5)
    return g


def test_degree_and_components() -> None:
    g = _star(5)
    degrees = degree_metrics(g)
    assert degrees[0]["degree"] == 5
    assert degrees[1]["degree"] == 1
    assert connected_components(g) == [list(range(6))]
    summary = summarize(g, center=0)
    assert summary["nodes"] == 6 and summary["max_degree"] == 5 and summary["components"] == 1


def test_local_pagerank_is_bounded() -> None:
    g = _star(300)
    pr = local_pagerank(g, 0, max_nodes=50)
    assert len(pr) <= 50
    assert pr.get(0, 0) > 0


def test_empty_graph_is_safe() -> None:
    g = nx.Graph()
    assert summarize(g)["nodes"] == 0
    assert local_pagerank(g, 1) == {}
