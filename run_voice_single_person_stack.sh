#!/usr/bin/env bash
# Per-process NumPy 1.x compatibility; preserves the existing follow scripts.
set -e
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u

compat_dir=/home/pi/pupper-tests/ros-numpy1
if [[ ! -f "${compat_dir}/numpy/__init__.py" ]]; then
  echo "Missing isolated NumPy at ${compat_dir}; install it before starting."
  exit 1
fi
export PYTHONPATH="${compat_dir}:${PYTHONPATH:-}"
unset VIRTUAL_ENV PYTHONHOME
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:${PATH}"

# Exercise the exact CvBridge conversion that failed before touching motors.
/usr/bin/python3 - <<'PY'
import numpy as np
import cv2
from cv_bridge import CvBridge
from sensor_msgs.msg import CompressedImage
assert np.__version__.split('.')[0] == '1', (np.__version__, np.__file__)
image = np.zeros((2, 2, 3), dtype=np.uint8)
ok, encoded = cv2.imencode('.jpg', image)
assert ok
message = CompressedImage()
message.format = 'jpeg'
message.data = encoded.tobytes()
decoded = CvBridge().compressed_imgmsg_to_cv2(message, 'bgr8')
assert decoded.shape == image.shape
print('ROS_NUMPY_OK:', np.__version__, np.__file__, flush=True)
print('CV_BRIDGE_OK: compressed image conversion passed', flush=True)
PY

if [[ "${1:-}" == '--check' ]]; then
  exit 0
fi

# Refuse duplicate stacks before entering the old script's cleanup handlers.
if pidof ros2_control_node >/dev/null 2>&1; then
  echo 'STOP: a controller is already running. No new stack was started.'
  exit 1
fi
if pgrep -f '/camera_ros/lib/camera_ros/camera_node|/hailo/lib/hailo/hailo_detection' >/dev/null 2>&1; then
  echo 'STOP: an existing camera/Hailo stack is running. No new stack was started.'
  exit 1
fi
if pgrep -f '/home/pi/pupper-tests/(single_person_follower|appearance_person_follower)\.py.*--execute' >/dev/null 2>&1; then
  echo 'STOP: an older execution follower is still running. No new stack was started.'
  exit 1
fi
exec /bin/bash /home/pi/pupper-tests/run_single_person_follow_safe.sh "${1:-600}"
