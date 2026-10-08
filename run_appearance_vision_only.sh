#!/usr/bin/env bash
# Persistent observation camera pipeline; never starts motor controllers.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u
if pidof ros2_control_node >/dev/null 2>&1; then
  echo 'STOP: motor controller is running. Do not start another vision stack.'; exit 1
fi
if pgrep -f '/camera_ros/lib/camera_ros/camera_node|/hailo/lib/hailo/hailo_detection' >/dev/null 2>&1; then
  echo 'STOP: camera/Hailo already running. No existing process was changed.'; exit 1
fi
compat_dir=/home/pi/pupper-tests/ros-numpy1
if [[ ! -f "${compat_dir}/numpy/__init__.py" ]]; then
  echo 'Missing isolated NumPy 1.x compatibility directory.'; exit 1
fi
export PYTHONPATH="${compat_dir}:${PYTHONPATH:-}"
unset VIRTUAL_ENV PYTHONHOME
echo 'VISION ONLY: camera + Hailo. NO MOTOR CONTROLLER. Keep this window open; Ctrl+C stops vision.'
exec /usr/bin/python3 -u /home/pi/pupper-tests/run_appearance_vision_only.py "$@"
