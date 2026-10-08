from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch.substitutions import Command, FindExecutable, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Launch the official Pupper V3 stack with a speed-limited person follower."""
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

    # These override only the runtime parameters of the official person_follower
    # node. No file in pupperv3-monorepo is modified.
    safe_follower_parameters = {
        "kp_angular": 0.55,
        "kp_linear": 1.2,
        "target_bbox_area": 0.70,
        "max_linear_vel": 0.35,
        "max_angular_vel": 0.50,
        "publish_rate": 10.0,
        "angular_deadzone": 0.16,
        "linear_deadzone": 0.06,
        "detection_timeout": 0.4,
    }

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
                parameters=[official_parameters],
                output="screen",
            ),
            Node(
                package="person_follower",
                executable="person_follower_node",
                name="person_follower_node",
                parameters=[safe_follower_parameters],
                remappings=[
                    (
                        "/person_following_cmd_vel",
                        "/person_following_raw_cmd_vel",
                    )
                ],
                output="screen",
            ),
            ExecuteProcess(
                cmd=[
                    "python3",
                    "/home/pi/pupper-tests/person_follow_safety_filter.py",
                ],
                output="screen",
            ),
        ]
    )










