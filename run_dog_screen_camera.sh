#!/usr/bin/env bash
set -u

export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-0
export QT_QPA_PLATFORM=wayland

if [[ ! -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]]; then
  echo "STOP: the Pupper Wayland screen session is not available."
  exit 1
fi

if pgrep -f '/camera_ros/lib/camera_ros/camera_node' >/dev/null 2>&1 \
  || pgrep -x rpicam-hello >/dev/null 2>&1 \
  || pgrep -x rpicam-vid >/dev/null 2>&1; then
  echo "STOP: the camera is already in use. Stop the older camera process first."
  exit 1
fi

echo "Showing the live camera fullscreen on the Pupper display."
echo "No ROS or motor controller will be started."
echo "Press Ctrl+C to close the camera view."

exec rpicam-hello \
  --qt-preview \
  --preview 0,0,720,720 \
  --timeout 0 \
  --framerate 20
