import numpy as np
import matplotlib
matplotlib.use('TkAgg')

from matplotlib import pyplot as plt
from matplotlib import animation

import serial
import threading
import time
import math

from lib.rotation import RPY2XYZ, D2R, plane
from lib.plotting import insideAnimation, outsideAnimation, smallDetails


# ============================================================
# CONFIGURATION
# ============================================================

SERIAL_PORT = 'COM17'
BAUDRATE = 115200

# Matplotlib update rate
ANIMATION_INTERVAL_MS = 10  # ~60 FPS


# ============================================================
# QUATERNION / EULER CONVERSION
# ============================================================

def quaternion_to_euler_degrees(q0, q1, q2, q3):
    """
    Convert quaternion (w, x, y, z) to Euler angles in degrees.
    Returns roll, pitch, yaw.
    """

    roll = math.atan2(
        2 * (q0*q1 + q2*q3),
        q0*q0 - q1*q1 - q2*q2 + q3*q3
    )

    pitch = math.atan2(
        -2 * (q1*q3 - q0*q2),
        q0*q0 - q1*q1 - q2*q2 + q3*q3
    )

    yaw = math.atan2(
        2 * (q1*q2 + q0*q3),
        q0*q0 + q1*q1 - q2*q2 - q3*q3
    )

    return (
        math.degrees(roll),
        math.degrees(pitch),
        math.degrees(yaw)
    )


# ============================================================
# QUATERNION -> ROTATION MATRIX
# ============================================================

def quaternion_to_rotation_matrix(q):
    q0, q1, q2, q3 = q

    return np.array([
        [
            1 - 2*q2**2 - 2*q3**2,
            2*q1*q2 - 2*q0*q3,
            2*q1*q3 + 2*q0*q2
        ],
        [
            2*q1*q2 + 2*q0*q3,
            1 - 2*q1**2 - 2*q3**2,
            2*q2*q3 - 2*q0*q1
        ],
        [
            2*q1*q3 - 2*q0*q2,
            2*q2*q3 + 2*q0*q1,
            1 - 2*q1**2 - 2*q2**2
        ]
    ])


# ============================================================
# SERIAL READER
# ============================================================

latest_quaternion = np.array([1.0, 0.0, 0.0, 0.0])

quaternion_lock = threading.Lock()

serial_running = True


def serial_reader():
    global latest_quaternion

    print(f"Opening {SERIAL_PORT}...")

    try:
        comm = serial.Serial(
            SERIAL_PORT,
            baudrate=BAUDRATE,
            timeout=1
        )

        print(f"Connected to {SERIAL_PORT}")

        # Give the ESP32 time to reset after opening serial
        time.sleep(2)

        # Clear anything already waiting
        comm.reset_input_buffer()

        while serial_running:

            line = comm.readline()

            if not line:
                continue

            try:
                text = line.decode('ascii', errors='ignore').strip()

                parts = text.split(';')

                if len(parts) != 4:
                    continue

                q = np.array([
                    float(parts[0]),
                    float(parts[1]),
                    float(parts[2]),
                    float(parts[3])
                ], dtype=float)

                # Make sure quaternion isn't zero
                magnitude = np.linalg.norm(q)

                if magnitude < 1e-6:
                    continue

                q /= magnitude

                # Atomically replace latest quaternion
                with quaternion_lock:
                    latest_quaternion = q

            except (ValueError, UnicodeDecodeError):
                # Ignore malformed serial lines
                continue

        comm.close()

    except serial.SerialException as e:
        print("Serial error:", e)


# Start serial reader thread
reader_thread = threading.Thread(
    target=serial_reader,
    daemon=True
)

reader_thread.start()


# ============================================================
# MATPLOTLIB SETUP
# ============================================================

fig = plt.figure()

ax = fig.add_subplot(
    111,
    projection='3d'
)

state_display = ax.text2D(
    0.07,
    1.0,
    "",
    color='green',
    transform=ax.transAxes
)

error_display = ax.text2D(
    0.07,
    0.95,
    "",
    color='red',
    transform=ax.transAxes
)


# ============================================================
# CUBE
# ============================================================

cube = np.array([
    [0.2, 0.2, 0.0],
    [0.2, 1.2, 0.0],
    [0.8, 1.2, 0.0],
    [0.8, 0.2, 0.0],

    [0.2, 0.2, 0.6],
    [0.8, 0.2, 0.6],
    [0.8, 1.2, 0.6],
    [0.2, 1.2, 0.6]
])


com = cube.mean(axis=0)

ax.plot(
    com[0],
    com[1],
    com[2],
    'ro'
)


# Initial cube

x = cube[:, 0]
y = cube[:, 1]
z = cube[:, 2]

coordinates = np.array([
    x,
    y,
    z
])

planes = plane(coordinates)

line1, line2, line3, line4, line5, line6 = outsideAnimation(
    planes,
    ax
)

smallDetails(ax)


# ============================================================
# MATPLOTLIB UPDATE
# ============================================================

def update_point(_):

    global coordinates

    try:

        # ----------------------------------------------------
        # Get newest quaternion
        # ----------------------------------------------------

        with quaternion_lock:
            q = latest_quaternion.copy()

        # ----------------------------------------------------
        # Rotation matrix
        # ----------------------------------------------------

        R = quaternion_to_rotation_matrix(q)

        error_display.set_text("")

        # ----------------------------------------------------
        # Euler angles
        # ----------------------------------------------------

        phi, theta, psi = quaternion_to_euler_degrees(
            q[0],
            q[1],
            q[2],
            q[3]
        )

        # ----------------------------------------------------
        # Display quaternion
        # ----------------------------------------------------

        quat_text = (
            f"q = "
            f"[{q[0]:.5f}, "
            f"{q[1]:.5f}, "
            f"{q[2]:.5f}, "
            f"{q[3]:.5f}]"
        )

        # ----------------------------------------------------
        # Display Euler angles
        # ----------------------------------------------------

        angles_text = (
            f"Roll (φ): {phi:.2f}°, "
            f"Pitch (θ): {theta:.2f}°, "
            f"Yaw (ψ): {psi:.2f}°"
        )

        state_display.set_text(
            f"IMU LSM6DSV16X Rotation\n"
            f"Quaternion:\n"
            f"{quat_text}\n"
            f"Euler Angles:\n"
            f"{angles_text}"
        )

        # ----------------------------------------------------
        # Rotate cube
        # ----------------------------------------------------

        new_coords = []

        for vertex in cube:

            rel = vertex - com

            rotated = np.dot(
                R,
                rel
            ) + com

            new_coords.append(rotated)

        coords = np.array(new_coords).T

        # ----------------------------------------------------
        # Update cube planes
        # ----------------------------------------------------

        plane_data = plane(coords)

        insideAnimation(
            line1,
            line2,
            line3,
            line4,
            line5,
            line6,
            *plane_data
        )

    except Exception as e:

        error_display.set_text(
            "Data error: " + str(e)
        )

    return (
        line1,
        line2,
        line3,
        line4,
        line5,
        line6
    )


# ============================================================
# ANIMATION
# ============================================================

ani = animation.FuncAnimation(
    fig,
    update_point,
    interval=ANIMATION_INTERVAL_MS,
    cache_frame_data=False
)


# ============================================================
# CLEAN SHUTDOWN
# ============================================================

def on_close(event):
    global serial_running

    serial_running = False


fig.canvas.mpl_connect(
    'close_event',
    on_close
)


# ============================================================
# RUN
# ============================================================

plt.show()

plt.close()
