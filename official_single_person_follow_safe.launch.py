from launch import LaunchDescription
from launch.actions import ExecuteProcess, EmitEvent
from launch.events import Shutdown
from launch.substitutions import Command, FindExecutable, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile
from launch_ros.substitutions import FindPackageShare


def generate_launch_description(appearance=False):
    """Separate single-person experiment; no original follower or safety filter."""
    xacro_file = PathJoinSubstitution(
        [
            FindPackageShare("pupper_v3_description"),
            "description",
            "pupper_v3.urdf.xacro",
        ]
    )
    robot_description = {
        "robot_description": Command(
            [PathJoinSubstitution([FindExecutable(name="xacro")]), " ", xacro_file]
        )
    }
    official_parameters = ParameterFile(
        PathJoinSubstitution(
            [FindPackageShare("neural_controller"), "launch", "config.yaml"]
        ),
        allow_substs=True,
    )

    return LaunchDescription(
        [
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                parameters=[robot_description],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="ros2_control_node",
                parameters=[official_parameters],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=[
                    "neural_controller",
                    "--controller-manager",
                    "/controller_manager",
                    "--controller-manager-timeout",
                    "30",
                    "--inactive",
                ],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=[
                    "joint_state_broadcaster",
                    "--controller-manager",
                    "/controller_manager",
                    "--controller-manager-timeout",
                    "30",
                ],
                output="screen",
            ),
            Node(
                package="camera_ros",
                executable="camera_node",
                name="camera",
                parameters=[official_parameters],
                output="screen",
            ),
            Node(
                package="hailo",
                executable="hailo_detection",
                name="hailo_detection_node",
                parameters=[official_parameters],
                output="screen",
            ),
            Node(
                package="cmd_vel_mux",
                executable="cmd_vel_mux_node",
                name="cmd_vel_mux",
                # Isolate this experiment from old AI/teleop velocity sources.
                parameters=[official_parameters, {
                    "inputs": ["/person_following_cmd_vel"], "timeout_ms": 250,
                }],
                output="screen",
            ),
            ExecuteProcess(
                cmd=["/usr/bin/python3", "-u",
                     "/home/pi/pupper-tests/appearance_person_follower.py" if appearance else
                     "/home/pi/pupper-tests/single_person_follower.py", "--execute"],
                output="screen",
                on_exit=[EmitEvent(event=Shutdown(reason="Appearance follower exited" if appearance else "Single-person follower exited"))],
            ),
        ]
    )
