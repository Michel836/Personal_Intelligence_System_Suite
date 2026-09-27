"""Canonical, bounded dimensionality reduction for the galaxy (M020).

The galaxy is a **2D exploratory projection**, never a literal map of semantic
distance. PCA (via a deterministic randomized SVD) is the dependable default and
works on the full corpus without an optional dependency. UMAP and t-SNE are
opt-in, availability-gated and bounded; t-SNE is refused above a small ceiling
because it is effectively O(N^2) and is easy to misuse on a large corpus.

No method is allowed to allocate an all-pairs matrix. The large-N path fits the
projection basis on a deterministic sample and transforms every vector, so cost
stays near O(N * dim) per projection.
"""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

#: Which methods are requested by name.
PROJECTION_METHODS = ("pca", "svd", "umap", "tsne")

PROJECTION_VERSION = "m020.1"

#: Above this many points the basis is fit on a deterministic sample.
FIT_CAP = 12_000
#: Hard ceilings for the optional, expensive methods.
TSNE_MAX = 2_000
UMAP_MAX = 20_000

LIMITATIONS = (
    "Coordinates are an exploratory 2D projection of a high-dimensional semantic "
    "space; distances are approximate and must not be read as literal semantic "
    "distance. PCA/SVD preserve global variance, UMAP/t-SNE primarily preserve "
    "local neighbourhoods, and a sample-fitted basis can shift with the sample."
)


class ProjectionError(ValueError):
    """Raised when a projection method is unavailable or unsafe for the input."""


@dataclass
class ProjectionResult:
    method: str
    version: str
    ids: list[int]
    coords: npt.NDArray[np.float64]  # shape (n, 2)
    explained_variance: list[float] = field(default_factory=list)
    sampled: bool = False
    fit_count: int = 0
    warnings: list[str] = field(default_factory=list)
    limitations: str = LIMITATIONS

    def __post_init__(self) -> None:
        coords = np.asarray(self.coords, dtype=np.float64)
        if coords.ndim != 2:
            coords = coords.reshape(-1, 2)
        self.coords = coords

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "version": self.version,
            "explained_variance": [round(float(v), 6) for v in self.explained_variance],
            "sampled": bool(self.sampled),
            "fit_count": int(self.fit_count),
            "input_count": len(self.ids),
            "warnings": list(self.warnings),
            "limitations": self.limitations,
        }

    def points(self) -> list[dict[str, Any]]:
        return [{"id": int(i), "x": round(float(x), 6), "y": round(float(y), 6)}
                for i, (x, y) in zip(self.ids, self.coords, strict=False)]


def _as_matrix(vectors: Any) -> npt.NDArray[np.float64]:
    matrix = np.asarray(vectors, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2:
        raise ProjectionError("vectors must be a 2D array")
    return np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)


