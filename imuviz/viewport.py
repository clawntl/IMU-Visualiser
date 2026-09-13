"""The live 3D view: a GPU-rendered (OpenGL, via pyqtgraph) scene showing
either a default IMU-board placeholder or a user-imported mesh, rotated in
real time by incoming orientation data."""

from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.shaders import FragmentShader, ShaderProgram, VertexShader

from .model_loader import load_mesh
from .orientation_math import euler_deg_to_rotation_matrix

# Front-face color, so the "front" of the default board is always visually
# obvious no matter how it's spun around. Body color is user-adjustable.
_DEFAULT_BODY_COLOR = (0.55, 0.62, 0.75, 1.0)
_FRONT_COLOR = (0.95, 0.35, 0.25, 1.0)

DEFAULT_BOARD_SIZE = (1.6, 1.0, 0.28)

# pyqtgraph's built-in 'shaded' shader floors brightness at 20% ambient,
# which is dark enough to nearly vanish against a dark background on faces
# angled away from the light. Same shading model, brighter floor, so
# smooth-shaded imported models stay visible from every angle/theme.
ShaderProgram("imu_shaded", [
    VertexShader("""
        uniform mat4 u_mvp;
        uniform mat3 u_normal;
        attribute vec4 a_position;
        attribute vec3 a_normal;
        attribute vec4 a_color;
        varying vec4 v_color;
        varying vec3 v_normal;
        void main() {
            v_normal = normalize(u_normal * a_normal);
            v_color = a_color;
            gl_Position = u_mvp * a_position;
        }
    """),
    FragmentShader("""
        #ifdef GL_ES
        precision mediump float;
        #endif
        varying vec4 v_color;
        varying vec3 v_normal;
        void main() {
            float p = dot(v_normal, normalize(vec3(1.0, -1.0, -1.0)));
            p = p < 0.0 ? 0.0 : p * 0.65;
            vec3 rgb = v_color.rgb * (0.4 + p);
            gl_FragColor = vec4(rgb, v_color.a);
        }
    """),
])


def _box_geometry(dx: float, dy: float, dz: float):
    hx, hy, hz = dx / 2, dy / 2, dz / 2
    v = np.array([
        [-hx, -hy, -hz], [hx, -hy, -hz], [hx, hy, -hz], [-hx, hy, -hz],
        [-hx, -hy, hz], [hx, -hy, hz], [hx, hy, hz], [-hx, hy, hz],
    ])
    # Faces grouped by side: 0=-X,1=+X,2=-Y,3=+Y(front),4=-Z,5=+Z
    faces = np.array([
        [0, 3, 7], [0, 7, 4],  # -X
        [1, 5, 6], [1, 6, 2],  # +X
        [0, 4, 5], [0, 5, 1],  # -Y
        [3, 2, 6], [3, 6, 7],  # +Y  (front)
        [0, 1, 2], [0, 2, 3],  # -Z
        [4, 7, 6], [4, 6, 5],  # +Z
    ])
    return v.astype(np.float32), faces.astype(np.int32)


def _box_colors(body_color: np.ndarray) -> np.ndarray:
    colors = np.tile(body_color, (12, 1))
    colors[6:8] = _FRONT_COLOR  # mark the +Y face as "front"
    return colors.astype(np.float32)


def _make_axis_triad(size: float) -> "gl.GLLinePlotItem":
    """A proper R=X, G=Y, B=Z axis gizmo. pyqtgraph's built-in GLAxisItem
    uses blue/yellow/green for X/Y/Z -- not the RGB=XYZ convention everyone
    actually expects -- so this replaces it."""
    pos = np.array([
        [0, 0, 0, size, 0, 0],  # X
        [0, 0, 0, 0, size, 0],  # Y
        [0, 0, 0, 0, 0, size],  # Z
    ], dtype=np.float32).reshape((-1, 3))

    color = np.array([
        [1, 0, 0, 1],  # X red
        [0, 1, 0, 1],  # Y green
        [0, 0, 1, 1],  # Z blue
    ], dtype=np.float32)
    color = np.hstack((color, color)).reshape((-1, 4))

    return gl.GLLinePlotItem(pos=pos, color=color, mode="lines", width=2, antialias=True)


