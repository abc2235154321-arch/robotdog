#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u

max_seconds="${1:-180}"
follow_variant="${PUPPER_FOLLOW_VARIANT:-single}"
case "${follow_variant}" in
  single)
    stack_runner=run_single_person_follow_stack.py
    activate_service=/activate_person_following
    deactivate_service=/deactivate_person_following
    start_instruction='~/pupper-tests/start_single_person_following_safe.sh'
    ;;
  appearance)
    stack_runner=run_appearance_follow_stack.py
    activate_service=/appearance_follow/activate
    deactivate_service=/appearance_follow/deactivate
    start_instruction='Voice: --appearance-follow --execute (explicit shirt colour + typed y required)'
    ;;
  *) echo 'STOP: unsupported follow variant.'; exit 2 ;;
esac
if ! [[ "${max_seconds}" =~ ^[0-9]+$ ]] \
  || (( max_seconds < 30 || max_seconds > 600 )); then
  echo "Usage: $0 [max_seconds]"
  echo "max_seconds must be between 30 and 600; default is 180."
  exit 2
fi

test_dir=/home/pi/pupper-tests
log_dir="${test_dir}/logs"
mkdir -p "${log_dir}"
log_file="${log_dir}/person_follow_$(date +%Y%m%d_%H%M%S).log"
launch_pid=""
cleanup_done=0

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

publish_zero() {
  timeout 3s ros2 topic pub --once /person_following_cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" \
    >/dev/null 2>&1 || true
  timeout 3s ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" \
    >/dev/null 2>&1 || true
}

deactivate_following() {
  timeout 4s ros2 service call \
    "${deactivate_service}" std_srvs/srv/Trigger "{}" \
    >/dev/null 2>&1 || true
  publish_zero
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
  deactivate_following
  timeout 3s ros2 topic pub --once /emergency_stop std_msgs/msg/Empty "{}" \
    >/dev/null 2>&1 || true
  deactivate_neural
  stop_launch_group
  stop_owned_vision_processes
}

on_signal() {
  echo
  echo "Stop requested; stopping person following and the complete ROS group."
  cleanup
  exit 130
}


if pidof ros2_control_node >/dev/null 2>&1; then
  echo "STOP: ros2_control_node is already running. Do not start a second motor controller."
  exit 1
fi

if pgrep -f '/hailo/lib/hailo/hailo_detection' >/dev/null 2>&1 \
  || pgrep -f '/camera_ros/lib/camera_ros/camera_node' >/dev/null 2>&1; then
  echo "STOP: an older camera/Hailo process is already running."
  echo "Do not start a second vision stack; stop the older process first."
  exit 1
fi

trap cleanup EXIT
trap on_signal INT TERM

echo "Starting official camera, Hailo detection, neural controller, and person follower."
echo "Mode: ${follow_variant}; following remains INACTIVE until explicitly armed."
setsid python3 -u "${test_dir}/${stack_runner}" >"${log_file}" 2>&1 &
launch_pid=$!

# The hardware interface exposes ROS entities before mechanical-stop homing is
# complete.  Never stand or follow until all 12 actuator confirmations from
# this exact launch are present in its log.
echo "CALIBRATION PHASE: waiting for the official 12-motor homing sequence."
homing_finished=0
for _ in $(seq 1 120); do
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    echo "STOP: launch process exited before homing completed."
    tail -n 120 "${log_file}"
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
  echo "Person following was not activated."
  tail -n 120 "${log_file}"
  exit 1
fi

homed_count="$(
  grep -aoE 'Homed actuator [0-9]+' "${log_file}" \
    | sort -u \
    | wc -l \
    | tr -d '[:space:]'
)"
if [[ "${homed_count}" != "12" ]]; then
  echo "STOP: only ${homed_count}/12 unique actuators were confirmed."
  echo "Person following was not activated."
  tail -n 120 "${log_file}"
  exit 1
