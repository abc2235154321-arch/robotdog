#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u

controllers="$(timeout 3s ros2 control list_controllers 2>/dev/null || true)"
if ! grep -E "neural_controller.*active" <<<"${controllers}" >/dev/null; then
  echo "STOP: neural_controller is not active. Start run_official_person_follow_safe.sh first."
  exit 1
fi

camera_info="$(timeout 3s ros2 topic info /camera/image_raw 2>/dev/null || true)"
detection_info="$(timeout 3s ros2 topic info /detections 2>/dev/null || true)"
if ! grep -Eq "Publisher count: [1-9]" <<<"${camera_info}" \
  || ! grep -Eq "Publisher count: [1-9]" <<<"${detection_info}"; then
  echo "STOP: camera or Hailo detection is not ready."
  exit 1
fi

if ! timeout 3s ros2 service type /activate_person_following \
  | grep -q "std_srvs/srv/Trigger"; then
  echo "STOP: person-following service is unavailable."
  exit 1
fi

echo "Place the robot on a clear floor and stand about 1.5 to 2 metres in front."
echo "Keep one hand near the physical power switch."

if ! timeout 15s python3 /home/pi/pupper-tests/verify_person_detection.py \
  --seconds 12 --required 3; then
  echo "STOP: Hailo did not see a person consistently."
  echo "Show most of your body in good light, then run this command again."
  exit 1
fi

for count in 5 4 3 2 1; do
  echo "Following starts in ${count}..."
  sleep 1
done

response="$(timeout 5s ros2 service call \
  /activate_person_following std_srvs/srv/Trigger "{}" 2>&1 || true)"
echo "${response}"
if ! grep -qi "success.*true" <<<"${response}"; then
  echo "STOP: activation was not confirmed."
  exit 1
fi

echo "Person following is ACTIVE."
echo "To stop motion while keeping the robot standing:"
echo "  ~/pupper-tests/stop_person_following_safe.sh"