class Viewport3D:
    def __init__(self):
        self.view = gl.GLViewWidget()
        self.view.setCameraPosition(distance=4.5, elevation=22, azimuth=45)
        self.view.setBackgroundColor((22, 24, 28))

        self.grid_item = gl.GLGridItem()
        self.grid_item.setSize(6, 6)
        self.grid_item.setSpacing(0.5, 0.5)
        self.grid_item.setColor((255, 255, 255, 40))
        self.view.addItem(self.grid_item)

        self._body_color = np.array(_DEFAULT_BODY_COLOR)
        self._board_size = DEFAULT_BOARD_SIZE
        v, f = _box_geometry(*self._board_size)
        self.mesh_item = gl.GLMeshItem(
            vertexes=v, faces=f, faceColors=_box_colors(self._body_color), shader="shaded",
            smooth=False, drawEdges=True, edgeColor=(0, 0, 0, 0.6),
        )
        self.view.addItem(self.mesh_item)

        self.axis_item = _make_axis_triad(1.4)
        self.view.addItem(self.axis_item)

        self._using_custom_model = False
        self._model_base_vertices: np.ndarray | None = None
        self._model_faces: np.ndarray | None = None
        self._model_pivot = np.zeros(3)
        self._model_rotation_cal = np.eye(3)
        self._model_rotation_deg = (0.0, 0.0, 0.0)
        self._last_R = np.eye(3)

    def widget(self):
        return self.view

    def set_theme(self, viewport_bg: tuple[int, int, int], grid_color: tuple[int, int, int, int]) -> None:
        self.view.setBackgroundColor(viewport_bg)
        self.grid_item.setColor(grid_color)

    def set_orientation(self, R: np.ndarray) -> None:
        self._last_R = R
        self._apply_transforms()

    def _apply_transforms(self) -> None:
        R = self._last_R

        # The axis triad always shows the true, uncalibrated orientation.
        self.axis_item.setTransform(_np_to_qmatrix(_rot_to_mat4(R)))

        # The model gets an extra fixed rotation on top, so its own (often
        # arbitrary) local axes can be calibrated to match the triad without
        # affecting what the triad itself represents.
        mesh_R = R @ self._model_rotation_cal if self._using_custom_model else R
        self.mesh_item.setTransform(_np_to_qmatrix(_rot_to_mat4(mesh_R)))

    def set_board_size(self, dx: float, dy: float, dz: float) -> None:
        self._board_size = (dx, dy, dz)
        if not self._using_custom_model:
            self._apply_box_mesh()

    def reset_to_default(self) -> None:
        self._using_custom_model = False
        self._apply_box_mesh()

    def _apply_box_mesh(self) -> None:
        v, f = _box_geometry(*self._board_size)
        self.mesh_item.setMeshData(
            vertexes=v, faces=f, faceColors=_box_colors(self._body_color),
            shader="shaded", smooth=False, drawEdges=True, edgeColor=(0, 0, 0, 0.6),
        )

    def load_model(self, path: str) -> None:
        vertices, faces = load_mesh(path)
        # Scale imported models up a bit to visually match the default box.
        vertices = vertices * 1.4

        self._model_base_vertices = vertices
        self._model_faces = faces
        self._model_pivot = np.zeros(3)
        self._model_rotation_cal = np.eye(3)
        self._model_rotation_deg = (0.0, 0.0, 0.0)
        self._using_custom_model = True
        self._apply_model_mesh()
        self._apply_transforms()

    def set_model_pivot(self, dx: float, dy: float, dz: float) -> None:
        """Shifts the imported model's rotation origin (e.g. so it matches
        where the IMU actually sits on a PCB/enclosure, instead of the
        mesh's geometric centroid). Offset is in the same display-scale
        units the model renders in. The RGB axis triad always marks the
        current origin, so it doubles as a visual guide while adjusting."""
        self._model_pivot = np.array([dx, dy, dz], dtype=np.float64)
        if self._using_custom_model:
            self._apply_model_mesh()

    def set_model_rotation(self, roll: float, pitch: float, yaw: float) -> None:
        """Applies a fixed calibration rotation (degrees) to the imported
        model only -- the axis triad keeps showing the true orientation.
        Use this when the model's own local axes (baked into the STL/OBJ
        file) don't line up with the triad, independent of where its
        origin/pivot is."""
        self._model_rotation_deg = (roll, pitch, yaw)
        self._model_rotation_cal = euler_deg_to_rotation_matrix(roll, pitch, yaw)
        if self._using_custom_model:
            self._apply_transforms()

    def set_body_color(self, r: float, g: float, b: float) -> None:
        self._body_color = np.array([r, g, b, 1.0])
        if self._using_custom_model:
            self._apply_model_mesh()
        else:
            self._apply_box_mesh()

    def _apply_model_mesh(self) -> None:
        vertices = (self._model_base_vertices - self._model_pivot).astype(np.float32)
        color = np.tile(self._body_color, (self._model_faces.shape[0], 1)).astype(np.float32)
        # Smooth-shaded, no per-triangle wireframe: looks like a solid part
        # instead of a mess of triangulation lines on curved/dense meshes.
        self.mesh_item.setMeshData(
            vertexes=vertices, faces=self._model_faces, faceColors=color,
            shader="imu_shaded", smooth=True, drawEdges=False,
        )

    def screenshot(self, path: str) -> None:
        image = self.view.grabFramebuffer()
        image.save(path)

    @property
    def using_custom_model(self) -> bool:
        return self._using_custom_model

    @property
    def model_pivot(self) -> tuple[float, float, float]:
        return tuple(self._model_pivot)

    @property
    def model_rotation(self) -> tuple[float, float, float]:
        return self._model_rotation_deg

    @property
    def body_color(self) -> tuple[float, float, float]:
        return tuple(self._body_color[:3])


def _rot_to_mat4(R: np.ndarray) -> np.ndarray:
    m = np.eye(4, dtype=np.float64)
    m[:3, :3] = R
    return m


def _np_to_qmatrix(m: np.ndarray):
    from PySide6.QtGui import QMatrix4x4

    flat = m.flatten().tolist()  # row-major, matches QMatrix4x4(m11, m12, ...)
    return QMatrix4x4(*flat)
