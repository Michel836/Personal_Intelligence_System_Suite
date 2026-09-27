"""Bounded, scalable clustering for the galaxy (M020).

Clusters are similarity groups, not ground-truth categories. The default is
MiniBatchKMeans (or a deterministic NumPy fallback) because it is linear in the
number of documents and never allocates an all-pairs distance matrix. HDBSCAN is
used only when installed; DBSCAN is refused above a small ceiling because it is
O(N^2) in the worst case. ``-1`` is reserved for UNCLUSTERED / NOISE.

Nothing here equates a cluster with a "topic": topics are derived separately from
cluster evidence in :mod:`src.galaxy.topics`.
"""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np
import numpy.typing as npt

CLUSTERING_VERSION = "m020.1"
NOISE = -1

#: Hard ceilings. DBSCAN builds a neighbourhood graph and is unsafe at scale.
DBSCAN_MAX = 5_000
#: Above this many vectors, k-selection and quality metrics run on a sample.
METRIC_SAMPLE = 2_000
#: Deterministic seeded subset used to fit the k-selection estimator.
SELECT_SAMPLE = 4_000

ALGORITHMS = ("minibatch-kmeans", "kmeans", "hdbscan", "dbscan")


class ClusteringError(ValueError):
    """Raised for unavailable algorithms or unsafe parameter combinations."""


@dataclass
class ClusterResult:
    algorithm: str
    version: str
    labels: npt.NDArray[np.int64]  # shape (n,), -1 == noise
    centroids: npt.NDArray[np.float64]  # shape (k, dim)
    k: int
    input_count: int
    seed: int
    quality: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.labels = np.asarray(self.labels, dtype=np.int64).reshape(-1)
        self.centroids = np.asarray(self.centroids, dtype=np.float64)

    @property
    def noise_count(self) -> int:
        return int(np.sum(self.labels == NOISE))

    def sizes(self) -> dict[int, int]:
        sizes: dict[int, int] = {}
        for label in self.labels.tolist():
            sizes[int(label)] = sizes.get(int(label), 0) + 1
        return sizes

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "version": self.version,
            "k": int(self.k),
            "input_count": int(self.input_count),
            "noise_count": self.noise_count,
            "seed": int(self.seed),
            "params": dict(self.params),
            "quality": dict(self.quality),
            "warnings": list(self.warnings),
            "sizes": {str(k): v for k, v in sorted(self.sizes().items())},
        }


def _as_matrix(vectors: Any) -> npt.NDArray[np.float64]:
    matrix = np.asarray(vectors, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2:
        raise ClusteringError("vectors must be a 2D array")
    return cast(npt.NDArray[np.float64], np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0))


