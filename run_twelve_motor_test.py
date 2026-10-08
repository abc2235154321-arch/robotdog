import importlib.util

from launch import LaunchService


print(
    "12-motor staged homing test (robot facing forward):\n"
    "  Stage 0: all motor ID 3\n"
    "  Stage 1: all motor ID 2\n"
    "  Stage 2: all motor ID 1\n"
    "  CAN1 front-left, CAN2 front-right, CAN3 back-left, CAN4 back-right\n",
    flush=True,
)

spec = importlib.util.spec_from_file_location(
    "twelve_motor_test_launch", "/home/pi/pupper-tests/twelve_motor_test.launch.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

service = LaunchService()
service.include_launch_description(module.generate_launch_description())
raise SystemExit(service.run())
