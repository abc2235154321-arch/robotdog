from launch import LaunchDescription
from launch.substitutions import Command, FindExecutable, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
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
    node_parameters = ParameterFile(
        PathJoinSubstitution(
            [FindPackageShare("neural_controller"), "launch", "config.yaml"]
        ),
        allow_substs=True,
    )

    def inactive_spawner(controller_name):
        return Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                controller_name,
                "--controller-manager",
                "/controller_manager",
                "--controller-manager-timeout",
                "30",
                "--inactive",
            ],
            output="screen",
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
                parameters=[node_parameters],
                output="screen",
            ),
            inactive_spawner("forward_position_controller"),
            inactive_spawner("forward_kp_controller"),
            inactive_spawner("forward_kd_controller"),
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
                package="animation_controller_py",
                executable="animation_controller_py",
                name="animation_controller_py",
                parameters=[node_parameters],
                output="screen",
            ),
            Node(
                package="topic_tools",
                executable="throttle",
                name="joint_state_throttler",
                parameters=[node_parameters],
                arguments=["messages"],
                output="screen",
            ),
        ]
    )