def _l2(matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return cast(npt.NDArray[np.float64], matrix / norms)


def available_algorithms() -> dict[str, dict[str, Any]]:
    have_hdbscan = importlib.util.find_spec("hdbscan") is not None
    have_sklearn = importlib.util.find_spec("sklearn") is not None
    return {
        "minibatch-kmeans": {"available": True, "max_points": None,
                             "backend": "sklearn" if have_sklearn else "numpy",
                             "noise": False},
        "kmeans": {"available": True, "max_points": None,
                   "backend": "sklearn" if have_sklearn else "numpy", "noise": False},
        "hdbscan": {"available": have_hdbscan, "max_points": None, "noise": True,
                    "note": "optional dependency"},
        "dbscan": {"available": have_sklearn, "max_points": DBSCAN_MAX, "noise": True,
                   "note": "refused above the ceiling (effectively O(N^2))"},
    }


# --- pure NumPy fallbacks ----------------------------------------------------
def _kmeans_plusplus(matrix: npt.NDArray[np.float64], k: int,
                    rng: np.random.Generator) -> npt.NDArray[np.float64]:
    n, dim = matrix.shape
    k = max(1, min(k, n))
    centers = np.empty((k, dim), dtype=np.float64)
    first = int(rng.integers(0, n))
    centers[0] = matrix[first]
    closest = np.sum((matrix - centers[0]) ** 2, axis=1)
    for i in range(1, k):
        total = float(closest.sum())
        if total <= 0.0:
            centers[i] = matrix[int(rng.integers(0, n))]
        else:
            probs = closest / total
            centers[i] = matrix[int(rng.choice(n, p=probs))]
        closest = np.minimum(closest, np.sum((matrix - centers[i]) ** 2, axis=1))
    return centers


def _assign(matrix: npt.NDArray[np.float64],
            centers: npt.NDArray[np.float64]) -> tuple[npt.NDArray[np.int64], float]:
    # (n, k) distances without an all-pairs (n, n) matrix.
    sq = (np.square(matrix).sum(axis=1)[:, None]
          + np.square(centers).sum(axis=1)[None, :]
          - 2.0 * matrix @ centers.T)
    np.maximum(sq, 0.0, out=sq)
    labels = np.argmin(sq, axis=1)
    inertia = float(np.take_along_axis(sq, labels[:, None], axis=1).sum())
    return labels, inertia


def _numpy_kmeans(matrix: npt.NDArray[np.float64], k: int, *, seed: int,
                  max_iter: int = 100) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], float]:
    rng = np.random.default_rng(int(seed))
    centers = _kmeans_plusplus(matrix, k, rng)
    labels = np.zeros(len(matrix), dtype=np.int64)
    inertia = 0.0
    for _ in range(max(1, int(max_iter))):
        labels, inertia = _assign(matrix, centers)
        new_centers = np.zeros_like(centers)
        for c in range(len(centers)):
            members = matrix[labels == c]
            if len(members):
                new_centers[c] = members.mean(axis=0)
            else:
                new_centers[c] = matrix[int(rng.integers(0, len(matrix)))]
        if np.allclose(new_centers, centers, atol=1e-6):
            centers = new_centers
            break
        centers = new_centers
    labels, inertia = _assign(matrix, centers)
    return labels, centers, float(inertia)


def _numpy_minibatch(matrix: npt.NDArray[np.float64], k: int, *, seed: int, batch_size: int = 1024,
                     max_iter: int = 50) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], float]:
    rng = np.random.default_rng(int(seed))
    centers = _kmeans_plusplus(matrix, k, rng)
    counts = np.zeros(k, dtype=np.float64)
    n = len(matrix)
    batch = max(64, min(int(batch_size), n))
    for _ in range(max(1, int(max_iter))):
        idx = rng.choice(n, size=batch, replace=False)
        points = matrix[idx]
        sq = (np.square(points).sum(axis=1)[:, None]
              + np.square(centers).sum(axis=1)[None, :]
              - 2.0 * points @ centers.T)
        labels = np.argmin(sq, axis=1)
        for c in range(k):
            members = points[labels == c]
            if not len(members):
                continue
            counts[c] += len(members)
            rate = 1.0 / counts[c]
            centers[c] = (1.0 - rate) * centers[c] + rate * members.mean(axis=0)
    labels, inertia = _assign(matrix, centers)
    return labels, centers, float(inertia)


# --- quality metrics ---------------------------------------------------------
def _silhouette(matrix: npt.NDArray[np.float64], labels: npt.NDArray[np.int64],
                *, sample: int = METRIC_SAMPLE, seed: int = 0) -> float | None:
    unique = np.unique(labels)
    unique = unique[unique != NOISE]
    if len(unique) < 2 or len(unique) >= len(labels):
        return None
    n = len(matrix)
    if n > sample:
        rng = np.random.default_rng(int(seed))
        idx = rng.choice(n, size=sample, replace=False)
        matrix = matrix[idx]
        labels = labels[idx]
    # Cosine distance matrix on a bounded sample (O(sample^2), sample<=2000).
    norm = _l2(matrix)
    dist = 1.0 - norm @ norm.T
    np.fill_diagonal(dist, 0.0)
    scores: list[float] = []
    for i in range(len(matrix)):
        same = labels == labels[i]
        same[i] = False
        if not same.any():
            continue
        others = [c for c in np.unique(labels) if c != labels[i] and c != NOISE]
        if not others:
            continue
        a = float(dist[i][same].mean())
        b = min(float(dist[i][labels == c].mean()) for c in others if (labels == c).any())
        denom = max(a, b)
        if denom > 0:
            scores.append((b - a) / denom)
    return float(np.mean(scores)) if scores else None


