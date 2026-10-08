import importlib.util

from launch import LaunchService


spec = importlib.util.spec_from_file_location(
    "official_stand_hold_launch",
    "/home/pi/pupper-tests/official_stand_hold.launch.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

service = LaunchService()
service.include_launch_description(module.generate_launch_description())
raise SystemExit(service.run())
