#!/usr/bin/env bash
# Fixed robot actions for voice_remote_qwen_dry_run.py.
# Uses an already initialized person-follow stack; never launches a controller.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u

# Match the new launcher's isolated ROS compatibility environment when present.
# The voice venv and global NumPy installation remain unchanged.
compat_dir=/home/pi/pupper-tests/ros-numpy1
if [[ -f "${compat_dir}/numpy/__init__.py" ]]; then
  export PYTHONPATH="${compat_dir}:${PYTHONPATH:-}"
fi

action="${1:-}"
case "${action}" in
  CHECK|STAND|FOLLOW|STOP) ;;
  *) echo 'Rejected: action must be CHECK, STAND, FOLLOW or STOP.'; exit 2 ;;
esac

require_controller() {
  local controllers
  controllers="$(timeout 5s ros2 control list_controllers 2>&1)" || {
    echo 'Controller manager is unavailable.'; return 1;
  }
  # ros2controlcli wraps names and states in ANSI color escapes, even in pipes.
  # Strip those before matching the exact state (never match "inactive").
  controllers="$(printf '%s\n' "${controllers}" | sed $'s/\033\\[[0-9;]*m//g')"
  if ! grep -Eq 'neural_controller[[:space:]].*[[:space:]]active([[:space:]]|$)' <<<"${controllers}"; then
    echo 'neural_controller is not active. Prepare the existing safe follow stack first.'
    return 1
  fi
}

check_ready() {
  require_controller || return 1
  if ! timeout 5s ros2 service type /single_person/check | grep -qx 'std_srvs/srv/Trigger'; then
    echo "Single-person node is missing; refusing the ordinary follower."; return 1
  fi
  for service in /activate_person_following /deactivate_person_following; do
    if ! timeout 5s ros2 service type "${service}" | grep -qx 'std_srvs/srv/Trigger'; then
      echo "Missing person-follow service: ${service}"; return 1
    fi
  done
  if ! timeout 8s ros2 topic echo --once /joint_states >/dev/null 2>&1; then
    echo 'No joint feedback; refusing movement.'; return 1
  fi
}

stop_following() {
  local response service_ok=0 zero_ok=0
  response="$(timeout 6s ros2 service call /deactivate_person_following std_srvs/srv/Trigger '{}' 2>&1 || true)"
  echo "${response}"
  if grep -Eqi 'success[=:[:space:]]+[Tt]rue' <<<"${response}"; then
    service_ok=1
  fi
  # Attempt zeros even when the service did not confirm deactivation.
  for _ in 1 2 3; do
    if timeout 3s ros2 topic pub --once /person_following_cmd_vel geometry_msgs/msg/Twist \
      '{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}' >/dev/null 2>&1; then
      zero_ok=1
    fi
  done
  if (( service_ok != 1 || zero_ok != 1 )); then
    echo 'STOP was attempted but not fully confirmed. Use the existing manual stop/power switch.'
    return 1
  fi
}

case "${action}" in
  CHECK)
    check_ready
    test -f /home/pi/pupper-tests/start_single_person_following_safe.sh
    echo 'ROBOT_READY: initialized controller and follow services found.'
    ;;
  FOLLOW)
    check_ready
    # Keep the existing person-detection verification and countdown.
    bash /home/pi/pupper-tests/start_single_person_following_safe.sh
    ;;
  STOP)
    stop_following
    echo 'STOP_CONFIRMED: following deactivated; motors are not powered off.'
    ;;
  STAND)
    stop_following
    require_controller
    echo 'STAND_CONFIRMED: following deactivated and stand controller remains active.'
    ;;
esac
