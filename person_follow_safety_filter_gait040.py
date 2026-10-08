#!/usr/bin/env python3
"""Safety filter for the official Pupper V3 person follower.

The official follower publishes raw commands on
``/person_following_raw_cmd_vel``.  This node applies conservative limits,
turns before moving forward, forbids automatic reverse motion, and publishes
the accepted command on ``/person_following_cmd_vel`` for the official mux.
"""

import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException


OUTPUT_HZ = 20.0
RAW_TIMEOUT_SEC = 0.35
FORWARD_GAIT_MPS = 0.40
MAX_YAW_RAD_S = 0.30
TURN_BEFORE_FORWARD_RAD_S = 0.22
MAX_FORWARD_ACCEL_MPS2 = 0.40
MAX_YAW_ACCEL_RAD_S2 = 0.80


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def approach(current: float, target: float, maximum_step: float) -> float:
    return current + clamp(target - current, -maximum_step, maximum_step)


class PersonFollowSafetyFilter(Node):
    def __init__(self) -> None:
        super().__init__("person_follow_safety_filter")
        self.publisher = self.create_publisher(
            Twist, "/person_following_cmd_vel", 10
        )
        self.subscription = self.create_subscription(
            Twist,
            "/person_following_raw_cmd_vel",
            self.raw_command_callback,
            10,
        )
        self.latest_raw = Twist()
        self.latest_raw_time = None
        self.output_x = 0.0
        self.output_yaw = 0.0
        self.last_status_time = 0.0
        self.timer = self.create_timer(1.0 / OUTPUT_HZ, self.control_tick)
        self.get_logger().info(
            "Safety filter ready: forward gait=0.40 m/s, yaw<=0.30 rad/s, "
            "no reverse, stale target stops in 0.35 s"
        )

    def raw_command_callback(self, msg: Twist) -> None:
        values = (msg.linear.x, msg.linear.y, msg.angular.z)
        if not all(math.isfinite(value) for value in values):
            self.get_logger().error("Rejected non-finite person-follow command")
            return
        self.latest_raw = msg
        self.latest_raw_time = time.monotonic()

    def control_tick(self) -> None:
        now = time.monotonic()
        fresh = (
            self.latest_raw_time is not None
            and now - self.latest_raw_time <= RAW_TIMEOUT_SEC
        )

        desired_x = 0.0
        desired_yaw = 0.0
        state = "NO FOLLOW COMMAND / STOP"

        if fresh:
            desired_yaw = clamp(
                self.latest_raw.angular.z,
                -MAX_YAW_RAD_S,
                MAX_YAW_RAD_S,
            )
            # This robot's official neural gait did not produce useful loaded
            # motion below roughly 0.40 m/s.  Treat any positive follower
            # request as the known-working 0.40 m/s gait command.  Zero and
            # negative requests still stop; automatic reverse stays disabled.
            desired_x = (
                FORWARD_GAIT_MPS if self.latest_raw.linear.x > 0.0 else 0.0
            )
            if abs(desired_yaw) > TURN_BEFORE_FORWARD_RAD_S:
                desired_x = 0.0
                state = "TURNING"
            elif desired_x > 0.0:
                state = "FOLLOWING GAIT 0.40"
            else:
                state = "DISTANCE OK / STAND"

        period = 1.0 / OUTPUT_HZ
        self.output_x = approach(
            self.output_x,
            desired_x,
            MAX_FORWARD_ACCEL_MPS2 * period,
        )
        self.output_yaw = approach(
            self.output_yaw,
            desired_yaw,
            MAX_YAW_ACCEL_RAD_S2 * period,
        )

        output = Twist()
        output.linear.x = self.output_x
        output.angular.z = self.output_yaw
        self.publisher.publish(output)

        if now - self.last_status_time >= 1.0:
            self.get_logger().info(
                f"{state}: x={self.output_x:.2f} m/s, "
                f"yaw={self.output_yaw:.2f} rad/s, "
                f"raw_x={self.latest_raw.linear.x:.2f}, "
                f"raw_yaw={self.latest_raw.angular.z:.2f}"
            )
            self.last_status_time = now

    def publish_stop(self) -> None:
        stop = Twist()
        for _ in range(5):
            self.publisher.publish(stop)
            time.sleep(0.05)


def main() -> None:
    rclpy.init()
    node = PersonFollowSafetyFilter()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            node.publish_stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
