"""Reuse the isolated motor launch, replacing its follower, never adding one."""
import importlib.util
from pathlib import Path
from launch import LaunchService

spec = importlib.util.spec_from_file_location(
    "appearance_motor_launch", Path(__file__).with_name("official_single_person_follow_safe.launch.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
service = LaunchService()
service.include_launch_description(module.generate_launch_description(appearance=True))
raise SystemExit(service.run())
