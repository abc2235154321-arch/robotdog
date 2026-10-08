#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u

test_dir=/home/pi/pupper-tests
log_dir="${test_dir}/logs"
mkdir -p "${log_dir}"
log_file="${log_dir}/straight_028_$(date +%Y%m%d_%H%M%S).log"
launch_pid=""
cleanup_done=0

send_zero() {
  timeout 3s ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" \
    >/dev/null 2>&1 || true
}

send_emergency_stop() {
  timeout 3s ros2 topic pub --once /emergency_stop std_msgs/msg/Empty "{}" \
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
  send_emergency_stop
  deactivate_neural
  stop_launch_group
}

on_signal() {
  echo
  echo "Stop requested; sending zero velocity and stopping the ROS process group."
  cleanup
  exit 130
}

trap cleanup EXIT
trap on_signal INT TERM

if pidof ros2_control_node >/dev/null 2>&1; then
  echo "STOP: ros2_control_node is already running. Do not start a second motor controller."
  exit 1
fi

echo "Starting the minimal official Pupper V3 walking controller."
echo "Using the official logical joint map; physical cables remain right=CAN1/3 and left=CAN2/4."
echo "This test contains only one straight-forward command; yaw is always zero."
echo "Camera, Hailo, joystick, animation, and bag recording are not started."
setsid python3 -u "${test_dir}/run_official_walk_stack.py" >"${log_file}" 2>&1 &
launch_pid=$!

# Do not trust controller discovery alone: the official hardware interface can
# already expose ROS entities while its mechanical-stop homing is still in
# progress.  Walking is forbidden until the official completion message and
# all 12 per-actuator confirmations have been observed in this run's log.
echo "CALIBRATION PHASE: waiting for the official 12-motor homing sequence."
homing_finished=0
for _ in $(seq 1 120); do
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    echo "STOP: launch process exited before homing completed."
    tail -n 100 "${log_file}"
    exit 1
  fi

  if grep -aFq "Finished homing!" "${log_file}"; then
    homing_finished=1
    break
  fi
  sleep 1
done

if [[ "${homing_finished}" -ne 1 ]]; then
  echo "STOP: official homing did not finish within 120 seconds."
  echo "No stand or walking command was sent."
  tail -n 100 "${log_file}"
  exit 1
fi

homed_count="$(
  grep -aoE 'Homed actuator [0-9]+' "${log_file}" \
    | sort -u \
    | wc -l \
    | tr -d '[:space:]'
)"
if [[ "${homed_count}" != "12" ]]; then
  echo "STOP: homing completion was logged, but only ${homed_count}/12 unique actuators were confirmed."
  echo "No stand or walking command was sent."
  tail -n 100 "${log_file}"
  exit 1
fi
echo "CALIBRATION COMPLETE: verified 12/12 actuators and 'Finished homing!'."

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

joint_snapshot="$(timeout 10s ros2 topic echo --once /joint_states 2>/dev/null || true)"
if [[ -z "${joint_snapshot}" ]]; then
  echo "STOP: no motor feedback; the walking controller was not activated."
  tail -n 100 "${log_file}"
  exit 1
fi

expected_joints=(
  leg_front_r_1 leg_front_r_2 leg_front_r_3
  leg_front_l_1 leg_front_l_2 leg_front_l_3
  leg_back_r_1 leg_back_r_2 leg_back_r_3
  leg_back_l_1 leg_back_l_2 leg_back_l_3
)

missing_joint=0
for joint in "${expected_joints[@]}"; do
  if ! grep -Fq "${joint}" <<<"${joint_snapshot}"; then
    echo "STOP: missing joint feedback name: ${joint}"
    missing_joint=1
  fi
done
if [[ "${missing_joint}" -ne 0 ]]; then
  echo "No movement command was sent."
  exit 1
fi
if grep -Eiq '(^|[^[:alpha:]])(nan|inf)([^[:alpha:]]|$)' <<<"${joint_snapshot}"; then
  echo "STOP: joint feedback contains NaN or Inf. No movement command was sent."
  exit 1
fi

echo "Verified all 12 official joint names in /joint_states."
echo "Activating the official neural walking controller."
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

echo "Controller ready. The command publisher will hold a visible zero-velocity standing phase before walking."
echo "STRAIGHT TEST: using a persistent publisher that waits for the controller subscriber."
if ! python3 "${test_dir}/publish_official_straight_028_cmd.py"; then
  echo "STOP: the verified straight command publisher failed."
  exit 1
fi

send_zero
echo "Straight test finished; stopping and disabling the controller."
cleanup
launch_pid=""
echo "Log saved to ${log_file}"
tail -n 80 "${log_file}"


