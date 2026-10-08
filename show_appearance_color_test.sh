#!/usr/bin/env bash
# Only an observer; no --execute option is accepted by the Python program.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u
compat_dir=/home/pi/pupper-tests/ros-numpy1
if [[ ! -f "${compat_dir}/numpy/__init__.py" ]]; then
  echo 'Missing isolated NumPy 1.x compatibility directory.'; exit 1
fi
export PYTHONPATH="${compat_dir}:${PYTHONPATH:-}"
unset PYTHONHOME VIRTUAL_ENV
exec /usr/bin/python3 /home/pi/pupper-tests/appearance_color_observer.py "$@"