def cohesion(vectors: Any, labels: Any, centroids: Any) -> float | None:
    """Mean cosine similarity of points to their assigned centroid."""
    matrix = _as_matrix(vectors)
    labels = np.asarray(labels, dtype=np.int64)
    centroids = np.asarray(centroids, dtype=np.float64)
    if matrix.shape[0] == 0 or centroids.shape[0] == 0:
        return None
    norm = _l2(matrix)
    cnorm = _l2(centroids)
    valid = (labels >= 0) & (labels < len(centroids))
    if not valid.any():
        return None
    sims = np.sum(norm[valid] * cnorm[labels[valid]], axis=1)
    return float(np.mean(sims))


def adjusted_rand_index(a: Any, b: Any) -> float:
    """Adjusted Rand index without SciPy/sklearn (noise labels are comparable)."""
    a = np.asarray(a, dtype=np.int64)
    b = np.asarray(b, dtype=np.int64)
    if a.shape != b.shape or len(a) == 0:
        raise ClusteringError("label arrays must have the same non-zero length")
    _, ai = np.unique(a, return_inverse=True)
    _, bi = np.unique(b, return_inverse=True)
    n = len(a)
    # Contingency table.
    table = np.zeros((ai.max() + 1, bi.max() + 1), dtype=np.float64)
    np.add.at(table, (ai, bi), 1.0)
    def comb2(x: npt.NDArray[np.float64]) -> float:
        return float(np.sum(x * (x - 1.0) / 2.0))
    sum_ij = comb2(table)
    sum_i = comb2(table.sum(axis=1))
    sum_j = comb2(table.sum(axis=0))
    total = comb2(np.array([float(n)]))
    expected = (sum_i * sum_j / total) if total else 0.0
    maximum = 0.5 * (sum_i + sum_j)
    denom = maximum - expected
    if abs(denom) < 1e-12:
        return 1.0
    return float((sum_ij - expected) / denom)


# --- dispatch ----------------------------------------------------------------
def _cluster_sklearn(matrix: npt.NDArray[np.float64], algorithm: str, k: int, *, seed: int,
                     max_iter: int) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], float, list[str]]:
    sk = importlib.import_module("sklearn.cluster")
    if algorithm == "minibatch-kmeans":
        model = sk.MiniBatchKMeans(
            n_clusters=k, random_state=int(seed), n_init=5,
            batch_size=min(4096, max(256, len(matrix) // 100 + 1)),
            max_iter=max(10, int(max_iter)))
    else:
        model = sk.KMeans(n_clusters=k, random_state=int(seed), n_init=5,
                          max_iter=max(10, int(max_iter)))
    labels = np.asarray(model.fit_predict(matrix), dtype=np.int64)
    centers = np.asarray(model.cluster_centers_, dtype=np.float64)
    inertia = float(getattr(model, "inertia_", 0.0))
    return labels, centers, inertia, []


def _cluster_hdbscan(matrix: npt.NDArray[np.float64], *, min_cluster_size: int,
                     min_samples: int | None) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], float, list[str]]:
    hdbscan = importlib.import_module("hdbscan")
    model = hdbscan.HDBSCAN(min_cluster_size=max(2, int(min_cluster_size)),
                            min_samples=min_samples)
    labels = np.asarray(model.fit_predict(matrix), dtype=np.int64)
    k = int(labels.max()) + 1 if len(labels) else 0
    centers = _centroids_from_labels(matrix, labels, max(k, 0))
    if len(centers):
        _, inertia = _assign(matrix, centers)
    else:
        inertia = 0.0
    return labels, centers, float(inertia), []


