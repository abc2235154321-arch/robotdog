"""ROS launch runner; the launch description contains only camera and Hailo."""
import argparse
import importlib.util
import math
from pathlib import Path


def parse_projection(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h-fov", type=float, help="Test horizontal field of view in degrees")
    parser.add_argument("--v-fov", type=float, help="Test vertical field of view in degrees")
    args = parser.parse_args(argv)
    if args.h_fov is None and args.v_fov is None:
        return {}  # Preserve the official configuration unless explicitly requested.
    if args.h_fov is None or args.v_fov is None:
        parser.error("Specify both --h-fov and --v-fov")
    if any(not math.isfinite(value) or not 1 <= value <= 180
           for value in (args.h_fov, args.v_fov)):
        parser.error("Test fields of view must be finite and between 1 and 180 degrees")
    return {"equirect_h_fov_deg": args.h_fov, "equirect_v_fov_deg": args.v_fov}


def main(argv=None):
    projection = parse_projection(argv)
    from launch import LaunchService
    spec = importlib.util.spec_from_file_location(
        "appearance_vision_only", Path(__file__).with_name("appearance_vision_only.launch.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if projection:
        print(f"TEST FOV: {projection['equirect_h_fov_deg']} / {projection['equirect_v_fov_deg']} degrees; "
              "restart the appearance observer so its projection matches. NO MOTOR COMMANDS.", flush=True)
    service = LaunchService()
    service.include_launch_description(module.generate_launch_description(projection))
    return service.run()


if __name__ == "__main__":
    raise SystemExit(main())