def _randomized_svd(matrix: npt.NDArray[np.float64], n_components: int, *, seed: int,
                    n_iter: int = 4, oversample: int = 8) -> tuple[
                        npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Deterministic randomized SVD (no SciPy/sklearn dependency).

    Returns ``(U, s, Vt)`` with ``U`` shape (n, k), ``s`` (k,), ``Vt`` (k, dim).
    """
    n, dim = matrix.shape
    k = min(int(n_components), n, dim)
    if k <= 0:
        return np.zeros((n, 0)), np.zeros(0), np.zeros((0, dim))
    rng = np.random.default_rng(int(seed))
    size = min(dim, k + oversample)
    q = rng.standard_normal((dim, size))
    q, _ = np.linalg.qr(matrix @ q)
    for _ in range(max(0, int(n_iter))):
        q, _ = np.linalg.qr(matrix.T @ q)
        q, _ = np.linalg.qr(matrix @ q)
    b = q.T @ matrix
    u_hat, s, vt = np.linalg.svd(b, full_matrices=False)
    u = q @ u_hat
    return u[:, :k], s[:k], vt[:k]


def _pca(vectors: npt.NDArray[np.float64], *, seed: int, fit_cap: int) -> ProjectionResult:
    warned = False
    fit = vectors
    if len(vectors) > fit_cap:
        rng = np.random.default_rng(int(seed))
        idx = np.sort(rng.choice(len(vectors), size=fit_cap, replace=False))
        fit = vectors[idx]
        warned = True
    mean = fit.mean(axis=0, keepdims=True)
    centered_fit = fit - mean
    _, s, vt = _randomized_svd(centered_fit, 2, seed=seed)
    centered = vectors - mean
    coords = centered @ vt.T
    total = float(np.square(centered_fit).sum()) or 1.0
    explained = [float((s[i] ** 2) / total) for i in range(len(s))]
    warnings = []
    if warned:
        warnings.append("basis fitted on a deterministic sample")
    return ProjectionResult("pca", PROJECTION_VERSION, [], coords, explained,
                            sampled=False, fit_count=len(fit), warnings=warnings)


def _svd(vectors: npt.NDArray[np.float64], *, seed: int, fit_cap: int) -> ProjectionResult:
    warned = False
    fit = vectors
    if len(vectors) > fit_cap:
        rng = np.random.default_rng(int(seed))
        idx = np.sort(rng.choice(len(vectors), size=fit_cap, replace=False))
        fit = vectors[idx]
        warned = True
    _, s, vt = _randomized_svd(fit, 2, seed=seed)
    coords = vectors @ vt.T
    total = float(np.square(fit).sum()) or 1.0
    explained = [float((s[i] ** 2) / total) for i in range(len(s))]
    warnings = []
    if warned:
        warnings.append("basis fitted on a deterministic sample")
    return ProjectionResult("svd", PROJECTION_VERSION, [], coords, explained,
                            sampled=False, fit_count=len(fit), warnings=warnings)


def _umap(vectors: npt.NDArray[np.float64], *, seed: int) -> ProjectionResult:
    try:
        umap = importlib.import_module("umap")
    except Exception as exc:  # noqa: BLE001 - optional dependency
        raise ProjectionError("umap is not installed (optional)") from exc
    if len(vectors) > UMAP_MAX:
        raise ProjectionError(
            f"umap refused above {UMAP_MAX} points; use pca/svd or a smaller scope")
    reducer = umap.UMAP(n_components=2, random_state=int(seed), n_neighbors=15, min_dist=0.1)
    coords = np.asarray(reducer.fit_transform(vectors), dtype=np.float64)
    return ProjectionResult("umap", PROJECTION_VERSION, [], coords, [],
                            sampled=False, fit_count=len(vectors))


def _tsne(vectors: npt.NDArray[np.float64], *, seed: int) -> ProjectionResult:
    if len(vectors) > TSNE_MAX:
        raise ProjectionError(
            f"t-SNE refused above {TSNE_MAX} points (it is effectively O(N^2)); "
            "use pca/svd or a bounded scope")
    try:
        tsne_cls = importlib.import_module("sklearn.manifold").TSNE
    except Exception as exc:  # noqa: BLE001 - optional dependency
        raise ProjectionError("scikit-learn is required for t-SNE") from exc
    coords = np.asarray(
        tsne_cls(n_components=2, perplexity=min(30.0, max(5.0, (len(vectors) - 1) / 3.0)),
                 random_state=int(seed), init="pca", learning_rate="auto").fit_transform(vectors),
        dtype=np.float64)
    return ProjectionResult("tsne", PROJECTION_VERSION, [], coords, [],
                            sampled=False, fit_count=len(vectors),
                            warnings=["t-SNE is exploratory only and non-deterministic "
                                      "across library versions"])


def available_methods() -> dict[str, dict[str, Any]]:
    """Report which projection methods can run in this environment."""
    have_umap = importlib.util.find_spec("umap") is not None
    have_sklearn = importlib.util.find_spec("sklearn") is not None
    return {
        "pca": {"available": True, "max_points": None, "deterministic": True,
                "note": "primary/fallback; randomized SVD"},
        "svd": {"available": True, "max_points": None, "deterministic": True,
                "note": "uncentered PCA variant"},
        "umap": {"available": have_umap, "max_points": UMAP_MAX, "deterministic": True,
                 "note": "optional; local neighbourhood structure"},
        "tsne": {"available": have_sklearn, "max_points": TSNE_MAX,
                 "deterministic": False, "note": "small exploratory sets only"},
    }


def project(ids: list[int], vectors: Any, *, method: str = "pca", seed: int = 0,
            fit_cap: int = FIT_CAP) -> ProjectionResult:
    """Project ``vectors`` to 2D, binding the returned ids to the coordinates."""
    method = (method or "pca").lower()
    if method not in PROJECTION_METHODS:
        raise ProjectionError(f"unknown projection method: {method}")
    matrix = _as_matrix(vectors)
    if matrix.shape[0] != len(ids):
        raise ProjectionError("ids/vectors length mismatch")
    if matrix.shape[0] == 0:
        return ProjectionResult(method, PROJECTION_VERSION, [], np.zeros((0, 2)))
    if matrix.shape[0] == 1:
        return ProjectionResult(method, PROJECTION_VERSION, list(ids), np.zeros((1, 2)),
                                [1.0], fit_count=1,
                                warnings=["a single point cannot be meaningfully projected"])
    if method == "pca":
        result = _pca(matrix, seed=seed, fit_cap=fit_cap)
    elif method == "svd":
        result = _svd(matrix, seed=seed, fit_cap=fit_cap)
    elif method == "umap":
        result = _umap(matrix, seed=seed)
    else:
        result = _tsne(matrix, seed=seed)
    result.ids = [int(i) for i in ids]
    result.coords = result.coords.reshape(len(ids), 2)
    return result
