#!/usr/bin/env python3
"""Standalone single-target follower. Default is no-motion observation mode.

With --execute, replaces (never runs alongside) the old follower/safety filter.
The separate launch file selects that topology. Geometry is NOT biometric ID.
"""
import argparse
import math
import time

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from std_srvs.srv import Trigger
from vision_msgs.msg import Detection2DArray

from single_person_lock import Box, PersonLock


class SinglePersonFollower(Node):
    def __init__(self, execute=False):
        super().__init__("single_person_follower")
        self.execute = execute
        self.lock = PersonLock()
        self.active = False
        self.x = self.yaw = 0.0
        self.last_stamp = None
        self.last_state = None
        self.last_received = None
        self.frame_age = None
        self.person_count = None
        self.last_diagnostic_log = 0.0
        self.status_pub = self.create_publisher(String, "/single_person/status", 10)
        self.velocity_pub = self.create_publisher(Twist, "/person_following_cmd_vel", 1) if execute else None
        self.create_subscription(Detection2DArray, "/detections", self.on_detections, 1)
        # Dry-run mode has its own services and never conflicts with the original.
        activate = "/activate_person_following" if execute else "/single_person_test/activate"
        deactivate = "/deactivate_person_following" if execute else "/single_person_test/deactivate"
        self.create_service(Trigger, activate, self.arm)
        self.create_service(Trigger, deactivate, self.stop)
        self.create_service(Trigger, "/single_person/check", self.check)
        self.create_timer(0.05, self.control)
        self.get_logger().info("EXECUTION mode" if execute else "OBSERVATION ONLY: no velocity publisher")

    def arm(self, request, response):
        if self.active:
            response.success = False
            response.message = "Already armed: stop first before selecting a new target"
            return response
        self.lock.arm()
        self.active = True
        self.last_stamp = None
        self.zero()
        response.success = True
        response.message = "ACQUIRING: stand alone at image centre; movement waits for LOCKED"
        return response

    def stop(self, request, response):
        self.active = False
        self.lock.reset()
        self.zero()
        response.success, response.message = True, "Following stopped; session target cleared"
        return response

    def check(self, request, response):
        self.lock.tick(time.monotonic())
        response.success = self.active and self.lock.state == "LOCKED"
        response.message = self.lock.state + ": " + self.lock.reason
        return response

    def on_detections(self, message):
        if not self.active:
            return
        self.last_received = time.monotonic()
        boxes = []
        for detection in message.detections:
            # Include every person, including low-confidence potential interlopers.
            if any(str(r.hypothesis.class_id) == "0" for r in detection.results):
                b = detection.bbox
                boxes.append(Box(float(b.center.position.x), float(b.center.position.y), float(b.size_x), float(b.size_y)))
        self.person_count = len(boxes)
        stamp = message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec
        age = (self.get_clock().now().nanoseconds - stamp) / 1e9
        self.frame_age = age
        if stamp <= 0 or not -0.05 <= age <= 0.30 or (self.last_stamp is not None and stamp <= self.last_stamp):
            if self.lock.state == "LOCKED":
                self.lock.lose("stale, repeated or out-of-order camera frame")
            else:
                self.lock.arm()
                self.lock.reason = f"invalid camera timestamp: age={age:.3f}s; max=0.30s (also reject repeated frames)"
            self.zero()
            return
        self.last_stamp = stamp
        self.lock.update(boxes, time.monotonic())

    def diagnostic(self):
        if self.last_received is None:
            return "NO /detections received; check camera/Hailo stack and ROS domain"
        age = "?" if self.frame_age is None else f"{self.frame_age:.3f}s"
        gap = time.monotonic() - self.last_received
        return f"people={self.person_count}, camera age={age}, received {gap:.2f}s ago"

    def zero(self):
        self.x = self.yaw = 0.0
        if self.velocity_pub is not None:
            self.velocity_pub.publish(Twist())

    def control(self):
        self.lock.tick(time.monotonic())
        state = self.lock.state
        self.status_pub.publish(String(data=state + ": " + self.lock.reason))
        if state != self.last_state:
            self.get_logger().info(state + ": " + self.lock.reason)
            self.last_state = state
        now = time.monotonic()
        if state == "ACQUIRING" and now - self.last_diagnostic_log >= 2.0:
            self.get_logger().info(self.diagnostic() + " | " + self.lock.reason)
            self.last_diagnostic_log = now
        if not self.active or state != "LOCKED":
            # Immediate zero rather than deceleration after loss/ambiguity.
            self.zero()
            return
        b = self.lock.target
        error = (b.x - 320.0) / 320.0
        desired_yaw = max(-0.25, min(0.25, -0.8 * error)) if abs(error) >= 0.10 else 0.0
        area_error = 0.25 - b.w * b.h / (640.0 * 640.0)
        desired_x = min(0.18, max(0.0, 1.2 * area_error)) if area_error >= 0.06 else 0.0
        if abs(desired_yaw) > 0.10 or abs(self.yaw) > 0.10:
            desired_x = 0.0
        self.x += max(-0.02, min(0.02, desired_x - self.x))
        self.yaw += max(-0.04, min(0.04, desired_yaw - self.yaw))
        if abs(desired_yaw) > 0.10 or abs(self.yaw) > 0.10:
            self.x = 0.0
        if not all(math.isfinite(v) for v in (self.x, self.yaw)):
            self.lock.lose("invalid velocity")
            self.zero()
            return
        if self.velocity_pub is not None:
            command = Twist()
            command.linear.x, command.angular.z = self.x, self.yaw
            self.velocity_pub.publish(command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--preview", action="store_true", help="Show camera and lock diagnostics on the dog's desktop (observation only)")
    args, ros_args = parser.parse_known_args()
    if args.preview and args.execute:
        parser.error("--preview is observation-only; never combine it with --execute")
    if args.preview:
        import os
        if not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
            parser.error("No desktop display. Run this command in the terminal on the dog's screen, not a plain SSH shell.")
    rclpy.init(args=ros_args)
    node = SinglePersonFollower(args.execute)
    if not args.execute:
        node.arm(None, type("Response", (), {})())
    try:
        if args.preview:
            from single_person_preview import SinglePersonPreview
            preview = SinglePersonPreview(node)
            try:
                while rclpy.ok() and preview.running:
                    rclpy.spin_once(node, timeout_sec=0.02)
                    preview.show()
            finally:
                preview.close()
        else:
            rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            node.zero()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