fi
echo "CALIBRATION COMPLETE: verified 12/12 actuators and 'Finished homing!'."

controller_loaded=0
for _ in $(seq 1 45); do
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    echo "STOP: launch process exited early."
    tail -n 120 "${log_file}"
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
  tail -n 120 "${log_file}"
  exit 1
fi

if ! timeout 12s ros2 topic echo --once /joint_states >/dev/null 2>&1; then
  echo "STOP: no valid motor feedback; the walking controller was not activated."
  tail -n 120 "${log_file}"
  exit 1
fi

vision_ready=0
for _ in $(seq 1 35); do
  camera_info="$(timeout 3s ros2 topic info /camera/image_raw 2>/dev/null || true)"
  detection_info="$(timeout 3s ros2 topic info /detections 2>/dev/null || true)"
  if grep -Eq "Publisher count: [1-9]" <<<"${camera_info}" \
    && grep -Eq "Publisher count: [1-9]" <<<"${detection_info}"; then
    vision_ready=1
    break
  fi
  sleep 1
done

if [[ "${vision_ready}" -ne 1 ]]; then
  echo "STOP: camera or Hailo detection did not become ready."
  tail -n 160 "${log_file}"
  exit 1
fi

if ! timeout 15s ros2 topic echo --once /detections >/dev/null 2>&1; then
  echo "STOP: Hailo node exists but no detection messages are arriving."
  tail -n 160 "${log_file}"
  exit 1
fi
echo "VISION READY: camera and Hailo detection messages verified."

if [[ "${follow_variant}" == appearance ]]; then
  if ! timeout 6s ros2 service type /appearance_follow/ready | grep -qx 'std_srvs/srv/Trigger'; then
    echo 'STOP: appearance follower is missing; refusing ordinary follow fallback.'
    tail -n 120 "${log_file}"
    exit 1
  fi
fi

if ! timeout 5s ros2 service type "${activate_service}" \
  | grep -q "std_srvs/srv/Trigger"; then
  echo "STOP: ${activate_service} is unavailable; mode=${follow_variant}."
  tail -n 120 "${log_file}"
  exit 1
fi

echo "Activating the official neural walking controller (includes startup calibration)."
timeout 10s ros2 service call \
  /controller_manager/switch_controller \
  controller_manager_msgs/srv/SwitchController \
  "{activate_controllers: [neural_controller], deactivate_controllers: [], strictness: 2, activate_asap: true, timeout: {sec: 5, nanosec: 0}}" \
  >/dev/null 2>&1 || true

controller_active=0
for _ in $(seq 1 12); do
  controllers="$(timeout 3s ros2 control list_controllers 2>/dev/null || true)"
  controllers="$(printf '%s\n' "${controllers}" | sed $'s/\033\\[[0-9;]*m//g')"
  if grep -Eq 'neural_controller[[:space:]].*[[:space:]]active([[:space:]]|$)' <<<"${controllers}"; then
    controller_active=1
    break
  fi
  sleep 1
done

if [[ "${controller_active}" -ne 1 ]]; then
  echo "STOP: neural controller did not become active."
  tail -n 120 "${log_file}"
  exit 1
fi

publish_zero
echo
echo "READY: robot is standing, but person following is still inactive."
echo "In a SECOND VS Code terminal, start following with:"
echo "  ${start_instruction}"
echo "Stop only the following motion with:"
echo "  ~/pupper-tests/stop_person_following_safe.sh"
echo "Press Ctrl+C in THIS terminal to stop the complete stack."
echo "Automatic complete shutdown in ${max_seconds} seconds."

for _ in $(seq 1 "${max_seconds}"); do
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    echo "STOP: ROS launch process exited unexpectedly."
    tail -n 160 "${log_file}"
    exit 1
  fi
  sleep 1
done

echo "Maximum runtime reached; stopping."
cleanup
launch_pid=""
echo "Log saved to ${log_file}"
