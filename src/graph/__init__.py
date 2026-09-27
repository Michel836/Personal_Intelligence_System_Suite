"""M016 timeline, relationship graph and explainable prioritization.

Builds on the existing canonical SQLite tables (M014 duplicates/versions,
M015 entities/categories/PII, archive members, tags/favorites) plus NetworkX/
Plotly already present. No separate graph database, no parallel relationship
model, and no inference of human/social relationships from co-occurrence.
"""
from __future__ import annotations

from .graph import DocumentGraph, plotly_network
from .metrics import (
    connected_components,
    degree_metrics,
    local_pagerank,
    summarize,
    to_networkx,
)
from .priority import compute_priority, rank_documents
from .relations import (
    ALL_TYPES,
    DEFAULT_NEIGHBORHOOD_TYPES,
    DIRECTED,
    OPTIONAL_TYPES,
    Relation,
    RelationService,
    RelationType,
)
from .timeline import DATE_SOURCES, TimelineEvent, TimelineService

__all__ = [
    "DocumentGraph", "plotly_network", "RelationService", "Relation", "RelationType",
    "DEFAULT_NEIGHBORHOOD_TYPES", "OPTIONAL_TYPES", "ALL_TYPES", "DIRECTED",
    "TimelineService", "TimelineEvent", "DATE_SOURCES",
    "compute_priority", "rank_documents",
    "to_networkx", "degree_metrics", "connected_components", "local_pagerank", "summarize",
]
