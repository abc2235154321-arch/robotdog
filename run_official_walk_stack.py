import importlib.util

from launch import LaunchService


spec = importlib.util.spec_from_file_location(
    "official_walk_demo_launch",
    "/home/pi/pupper-tests/official_walk_demo.launch.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

service = LaunchService()
service.include_launch_description(module.generate_launch_description())
raise SystemExit(service.run())