def _cluster_dbscan(matrix: npt.NDArray[np.float64], *, eps: float,
                    min_samples: int) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], float, list[str]]:
    if len(matrix) > DBSCAN_MAX:
        raise ClusteringError(
            f"dbscan refused above {DBSCAN_MAX} points (effectively O(N^2))")
    sk = importlib.import_module("sklearn.cluster")
    model = sk.DBSCAN(eps=float(eps), min_samples=max(2, int(min_samples)))
    labels = np.asarray(model.fit_predict(matrix), dtype=np.int64)
    k = int(labels.max()) + 1 if len(labels) else 0
    centers = _centroids_from_labels(matrix, labels, max(k, 0))
    _, inertia = _assign(matrix, centers) if len(centers) else (labels, np.float64(0.0))
    return labels, centers, float(inertia), ["dbscan on a bounded set only"]


def _centroids_from_labels(matrix: npt.NDArray[np.float64], labels: npt.NDArray[np.int64],
                           k: int) -> npt.NDArray[np.float64]:
    if k <= 0:
        return np.zeros((0, matrix.shape[1]), dtype=np.float64)
    centers = np.zeros((k, matrix.shape[1]), dtype=np.float64)
    for c in range(k):
        members = matrix[labels == c]
        if len(members):
            centers[c] = members.mean(axis=0)
    return centers


def cluster(vectors: Any, *, algorithm: str = "minibatch-kmeans", k: int = 12,
            seed: int = 0, max_iter: int = 50, min_cluster_size: int = 15,
            min_samples: int | None = None, eps: float = 0.35) -> ClusterResult:
    """Cluster ``vectors`` with an explicit, recorded algorithm/parameter set."""
    algorithm = (algorithm or "minibatch-kmeans").lower()
    if algorithm not in ALGORITHMS:
        raise ClusteringError(f"unknown clustering algorithm: {algorithm}")
    matrix = _as_matrix(vectors)
    n = len(matrix)
    warnings: list[str] = []
    if n == 0:
        return ClusterResult(algorithm, CLUSTERING_VERSION, np.zeros(0, dtype=np.int64),
                             np.zeros((0, 0)), 0, 0, seed, params={"k": int(k)})
    if algorithm == "dbscan" and n > DBSCAN_MAX:
        raise ClusteringError(f"dbscan refused above {DBSCAN_MAX} points")
    if algorithm in ("minibatch-kmeans", "kmeans"):
        if n < 2:
            return ClusterResult(algorithm, CLUSTERING_VERSION, np.zeros(n, dtype=np.int64),
                                 _as_matrix(matrix), min(1, n), n, seed,
                                 params={"k": 1}, warnings=["too few points to cluster"])
        k = max(1, min(int(k), n))
        try:
            labels, centers, inertia, warns = _cluster_sklearn(matrix, algorithm, k, seed=seed,
                                                               max_iter=max_iter)
        except Exception:  # noqa: BLE001 - sklearn optional
            if algorithm == "minibatch-kmeans":
                labels, centers, inertia = _numpy_minibatch(matrix, k, seed=seed)
            else:
                labels, centers, inertia = _numpy_kmeans(matrix, k, seed=seed)
            warns = ["scikit-learn unavailable; NumPy fallback used"]
        warnings.extend(warns)
    elif algorithm == "hdbscan":
        labels, centers, inertia, warns = _cluster_hdbscan(
            matrix, min_cluster_size=min_cluster_size, min_samples=min_samples)
        warnings.extend(warns)
    else:
        labels, centers, inertia, warns = _cluster_dbscan(
            matrix, eps=eps, min_samples=min_samples or 5)
        warnings.extend(warns)

    sizes = np.bincount(labels[labels >= 0], minlength=len(centers)) if len(centers) else np.array([])
    quality: dict[str, Any] = {
        "inertia": round(float(inertia), 6),
        "cohesion": (round(c, 6) if (c := cohesion(matrix, labels, centers)) is not None else None),
        "silhouette_sample": (round(s, 6) if (s := _silhouette(matrix, labels, seed=seed)) is not None else None),
        "cluster_count": int(len(centers)),
        "noise_count": int(np.sum(labels == NOISE)),
        "largest_cluster": int(sizes.max()) if len(sizes) else 0,
        "smallest_cluster": int(sizes.min()) if len(sizes) else 0,
        "metric_sample_cap": METRIC_SAMPLE,
    }
    return ClusterResult(algorithm, CLUSTERING_VERSION, labels, centers,
                         int(len(centers)), n, int(seed), quality=quality,
                         params={"k": int(k), "max_iter": int(max_iter),
                                 "min_cluster_size": int(min_cluster_size),
                                 "min_samples": min_samples, "eps": float(eps)},
                         warnings=warnings)


