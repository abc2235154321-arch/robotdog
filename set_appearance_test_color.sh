#!/usr/bin/env bash
# Fixed observation-only target request. Never invokes robot action services.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u
color="${1:-}"
case "${color}" in
  CHECK|red|orange|yellow|green|blue|purple|black|white|gray) ;;
  *) echo 'Unsupported observation colour.'; exit 2 ;;
esac
if ! timeout 5s ros2 service type /appearance_test/check | grep -qx 'std_srvs/srv/Trigger'; then
  echo 'Appearance observer is not running. No request sent.'; exit 1
fi
if [[ "${color}" == CHECK ]]; then
  echo 'APPEARANCE_OBSERVER_OK (no motion or target request)'; exit 0
fi
timeout 6s ros2 topic pub --once /appearance_test/target_color std_msgs/msg/String "{data: '${color}'}"
echo "OBSERVATION_REQUEST_SENT: ${color}; check the screen for the received target. NO MOTOR ACTION."
