import importlib.util

from launch import LaunchService


print(
    "Four-leg motor-1 test (robot facing forward):\n"
    "  CAN1 = robot front-left  = your right when facing robot\n"
    "  CAN2 = robot front-right = your left when facing robot\n"
    "  CAN3 = robot back-left   = your right when facing robot\n"
    "  CAN4 = robot back-right  = your left when facing robot\n",
    flush=True,
)

spec = importlib.util.spec_from_file_location(
    "four_leg_motor1_test_launch", "/home/pi/pupper-tests/four_leg_motor1_test.launch.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

service = LaunchService()
service.include_launch_description(module.generate_launch_description())
raise SystemExit(service.run())
