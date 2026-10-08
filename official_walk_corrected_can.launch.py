import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile
from launch_ros.substitutions import FindPackageShare


# Physical wiring verified from the assembly slides and this robot, using the
# robot's own left/right perspective.
CORRECTED_CAN_CHANNELS = {
    "leg_front_r_1": 1,
    "leg_front_r_2": 1,
    "leg_front_r_3": 1,
    "leg_front_l_1": 2,
    "leg_front_l_2": 2,
    "leg_front_l_3": 2,
    "leg_back_r_1": 3,
    "leg_back_r_2": 3,
    "leg_back_r_3": 3,
    "leg_back_l_1": 4,
    "leg_back_l_2": 4,
    "leg_back_l_3": 4,
}


def build_corrected_robot_description() -> str:
    package_share = Path(get_package_share_directory("pupper_v3_description"))
    xacro_file = package_share / "description" / "pupper_v3.urdf.xacro"
    result = subprocess.run(
        ["xacro", str(xacro_file)],
        check=True,
        capture_output=True,
        text=True,
    )

    root = ET.fromstring(result.stdout)
    found = set()
    for joint in root.findall(".//ros2_control/joint"):
        joint_name = joint.get("name")
        if joint_name not in CORRECTED_CAN_CHANNELS:
            continue
        can_param = joint.find("./param[@name='can_channel']")
        if can_param is None:
            raise RuntimeError(f"Missing can_channel for {joint_name}")
        can_param.text = str(CORRECTED_CAN_CHANNELS[joint_name])
        found.add(joint_name)

    missing = set(CORRECTED_CAN_CHANNELS) - found
    if missing:
        raise RuntimeError(f"Missing expected joints in generated URDF: {sorted(missing)}")

    return ET.tostring(root, encoding="unicode")


def generate_launch_description():
    robot_description = {
        "robot_description": build_corrected_robot_description(),
    }
    node_parameters = ParameterFile(
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
                parameters=[node_parameters],
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
        ]
    )


if __name__ == "__main__":
    description = build_corrected_robot_description()
    root = ET.fromstring(description)
    actual = {}
    for joint in root.findall(".//ros2_control/joint"):
        joint_name = joint.get("name")
        if joint_name in CORRECTED_CAN_CHANNELS:
            can_param = joint.find("./param[@name='can_channel']")
            actual[joint_name] = int(can_param.text)
    if actual != CORRECTED_CAN_CHANNELS:
        raise SystemExit(f"CAN map verification failed: {actual}")
    for joint_name, channel in actual.items():
        print(f"{joint_name}=CAN{channel}")
