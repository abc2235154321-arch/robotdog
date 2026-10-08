#!/usr/bin/env python3
"""Load the separate 0.40 m/s person-follow launch without editing official files."""

import importlib.util

from launch import LaunchService


spec = importlib.util.spec_from_file_location(
    "official_person_follow_gait040_safe_launch",
    "/home/pi/pupper-tests/official_person_follow_gait040_safe.launch.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

service = LaunchService()
service.include_launch_description(module.generate_launch_description())
raise SystemExit(service.run())
