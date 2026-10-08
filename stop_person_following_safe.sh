#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash
source /home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash
set -u

timeout 4s ros2 service call \
  /deactivate_person_following std_srvs/srv/Trigger "{}" \
  >/dev/null 2>&1 || true

for _ in $(seq 1 5); do
  timeout 2s ros2 topic pub --once \
    /person_following_cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" \
    >/dev/null 2>&1 || true
done

echo "Person following is inactive; the robot should remain standing."
echo "Press Ctrl+C in the main person-follow terminal to shut down the complete stack."
