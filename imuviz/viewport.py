"""The live 3D view: a GPU-rendered (OpenGL, via pyqtgraph) scene showing
either a default IMU-board placeholder or a user-imported mesh, rotated in
real time by incoming orientation data."""

from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.shaders import FragmentShader, ShaderProgram, VertexShader

from .model_loader import load_mesh

# Front-face color vs. body color, so the "front" of the board/model is
# always visually obvious no matter how it's spun around.
_BODY_COLOR = (0.55, 0.62, 0.75, 1.0)
_FRONT_COLOR = (0.95, 0.35, 0.25, 1.0)

DEFAULT_BOARD_SIZE = (1.6, 1.0, 0.28)

# pyqtgraph's built-in 'shaded' shader floors brightness at 20% ambient,
# which is dark enough to nearly vanish against this app's dark background
# on faces angled away from the light. Same shading model, brighter floor,
# so smooth-shaded imported models stay visible from every angle.
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


def _box_mesh(dx: float, dy: float, dz: float):
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
    colors = np.tile(np.array(_BODY_COLOR), (faces.shape[0], 1))
    colors[6:8] = _FRONT_COLOR  # mark the +Y face as "front"
    return v.astype(np.float32), faces.astype(np.int32), colors.astype(np.float32)


class Viewport3D:
    def __init__(self):
        self.view = gl.GLViewWidget()
        self.view.setCameraPosition(distance=4.5, elevation=22, azimuth=45)
        self.view.setBackgroundColor((22, 24, 28))

        grid = gl.GLGridItem()
        grid.setSize(6, 6)
        grid.setSpacing(0.5, 0.5)
        grid.setColor((255, 255, 255, 40))
        self.view.addItem(grid)

        self._board_size = DEFAULT_BOARD_SIZE
        v, f, c = _box_mesh(*self._board_size)
        self.mesh_item = gl.GLMeshItem(
            vertexes=v, faces=f, faceColors=c, shader="shaded",
            smooth=False, drawEdges=True, edgeColor=(0, 0, 0, 0.6),
        )
        self.view.addItem(self.mesh_item)

        self.axis_item = gl.GLAxisItem()
        self.axis_item.setSize(1.4, 1.4, 1.4)
        self.view.addItem(self.axis_item)

        self._using_custom_model = False

    def widget(self):
        return self.view

    def set_orientation(self, R: np.ndarray) -> None:
        m = np.eye(4, dtype=np.float64)
        m[:3, :3] = R
        tr = _np_to_qmatrix(m)
        self.mesh_item.setTransform(tr)
        self.axis_item.setTransform(tr)

    def set_board_size(self, dx: float, dy: float, dz: float) -> None:
        self._board_size = (dx, dy, dz)
        if not self._using_custom_model:
            v, f, c = _box_mesh(dx, dy, dz)
            self.mesh_item.setMeshData(
                vertexes=v, faces=f, faceColors=c,
                shader="shaded", smooth=False, drawEdges=True, edgeColor=(0, 0, 0, 0.6),
            )

    def reset_to_default(self) -> None:
        v, f, c = _box_mesh(*self._board_size)
        self.mesh_item.setMeshData(
            vertexes=v, faces=f, faceColors=c,
            shader="shaded", smooth=False, drawEdges=True, edgeColor=(0, 0, 0, 0.6),
        )
        self._using_custom_model = False

    def load_model(self, path: str) -> None:
        vertices, faces = load_mesh(path)
        # Scale imported models up a bit to visually match the default box.
        vertices = vertices * 1.4
        color = np.tile(np.array(_BODY_COLOR), (faces.shape[0], 1)).astype(np.float32)
        # Smooth-shaded, no per-triangle wireframe: looks like a solid part
        # instead of a mess of triangulation lines on curved/dense meshes.
        self.mesh_item.setMeshData(
            vertexes=vertices, faces=faces, faceColors=color,
            shader="imu_shaded", smooth=True, drawEdges=False,
        )
        self._using_custom_model = True

    def screenshot(self, path: str) -> None:
        image = self.view.grabFramebuffer()
        image.save(path)

    @property
    def using_custom_model(self) -> bool:
        return self._using_custom_model


def _np_to_qmatrix(m: np.ndarray):
    from PySide6.QtGui import QMatrix4x4

    flat = m.flatten().tolist()  # row-major, matches QMatrix4x4(m11, m12, ...)
    return QMatrix4x4(*flat)
