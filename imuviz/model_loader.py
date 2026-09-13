"""Loads user-supplied 3D models (STL/OBJ) into plain vertex/face arrays,
centered on their centroid and scaled to a consistent visual size."""

from __future__ import annotations

import numpy as np


class ModelLoadError(Exception):
    pass


def load_mesh(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Returns (vertices Nx3 float32, faces Mx3 int32), normalized to fit
    roughly within a 2-unit bounding box and centered at the origin."""

    lower = path.lower()
    if lower.endswith(".stl"):
        vertices, faces = _load_stl(path)
    elif lower.endswith(".obj"):
        vertices, faces = _load_obj(path)
    else:
        raise ModelLoadError(f"Unsupported model format: {path}")

    if len(vertices) == 0 or len(faces) == 0:
        raise ModelLoadError("Model contains no usable geometry")

    return _normalize(vertices, faces)


def _load_stl(path: str) -> tuple[np.ndarray, np.ndarray]:
    from stl import mesh as stl_mesh

    m = stl_mesh.Mesh.from_file(path)
    # m.vectors is (n_triangles, 3, 3) -- each triangle has its own verts.
    tris = m.vectors.reshape(-1, 3).astype(np.float64)
    vertices, inverse = np.unique(tris, axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3)
    return vertices, faces


def _load_obj(path: str) -> tuple[np.ndarray, np.ndarray]:
    vertices: list[list[float]] = []
    faces: list[list[int]] = []

    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("v "):
                parts = line.split()[1:4]
                vertices.append([float(p) for p in parts])

            elif line.startswith("f "):
                tokens = line.split()[1:]
                idxs = [int(tok.split("/")[0]) for tok in tokens]
                idxs = [i - 1 if i > 0 else len(vertices) + i for i in idxs]
                # Fan-triangulate polygons with more than 3 vertices.
                for i in range(1, len(idxs) - 1):
                    faces.append([idxs[0], idxs[i], idxs[i + 1]])

    return np.array(vertices, dtype=np.float64), np.array(faces, dtype=np.int64)


def _normalize(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    centroid = vertices.mean(axis=0)
    centered = vertices - centroid

    extent = np.max(np.abs(centered))
    if extent < 1e-9:
        extent = 1.0

    scaled = centered / extent  # fits within [-1, 1] on the largest axis

    return scaled.astype(np.float32), faces.astype(np.int32)
