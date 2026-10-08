from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    official_parameters = ParameterFile(
        PathJoinSubstitution(
            [FindPackageShare("neural_controller"), "launch", "config.yaml"]
        ),
        allow_substs=True,
    )
    return LaunchDescription(
        [
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
        ]
    )
