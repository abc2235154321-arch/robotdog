#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u

test_dir=/home/pi/pupper-tests
log_dir="${test_dir}/logs"
mkdir -p "${log_dir}"
camera_log="${log_dir}/camera_only_$(date +%Y%m%d_%H%M%S).log"
bridge_log="${log_dir}/foxglove_camera_$(date +%Y%m%d_%H%M%S).log"
camera_pid=""
bridge_pid=""
cleanup_done=0

stop_pid_group() {
  local pid="$1"
  if [[ -n "${pid}" ]] && kill -0 -- "-${pid}" 2>/dev/null; then
    kill -INT -- "-${pid}" 2>/dev/null || true
    sleep 0.5
    kill -TERM -- "-${pid}" 2>/dev/null || true
  fi
}

cleanup() {
  if [[ "${cleanup_done}" -eq 1 ]]; then
    return
  fi
  cleanup_done=1
  trap - EXIT INT TERM
  stop_pid_group "${bridge_pid}"
  stop_pid_group "${camera_pid}"
  [[ -n "${bridge_pid}" ]] && wait "${bridge_pid}" 2>/dev/null || true
  [[ -n "${camera_pid}" ]] && wait "${camera_pid}" 2>/dev/null || true
}

on_signal() {
  echo
  echo "Stopping camera screen only mode."
  cleanup
  exit 130
}

trap cleanup EXIT
trap on_signal INT TERM

if pgrep -f '/camera_ros/lib/camera_ros/camera_node' >/dev/null 2>&1; then
  echo "STOP: camera_node is already running. Stop the older camera process first."
  exit 1
fi

if pgrep -f '/foxglove_bridge/lib/foxglove_bridge/foxglove_bridge' >/dev/null 2>&1; then
  echo "STOP: foxglove_bridge is already running. Stop the older bridge first."
  exit 1
fi

config_file="$(ros2 pkg prefix neural_controller)/share/neural_controller/launch/config.yaml"
if [[ ! -f "${config_file}" ]]; then
  echo "STOP: official camera configuration was not found: ${config_file}"
  exit 1
fi

echo "Starting camera only. No motor controller will be launched."
setsid ros2 run camera_ros camera_node --ros-args \
  -r __node:=camera \
  --params-file "${config_file}" \
  >"${camera_log}" 2>&1 &
camera_pid=$!

camera_ready=0
for _ in $(seq 1 30); do
  if ! kill -0 "${camera_pid}" 2>/dev/null; then
    echo "STOP: camera process exited early."
    tail -n 100 "${camera_log}"
    exit 1
  fi
  camera_info="$(timeout 3s ros2 topic info /camera/image_raw 2>/dev/null || true)"
  if grep -Eq "Publisher count: [1-9]" <<<"${camera_info}"; then
    camera_ready=1
    break
  fi
  sleep 1
done

if [[ "${camera_ready}" -ne 1 ]]; then
  echo "STOP: camera did not publish /camera/image_raw within 30 seconds."
  tail -n 120 "${camera_log}"
  exit 1
fi

echo "Camera is publishing. Starting Foxglove bridge on port 8765."
setsid ros2 run foxglove_bridge foxglove_bridge --ros-args \
  -p port:=8765 \
  >"${bridge_log}" 2>&1 &
bridge_pid=$!

sleep 2
if ! kill -0 "${bridge_pid}" 2>/dev/null; then
  echo "STOP: Foxglove bridge failed to start."
  tail -n 100 "${bridge_log}"
  exit 1
fi

robot_ip="$(hostname -I | awk '{print $1}')"
echo
echo "CAMERA READY - NO MOTORS STARTED"
echo "Foxglove connection: ws://${robot_ip}:8765"
echo "In Foxglove, add an Image panel and select /camera/image_raw."
echo "Press Ctrl+C here to stop the camera and bridge."

while true; do
  if ! kill -0 "${camera_pid}" 2>/dev/null; then
    echo "STOP: camera process exited unexpectedly."
    tail -n 100 "${camera_log}"
    exit 1
  fi
  if ! kill -0 "${bridge_pid}" 2>/dev/null; then
    echo "STOP: Foxglove bridge exited unexpectedly."
    tail -n 100 "${bridge_log}"
    exit 1
  fi
  sleep 1
done
