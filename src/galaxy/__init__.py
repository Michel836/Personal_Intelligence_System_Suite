"""Bounded corpus-navigation and discovery layer (M020).

A mono-user, local-only exploratory layer over the canonical SQLite corpus and
embedding store: a 2D semantic galaxy, scalable clustering, interpretable topics,
semantic neighbourhoods and contextual document exploration. SQLite stays
canonical; nothing is sent off the machine and no second corpus database is
created. Projections and clusters are derived, bounded and rebuildable.
"""
from __future__ import annotations

from .clustering import (
    ALGORITHMS,
    CLUSTERING_VERSION,
    NOISE,
    ClusteringError,
    ClusterResult,
    adjusted_rand_index,
    available_algorithms,
    cluster,
    cluster_stability,
    cohesion,
    select_k,
)
from .projection import (
    PROJECTION_METHODS,
    PROJECTION_VERSION,
    ProjectionError,
    ProjectionResult,
    available_methods,
    project,
)
from .service import (
    MEDIUM_MAX,
    POINT_LIMITS,
    SCOPE_KINDS,
    SMALL_MAX,
    GalaxyError,
    GalaxyService,
    describe_stack,
    detect_store,
    scale_tier,
)
from .store import (
    SCHEMA_VERSION,
    GalaxyStore,
    freshness_signature,
    new_run_id,
    vector_namespace,
)
from .text import STOPWORDS, ctfidf_terms, is_safe_term, tfidf_terms, tokenize
from .topics import TOPIC_VERSION, Topic, build_topics, label_from_evidence

__all__ = [
    "ALGORITHMS", "CLUSTERING_VERSION", "NOISE", "ClusterResult", "ClusteringError",
    "adjusted_rand_index", "available_algorithms", "cluster", "cluster_stability",
    "cohesion", "select_k",
    "PROJECTION_METHODS", "PROJECTION_VERSION", "ProjectionError", "ProjectionResult",
    "available_methods", "project",
    "POINT_LIMITS", "SCOPE_KINDS", "SMALL_MAX", "MEDIUM_MAX", "GalaxyError",
    "GalaxyService", "describe_stack", "detect_store", "scale_tier",
    "SCHEMA_VERSION", "GalaxyStore", "freshness_signature", "new_run_id",
    "vector_namespace",
    "STOPWORDS", "ctfidf_terms", "is_safe_term", "tfidf_terms", "tokenize",
    "TOPIC_VERSION", "Topic", "build_topics", "label_from_evidence",
]
