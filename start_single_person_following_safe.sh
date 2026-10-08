#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u
controllers="$(timeout 5s ros2 control list_controllers 2>&1)"
controllers="$(printf '%s\n' "${controllers}" | sed $'s/\033\\[[0-9;]*m//g')"
if ! grep -Eq 'neural_controller[[:space:]].*[[:space:]]active([[:space:]]|$)' <<<"${controllers}"; then
  echo 'STOP: neural controller is not active.'; exit 1
fi
if ! timeout 5s ros2 service type /single_person/check | grep -qx 'std_srvs/srv/Trigger'; then
  echo 'STOP: single-person follower is not running.'; exit 1
fi
echo 'Stand ALONE near the camera centre, about 1.5-2 metres away.'
echo 'Loss/overlap latches STOP; a new session requires stopping and re-arming.'
for count in 5 4 3 2 1; do echo "Arming in ${count}..."; sleep 1; done
confirmed=0
cleanup() {
  if (( confirmed == 0 )); then
    timeout 5s ros2 service call /deactivate_person_following std_srvs/srv/Trigger '{}' >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
response="$(timeout 5s ros2 service call /activate_person_following std_srvs/srv/Trigger '{}' 2>&1)"
echo "${response}"
if ! grep -Eqi 'success[=:[:space:]]+[Tt]rue' <<<"${response}"; then
  echo 'STOP: arm request was not accepted.'; exit 1
fi
for _ in $(seq 1 12); do
  response="$(timeout 2s ros2 service call /single_person/check std_srvs/srv/Trigger '{}' 2>&1 || true)"
  if grep -Eqi 'success[=:[:space:]]+[Tt]rue' <<<"${response}"; then
    confirmed=1
    echo 'TARGET_LOCKED: single-person following is active.'
    exit 0
  fi
  if grep -q 'LOST:' <<<"${response}"; then
    echo "STOP: ${response}"; exit 1
  fi
  sleep 0.2
done
echo 'STOP: could not confirm one stable target; following deactivated.'
exit 1