def cluster_stability(vectors: Any, *, algorithm: str = "minibatch-kmeans", k: int = 12,
                      seeds: tuple[int, ...] = (0, 1), **kwargs: Any) -> dict[str, Any]:
    """Agreement (ARI) between independent seeds; a stability proxy, not a promise."""
    results = [cluster(vectors, algorithm=algorithm, k=k, seed=s, **kwargs) for s in seeds]
    if len(results) < 2:
        return {"ari": None, "seeds": list(seeds)}
    aris = [adjusted_rand_index(results[i].labels, results[i + 1].labels)
            for i in range(len(results) - 1)]
    return {"ari": round(float(np.mean(aris)), 6), "per_pair": [round(a, 6) for a in aris],
            "seeds": list(seeds)}


def select_k(vectors: Any, *, k_min: int = 4, k_max: int = 24, seed: int = 0,
             metric: str = "silhouette", sample: int = SELECT_SAMPLE,
             candidates: tuple[int, ...] | None = None) -> dict[str, Any]:
    """Evidence-based cluster count selection (silhouette sample + elbow proxy).

    Prefers interpretable/stable clustering over maximising a single metric: the
    silhouette winner is reported together with the inertia curve and the chosen
    rationale so a caller can override it transparently.
    """
    matrix = _as_matrix(vectors)
    n = len(matrix)
    if n < 2:
        return {"selected_k": 1, "scores": {}, "inertia": {}, "rationale": "too few points",
                "candidates": [1]}
    if n > sample:
        rng = np.random.default_rng(int(seed))
        idx = rng.choice(n, size=sample, replace=False)
        matrix = matrix[idx]
    k_min = max(2, int(k_min))
    k_max = max(k_min, int(k_max))
    k_max = min(k_max, max(2, len(matrix) - 1), 32)
    if candidates is None:
        step = max(1, (k_max - k_min) // 8)
        candidates = tuple(range(k_min, k_max + 1, step))
    scores: dict[str, float] = {}
    inertia: dict[str, float] = {}
    for k in candidates:
        result = cluster(matrix, algorithm="kmeans", k=k, seed=seed, max_iter=40)
        sil = _silhouette(matrix, result.labels, seed=seed)
        if sil is not None:
            scores[str(k)] = round(float(sil), 6)
        inertia[str(k)] = round(float(result.quality.get("inertia", 0.0)), 6)
    if metric == "silhouette" and scores:
        selected = int(max(scores, key=lambda key: (scores[key], -int(key))))
        rationale = "maximise silhouette on a deterministic sample"
    else:
        # Elbow proxy: largest second-difference drop in inertia.
        selected = min(candidates)
        rationale = "elbow proxy on inertia"
        keys = sorted(inertia, key=int)
        if len(keys) >= 3:
            drops = [inertia[keys[i]] - inertia[keys[i + 1]] for i in range(len(keys) - 1)]
            best = max(range(len(drops) - 1), key=lambda i: drops[i] - drops[i + 1], default=0)
            selected = int(keys[best])
    return {"selected_k": int(selected), "scores": scores, "inertia": inertia,
            "rationale": rationale, "candidates": [int(c) for c in candidates],
            "sample": len(matrix), "metric": metric}
