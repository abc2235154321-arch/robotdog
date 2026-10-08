#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u

test_dir=/home/pi/pupper-tests
log_file="${test_dir}/logs/person_vision_preflight_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "${test_dir}/logs"
launch_pid=""

stop_owned_vision_processes() {
  local pattern
  for pattern in \
    '/camera_ros/lib/camera_ros/camera_node' \
    '/hailo/lib/hailo/hailo_detection'; do
    pkill -TERM -f "${pattern}" 2>/dev/null || true
    for _ in $(seq 1 10); do
      if ! pgrep -f "${pattern}" >/dev/null 2>&1; then
        break
      fi
      sleep 0.2
    done
    if pgrep -f "${pattern}" >/dev/null 2>&1; then
      pkill -KILL -f "${pattern}" 2>/dev/null || true
    fi
  done
}

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "${launch_pid}" ]] && kill -0 -- "-${launch_pid}" 2>/dev/null; then
    kill -INT -- "-${launch_pid}" 2>/dev/null || true
    sleep 1
    kill -TERM -- "-${launch_pid}" 2>/dev/null || true
  fi
  if [[ -n "${launch_pid}" ]]; then
    wait "${launch_pid}" 2>/dev/null || true
  fi
  # ROS launch may give individual nodes their own process groups.  This
  # preflight owns these two exact executables and no motor controller is
  # allowed to coexist, so remove only its camera/Hailo leftovers.
  stop_owned_vision_processes
}
trap cleanup EXIT INT TERM

if pidof ros2_control_node >/dev/null 2>&1; then
  echo "STOP: a motor controller is running; finish that test first."
  exit 1
fi

if pgrep -f '/hailo/lib/hailo/hailo_detection' >/dev/null 2>&1 \
  || pgrep -f '/camera_ros/lib/camera_ros/camera_node' >/dev/null 2>&1; then
  echo "STOP: an older camera/Hailo process is already running."
  echo "Close the older vision test before starting this preflight."
  exit 1
fi

echo "VISION-ONLY PREFLIGHT: motors are not launched."
setsid python3 -u "${test_dir}/run_person_vision_preflight.py" \
  >"${log_file}" 2>&1 &
launch_pid=$!

ready=0
for _ in $(seq 1 35); do
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    echo "STOP: camera/Hailo launch exited early."
    tail -n 100 "${log_file}"
    exit 1
  fi
  info="$(timeout 3s ros2 topic info /detections 2>/dev/null || true)"
  if grep -Eq "Publisher count: [1-9]" <<<"${info}"; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "${ready}" -ne 1 ]]; then
  echo "STOP: /detections publisher did not appear."
  tail -n 120 "${log_file}"
  exit 1
fi

echo "VISION PIPELINE OK: camera -> Hailo -> /detections is active."
if timeout 15s python3 "${test_dir}/verify_person_detection.py" \
  --seconds 12 --required 3; then
  echo "PERSON DETECTED: stable class-0 detections were verified."
else
  echo "NO STABLE PERSON: pipeline works, but a person was not seen consistently."
  echo "Inspect the saved image under ${test_dir}/diagnostics/."
fi
echo "Log saved to ${log_file}"
