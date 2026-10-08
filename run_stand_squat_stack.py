import importlib.util

from launch import LaunchService


spec = importlib.util.spec_from_file_location(
    "stand_squat_demo_safe_launch",
    "/home/pi/pupper-tests/stand_squat_demo_safe.launch.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

service = LaunchService()
service.include_launch_description(module.generate_launch_description())
raise SystemExit(service.run())
