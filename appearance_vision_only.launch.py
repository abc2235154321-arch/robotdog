"""Persistent camera/Hailo only; no controllers, following, mux or motor actions."""
from launch import LaunchDescription
from launch.actions import EmitEvent
from launch.events import Shutdown
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile
from launch_ros.substitutions import FindPackageShare


def generate_launch_description(projection_parameters=None):
    parameters = ParameterFile(PathJoinSubstitution([
        FindPackageShare("neural_controller"), "launch", "config.yaml",
    ]), allow_substs=True)
    return LaunchDescription([
        Node(package="camera_ros", executable="camera_node", name="camera",
             parameters=[parameters], output="screen",
             on_exit=[EmitEvent(event=Shutdown(reason="Appearance camera exited"))]),
        Node(package="hailo", executable="hailo_detection", name="hailo_detection_node",
             # Last entry overrides only this test process, never the official YAML.
             parameters=[parameters, projection_parameters or {}], output="screen",
             on_exit=[EmitEvent(event=Shutdown(reason="Appearance Hailo exited"))]),
    ])
