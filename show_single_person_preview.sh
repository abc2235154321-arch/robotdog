#!/usr/bin/env bash
# Run from the terminal on the dog's physical desktop, NOT the voice venv.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo "No graphical session. Run this script in the terminal ON THE DOG'S SCREEN."
  exit 1
fi
compat_dir=/home/pi/pupper-tests/ros-numpy1
if [[ ! -f "${compat_dir}/numpy/__init__.py" ]]; then
  echo 'Missing isolated NumPy 1.x compatibility directory.'; exit 1
fi
export PYTHONPATH="${compat_dir}:${PYTHONPATH:-}"
unset PYTHONHOME VIRTUAL_ENV
exec /usr/bin/python3 /home/pi/pupper-tests/single_person_follower.py --preview
