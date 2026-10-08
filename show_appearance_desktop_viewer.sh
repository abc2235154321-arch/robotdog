#!/usr/bin/env bash
# Viewer only. No ROS sourcing, camera startup, browser or motor actions.
set -euo pipefail
if [[ -z "${DISPLAY:-}" ]]; then
  echo 'Specify the dog desktop, e.g. DISPLAY=:0 bash ~/pupper-tests/show_appearance_desktop_viewer.sh'; exit 1
fi
compat_dir=/home/pi/pupper-tests/ros-numpy1
if [[ ! -f "${compat_dir}/numpy/__init__.py" ]]; then
  echo 'Missing isolated NumPy 1.x directory.'; exit 1
fi
# Keep this small viewer independent of inherited ROS packages and venv state.
export PYTHONPATH="${compat_dir}"
unset VIRTUAL_ENV PYTHONHOME
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
exec /usr/bin/python3 /home/pi/pupper-tests/appearance_desktop_viewer.py "$@"
