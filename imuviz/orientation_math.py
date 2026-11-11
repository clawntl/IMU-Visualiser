"""Quaternion / Euler / rotation-matrix conversions used across the app.

Quaternions are always (w, x, y, z). Euler angles are roll/pitch/yaw in
degrees, applied in the same body-frame X-Y-Z convention the original
firmware/plotting code used.
"""

from __future__ import annotations

import math

import numpy as np


def normalize_quat(w: float, x: float, y: float, z: float) -> np.ndarray:
    q = np.array([w, x, y, z], dtype=float)
    n = np.linalg.norm(q)
    if n < 1e-9:
        return np.array([1.0, 0.0, 0.0, 0.0])
    return q / n


def quat_to_rotation_matrix(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
        [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
        [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y],
    ])


def quat_to_euler_deg(q: np.ndarray) -> tuple[float, float, float]:
    """Roll (X), pitch (Y), yaw (Z), matching the R = Rz(yaw)@Ry(pitch)@Rx(roll)
    convention used by quat_to_rotation_matrix / euler_deg_to_rotation_matrix.

    Note: pitch must come from asin, not atan2 with the roll/yaw-style
    denominator -- that shortcut (present in the original version of this
    project) silently drifts as pitch grows away from zero.
    """
    w, x, y, z = q

    roll = math.atan2(2 * (w * x + y * z), w * w - x * x - y * y + z * z)
    sin_pitch = max(-1.0, min(1.0, 2 * (w * y - x * z)))
    pitch = math.asin(sin_pitch)
    yaw = math.atan2(2 * (x * y + w * z), w * w + x * x - y * y - z * z)

    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


def euler_deg_to_rotation_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    rx, ry, rz = math.radians(roll), math.radians(pitch), math.radians(yaw)

    Rx = np.array([
        [1, 0, 0],
        [0, math.cos(rx), -math.sin(rx)],
        [0, math.sin(rx), math.cos(rx)],
    ])
    Ry = np.array([
        [math.cos(ry), 0, math.sin(ry)],
        [0, 1, 0],
        [-math.sin(ry), 0, math.cos(ry)],
    ])
    Rz = np.array([
        [math.cos(rz), -math.sin(rz), 0],
        [math.sin(rz), math.cos(rz), 0],
        [0, 0, 1],
    ])

    return Rz @ Ry @ Rx


def euler_deg_to_quat(roll: float, pitch: float, yaw: float) -> np.ndarray:
    rx, ry, rz = math.radians(roll) / 2, math.radians(pitch) / 2, math.radians(yaw) / 2

    cr, sr = math.cos(rx), math.sin(rx)
    cp, sp = math.cos(ry), math.sin(ry)
    cy, sy = math.cos(rz), math.sin(rz)

    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy

    return normalize_quat(w, x, y, z)


AXIS_VECTORS = {
    "+X": np.array([1.0, 0.0, 0.0]),
    "-X": np.array([-1.0, 0.0, 0.0]),
    "+Y": np.array([0.0, 1.0, 0.0]),
    "-Y": np.array([0.0, -1.0, 0.0]),
    "+Z": np.array([0.0, 0.0, 1.0]),
    "-Z": np.array([0.0, 0.0, -1.0]),
}


def build_axis_remap_matrix(x_src: str, y_src: str, z_src: str) -> np.ndarray | None:
    """Builds the fixed rotation matrix M that maps sensor-frame axes to the
    visualiser's display frame, given which sensor axis (e.g. "+Y") should
    appear as each display axis. Returns None if the three choices don't
    form a valid right-handed orthogonal basis (e.g. two axes the same).

    Apply as R_display = M @ R_sensor @ M.T (a similarity transform), which
    corrects both the resting pose and the rotation dynamics for a sensor
    mounted sideways/upside-down/rotated relative to the visualised body.
    """
    M = np.array([AXIS_VECTORS[x_src], AXIS_VECTORS[y_src], AXIS_VECTORS[z_src]])

    if not np.allclose(M @ M.T, np.eye(3), atol=1e-6):
        return None
    if not np.isclose(np.linalg.det(M), 1.0, atol=1e-6):
        return None

    return M


def rotation_matrix_to_quat(R: np.ndarray) -> np.ndarray:
    m = R
    tr = m[0, 0] + m[1, 1] + m[2, 2]

    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s

    return normalize_quat(w, x, y, z)
