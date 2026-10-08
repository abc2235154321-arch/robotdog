#!/usr/bin/env bash
# Fixed colour/control whitelist. Never launches a controller or falls back.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u
compat_dir=/home/pi/pupper-tests/ros-numpy1
if [[ -f "${compat_dir}/numpy/__init__.py" ]]; then
  export PYTHONPATH="${compat_dir}:${PYTHONPATH:-}"
fi
action="${1:-}"
case "${action}" in
  CHECK|STOP|STAND) ;;
  FOLLOW_red|FOLLOW_orange|FOLLOW_yellow|FOLLOW_green|FOLLOW_blue|FOLLOW_purple|FOLLOW_black|FOLLOW_white|FOLLOW_gray) ;;
  SELECT_red|SELECT_orange|SELECT_yellow|SELECT_green|SELECT_blue|SELECT_purple|SELECT_black|SELECT_white|SELECT_gray) ;;
  *) echo 'STOP: explicit whitelisted shirt colour required; no ordinary FOLLOW.'; exit 2 ;;
esac

call_ok() {
  local response
  response="$(timeout 6s ros2 service call "$1" std_srvs/srv/Trigger '{}' 2>&1)" || return 1
  echo "${response}"
  grep -Eqi 'success[=:[:space:]]+[Tt]rue' <<<"${response}"
}

require_ready() {
  local controllers service_type topic_info
  controllers="$(timeout 5s ros2 control list_controllers 2>&1)" || return 1
  controllers="$(printf '%s\n' "${controllers}" | sed $'s/\033\\[[0-9;]*m//g')"
  if ! grep -Eq 'neural_controller[[:space:]].*[[:space:]]active([[:space:]]|$)' <<<"${controllers}"; then
    echo 'STOP: neural_controller is not active.'; return 1
  fi
  service_type="$(timeout 5s ros2 service type /appearance_follow/ready 2>&1)" || {
    echo "${service_type}"
    echo 'STOP: cannot query appearance readiness service.'; return 1
  }
  if ! grep -qx 'std_srvs/srv/Trigger' <<<"${service_type}"; then
    echo 'STOP: wrong stack or appearance node missing; no ordinary fallback.'; return 1
  fi
  call_ok /appearance_follow/ready || { echo 'STOP: no fresh synchronized colour geometry.'; return 1; }
  # Consume the COMPLETE ros2 output before grep -q. Otherwise grep exits after
  # the count line and ros2's later writes raise BrokenPipe under pipefail.
  # Keep the producer's exit status: partial matching output is NOT readiness.
  topic_info="$(timeout 5s ros2 topic info /person_following_cmd_vel 2>&1)" || {
    echo "${topic_info}"
    echo 'STOP: cannot query follow velocity publishers.'; return 1
  }
  if ! grep -Eq '^Publisher count: 1[[:space:]]*$' <<<"${topic_info}"; then
    echo "${topic_info}"
    echo 'STOP: expected exactly one follow velocity publisher; possible competing controller.'; return 1
  fi
  timeout 8s ros2 topic echo --once /joint_states >/dev/null 2>&1 || {
    echo 'STOP: no joint feedback.'; return 1;
  }
}

stop_following() {
  local service_ok=0 zero_ok=0
  if call_ok /appearance_follow/deactivate; then service_ok=1; fi
  for _ in 1 2 3; do
    if timeout 3s ros2 topic pub --once /person_following_cmd_vel geometry_msgs/msg/Twist \
      '{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}' >/dev/null 2>&1; then zero_ok=1; fi
  done
  if (( service_ok != 1 || zero_ok != 1 )); then
    echo 'STOP not fully confirmed; use the manual/physical stop.'; return 1
  fi
}

case "${action}" in
  STOP) stop_following; echo 'STOP_CONFIRMED: inactive; motors still powered.'; exit 0 ;;
  STAND) stop_following; require_ready; echo 'STAND_CONFIRMED: follow inactive; controller active.'; exit 0 ;;
  CHECK) require_ready; echo 'APPEARANCE_ROBOT_READY: fresh images + active controller; no action sent.'; exit 0 ;;
esac

confirmed=0
cleanup() {
  if (( confirmed == 0 )); then stop_following || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP
stop_following
require_ready
color="${action#*_}"
call_ok "/appearance_follow/select_${color}" || { echo 'Colour selection rejected.'; exit 1; }
if [[ "${action}" == SELECT_* ]]; then
  confirmed=1
  echo "COLOUR_SELECTED: ${color}; movement remains INACTIVE."
  exit 0
fi
echo "Follow shirt=${color}. Keep the controlled test area clear; have a manual stop ready."
for count in 5 4 3 2 1; do echo "Arming in ${count}..."; sleep 1; done
require_ready
call_ok /appearance_follow/activate || { echo 'Arm rejected.'; exit 1; }
for _ in $(seq 1 12); do
  response="$(timeout 2s ros2 service call /appearance_follow/check std_srvs/srv/Trigger '{}' 2>&1 || true)"
  echo "${response}"
  if grep -Eqi 'success[=:[:space:]]+[Tt]rue' <<<"${response}"; then
    confirmed=1
    echo "TARGET_LOCKED: ${color}; appearance following active."
    exit 0
  fi
  if grep -q 'LOST:' <<<"${response}"; then echo "STOP: ${response}"; exit 1; fi
  sleep 0.2
done
echo 'STOP: could not confirm unique stable colour target; deactivating.'
exit 1
