#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u

test_dir=/home/pi/pupper-tests
log_dir="${test_dir}/logs"
mkdir -p "${log_dir}"
log_file="${log_dir}/walk_demo_$(date +%Y%m%d_%H%M%S).log"
launch_pid=""
cleanup_done=0

send_zero() {
  timeout 3s ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" \
    >/dev/null 2>&1 || true
}

deactivate_neural() {
  timeout 5s ros2 service call \
    /controller_manager/switch_controller \
    controller_manager_msgs/srv/SwitchController \
    "{activate_controllers: [], deactivate_controllers: [neural_controller], strictness: 1, activate_asap: true, timeout: {sec: 3, nanosec: 0}}" \
    >/dev/null 2>&1 || true
}

stop_launch_group() {
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

cleanup() {
  if [[ "${cleanup_done}" -eq 1 ]]; then
    return
  fi
  cleanup_done=1
  trap - EXIT INT TERM

  send_zero
  timeout 3s ros2 topic pub --once /emergency_stop std_msgs/msg/Empty "{}" \
    >/dev/null 2>&1 || true
  deactivate_neural
  stop_launch_group
}

on_signal() {
  echo
  echo "Stop requested; immediately stopping the complete ROS process group."
  cleanup_done=1
  trap - EXIT INT TERM
  stop_launch_group
  exit 130
}

trap cleanup EXIT
trap on_signal INT TERM

if pidof ros2_control_node >/dev/null 2>&1; then
  echo "STOP: ros2_control_node is already running. Do not start a second motor controller."
  exit 1
fi

echo "Starting minimal official walking stack."
echo "Camera, Hailo, joystick, animation, and bag recording are not started."
setsid python3 "${test_dir}/run_official_walk_stack.py" >"${log_file}" 2>&1 &
launch_pid=$!

controller_loaded=0
for _ in $(seq 1 35); do
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    echo "STOP: launch process exited early."
    tail -n 100 "${log_file}"
    exit 1
  fi

  controllers="$(timeout 3s ros2 control list_controllers 2>/dev/null || true)"
  if grep -q "neural_controller" <<<"${controllers}"; then
    controller_loaded=1
    break
  fi
  sleep 1
done

if [[ "${controller_loaded}" -ne 1 ]]; then
  echo "STOP: official neural controller did not load."
  tail -n 100 "${log_file}"
  exit 1
fi

if ! timeout 10s ros2 topic echo --once /joint_states >/dev/null 2>&1; then
  echo "STOP: no valid motor feedback; walking controller was not activated."
  tail -n 100 "${log_file}"
  exit 1
fi

echo "Activating official neural walking controller."
timeout 10s ros2 service call \
  /controller_manager/switch_controller \
  controller_manager_msgs/srv/SwitchController \
  "{activate_controllers: [neural_controller], deactivate_controllers: [], strictness: 2, activate_asap: true, timeout: {sec: 5, nanosec: 0}}" \
  >/dev/null 2>&1 || true

controller_active=0
for _ in $(seq 1 10); do
  controllers="$(timeout 3s ros2 control list_controllers 2>/dev/null || true)"
  if grep -E "neural_controller.*active" <<<"${controllers}" >/dev/null; then
    controller_active=1
    break
  fi
  sleep 1
done

if [[ "${controller_active}" -ne 1 ]]; then
  echo "STOP: neural controller did not become active; no movement command was sent."
  tail -n 100 "${log_file}"
  exit 1
fi

cmd_vel_info="$(timeout 3s ros2 topic info /cmd_vel 2>/dev/null || true)"
if ! grep -Eq "Subscription count: [1-9]" <<<"${cmd_vel_info}"; then
  echo "STOP: neural controller is active but /cmd_vel has no subscriber."
  echo "${cmd_vel_info}"
  exit 1
fi

echo "Verified that /cmd_vel has an active subscriber."
echo "Standing still for 5 seconds before walking."
send_zero
sleep 5

publish_motion() {
  local label="$1"
  local duration="$2"
  local linear_x="$3"
  local angular_z="$4"
  echo "${label}"
  timeout -s INT -k 1s "${duration}" ros2 topic pub -r 20 \
    /cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: ${linear_x}, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: ${angular_z}}}" \
    >/dev/null 2>&1 || true
  send_zero
  sleep 2
}

publish_motion "Walking forward slowly for 4 seconds." 4s 0.25 0.0
publish_motion "Walking backward slowly for 3 seconds." 3s -0.20 0.0
publish_motion "Turning left slowly for 3 seconds." 3s 0.0 0.50

echo "Walking demo finished; stopping and disabling motors."
cleanup
launch_pid=""
echo "Log saved to ${log_file}"
tail -n 80 "${log_file}"
