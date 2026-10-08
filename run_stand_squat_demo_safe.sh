#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u

test_dir=/home/pi/pupper-tests
log_dir="${test_dir}/logs"
mkdir -p "${log_dir}"
log_file="${log_dir}/stand_squat_$(date +%Y%m%d_%H%M%S).log"
launch_pid=""
cleanup_done=0

cleanup() {
  if [[ "${cleanup_done}" -eq 1 ]]; then
    return
  fi
  cleanup_done=1
  trap - EXIT INT TERM

  if [[ -n "${launch_pid}" ]] && kill -0 -- "-${launch_pid}" 2>/dev/null; then
    kill -INT -- "-${launch_pid}" 2>/dev/null || true
    for _ in $(seq 1 10); do
      if ! kill -0 -- "-${launch_pid}" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done
    if kill -0 -- "-${launch_pid}" 2>/dev/null; then
      kill -TERM -- "-${launch_pid}" 2>/dev/null || true
      sleep 0.5
    fi
    if kill -0 -- "-${launch_pid}" 2>/dev/null; then
      kill -KILL -- "-${launch_pid}" 2>/dev/null || true
    fi
  fi
  if [[ -n "${launch_pid}" ]]; then
    wait "${launch_pid}" 2>/dev/null || true
  fi
  launch_pid=""
}

on_signal() {
  echo
  echo "Stop requested; stopping the complete ROS process group."
  cleanup
  exit 130
}

trap cleanup EXIT
trap on_signal INT TERM

if pidof ros2_control_node >/dev/null 2>&1; then
  echo "STOP: ros2_control_node is already running. Do not start a second motor controller."
  echo "Run: pidof ros2_control_node"
  exit 1
fi

echo "Starting minimal official motor + animation stack."
echo "Camera, Hailo, joystick, walking controller, and bag recording are not started."
setsid python3 "${test_dir}/run_stand_squat_stack.py" >"${log_file}" 2>&1 &
launch_pid=$!

controllers_ready=0
for _ in $(seq 1 30); do
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    echo "STOP: launch process exited early."
    tail -n 100 "${log_file}"
    exit 1
  fi

  controllers="$(timeout 3s ros2 control list_controllers 2>/dev/null || true)"
  if grep -q "forward_position_controller" <<<"${controllers}" \
    && grep -q "forward_kp_controller" <<<"${controllers}" \
    && grep -q "forward_kd_controller" <<<"${controllers}"; then
    controllers_ready=1
    break
  fi
  sleep 1
done

if [[ "${controllers_ready}" -ne 1 ]]; then
  echo "STOP: animation controllers did not load."
  tail -n 100 "${log_file}"
  exit 1
fi

if ! timeout 10s ros2 topic echo --once /joint_states_throttled >/dev/null 2>&1; then
  echo "STOP: no valid joint-state feedback; animation was not sent."
  tail -n 100 "${log_file}"
  exit 1
fi

echo "Playing official stand -> sit -> stand animation."
ros2 topic pub --once \
  /animation_controller_py/animation_select \
  std_msgs/msg/String \
  "{data: stand_sit_stand_recording_2025-09-03_12-46-36_0}"

sleep 18
echo "Animation time finished; stopping motor stack."
cleanup
launch_pid=""
echo "Log saved to ${log_file}"
tail -n 80 "${log_file}"
