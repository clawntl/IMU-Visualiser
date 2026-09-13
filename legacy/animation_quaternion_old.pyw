import numpy as np
import matplotlib
from matplotlib import pyplot as plt
from matplotlib import animation
import serial
from lib.rotation import RPY2XYZ, D2R, plane
from lib.plotting import insideAnimation, outsideAnimation, smallDetails

import math

def quaternion_to_euler_degrees(q0, q1, q2, q3):
    """
    Convert quaternion (w, x, y, z) to Euler angles in degrees
    Returns roll (phi), pitch (theta), yaw (psi)
    """
    # roll (x-axis rotation)
    #sinr_cosp = 2 * (q0 * q1 + q2 * q3)
    #cosr_cosp = 1 - 2 * (q1 * q1 + q2 * q2)
    #roll = math.atan2(sinr_cosp, cosr_cosp)

    roll = math.atan2(2 * (q0*q1 + q2*q3), q0*q0 - q1*q1 - q2*q2 + q3*q3)

    pitch = math.atan2(-2 * (q1*q3 - q0*q2), q0*q0 - q1*q1 - q2*q2 + q3*q3)

    yaw = math.atan2(2 * (q1*q2 + q0*q3), q0*q0 + q1*q1 - q2*q2 - q3*q3)

    # pitch (y-axis rotation)
    #sinp = 2 * (q0 * q2 - q3 * q1)
    #if abs(sinp) >= 1:
        #pitch = math.copysign(math.pi / 2, sinp)  # use 90 degrees if out of range
    #else:
        #pitch = math.asin(sinp)

    # yaw (z-axis rotation)
    #siny_cosp = 2 * (q0 * q3 + q1 * q2)
    #cosy_cosp = 1 - 2 * (q2 * q2 + q3 * q3)
    #yaw = math.atan2(siny_cosp, cosy_cosp)

    # convert radians to degrees
    roll_deg = math.degrees(roll)
    pitch_deg = math.degrees(pitch)
    yaw_deg = math.degrees(yaw)

    return roll_deg, pitch_deg, yaw_deg

matplotlib.use('TkAgg')
print(matplotlib.get_backend())

# Open Serial
comm = serial.Serial('COM17', baudrate=115200)

# Set up figure
fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')

state_display = ax.text2D(0.07, 1.0, "", color='green', transform=ax.transAxes)
error_display = ax.text2D(0.07, 0.95, "", color='red', transform=ax.transAxes)

# Cube corners
cube = np.array([
    [0.2, 0.2, 0.0], [0.2, 1.2, 0.0], [0.8, 1.2, 0.0], [0.8, 0.2, 0.0],
    [0.2, 0.2, 0.6], [0.8, 0.2, 0.6], [0.8, 1.2, 0.6], [0.2, 1.2, 0.6]
])

# Center of mass
com = cube.mean(axis=0)
ax.plot(com[0], com[1], com[2], 'ro')

# Initial cube plot
x, y, z = cube[:, 0], cube[:, 1], cube[:, 2]
coordinates = np.array([x, y, z])
planes = plane(coordinates)
line1, line2, line3, line4, line5, line6 = outsideAnimation(planes, ax)
smallDetails(ax)


def quaternion_to_rotation_matrix(q):
    q0, q1, q2, q3 = q
    return np.array([
        [1 - 2*q2**2 - 2*q3**2,     2*q1*q2 - 2*q0*q3,       2*q1*q3 + 2*q0*q2],
        [2*q1*q2 + 2*q0*q3,         1 - 2*q1**2 - 2*q3**2,   2*q2*q3 - 2*q0*q1],
        [2*q1*q3 - 2*q0*q2,         2*q2*q3 + 2*q0*q1,       1 - 2*q1**2 - 2*q2**2]
    ])


def update_point(_):
    global coordinates
    try:
        raw = comm.readline().decode('ascii').strip().split(';')
        if len(raw) < 4:
            raise ValueError("Incomplete quaternion")

        q = np.array([float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])])
        q = q / np.linalg.norm(q)  # Normalize
        R = quaternion_to_rotation_matrix(q)
        error_display.set_text("")

        phi, theta, psi = quaternion_to_euler_degrees(q[0], q[1], q[2], q[3])


        # Format quaternion with 5 decimals
        quat_text = f"q = [{q[0]:.5f}, {q[1]:.5f}, {q[2]:.5f}, {q[3]:.5f}]"

        # Format Euler angles in degrees with 2 decimals
        angles_text = f"Roll (φ): {phi:.2f}°, Pitch (θ): {theta:.2f}°, Yaw (ψ): {psi:.2f}°"

        # Set the combined text on your state_display
        state_display.set_text(f"IMU BMI160 Rotation\nQuaternion:\n{quat_text}\nEuler Angles:\n{angles_text}")


    except Exception as e:
        R = np.eye(3)
        error_display.set_text("Data error: " + str(e))

    new_coords = []
    for vertex in cube:
        rel = vertex - com
        rotated = np.dot(R, rel) + com
        new_coords.append(rotated)

    coords = np.array(new_coords).T
    plane_data = plane(coords)
    insideAnimation(line1, line2, line3, line4, line5, line6, *plane_data)

    
    return line1, line2, line3, line4, line5, line6


ani = animation.FuncAnimation(fig, update_point, interval=10, cache_frame_data=False)
plt.show()
plt.close()
