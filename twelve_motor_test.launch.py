from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    with open(
        "/home/pi/pupper-tests/twelve_motor_test.urdf", "r", encoding="utf-8"
    ) as urdf_file:
        robot_description = urdf_file.read()

    return LaunchDescription(
        [
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                parameters=[{"robot_description": robot_description}],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="ros2_control_node",
                parameters=[{"update_rate": 200}],
                output="screen",
            ),
        ]
    )
