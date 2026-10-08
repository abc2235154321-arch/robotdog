#!/usr/bin/env python3
import math
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from std_msgs.msg import Float32MultiArray


FORWARD_SPEED_MPS = 0.28
FORWARD_DURATION_SEC = 3.0
STAND_DURATION_SEC = 5.0
COMMAND_VERIFY_SEC = 1.0
PUBLISH_HZ = 20.0
SUBSCRIBER_WAIT_SEC = 8.0


def make_twist(linear_x: float) -> Twist:
    msg = Twist()
    msg.linear.x = linear_x
    msg.linear.y = 0.0
    msg.linear.z = 0.0
    msg.angular.x = 0.0
    msg.angular.y = 0.0
    msg.angular.z = 0.0
    return msg


def publish_for(node, publisher, msg: Twist, duration: float) -> int:
    period = 1.0 / PUBLISH_HZ
    deadline = time.monotonic() + duration
    count = 0
    while rclpy.ok() and time.monotonic() < deadline:
        publisher.publish(msg)
        rclpy.spin_once(node, timeout_sec=0.0)
        count += 1
        time.sleep(period)
    return count


def main() -> int:
    if not math.isfinite(FORWARD_SPEED_MPS) or FORWARD_SPEED_MPS <= 0.0:
        print("STOP: invalid forward speed.", file=sys.stderr)
        return 2

    rclpy.init()
    node = rclpy.create_node("official_straight_only_command")
    publisher = node.create_publisher(Twist, "/cmd_vel", 10)
    latest_observation = {"data": None}

    def observation_callback(msg: Float32MultiArray) -> None:
        latest_observation["data"] = list(msg.data)

    observation_subscription = node.create_subscription(
        Float32MultiArray,
        "/neural_controller/observation",
        observation_callback,
        10,
    )

    try:
        deadline = time.monotonic() + SUBSCRIBER_WAIT_SEC
        while rclpy.ok() and publisher.get_subscription_count() < 1:
            if time.monotonic() >= deadline:
                print("STOP: /cmd_vel subscriber was not discovered.", file=sys.stderr)
                return 3
            rclpy.spin_once(node, timeout_sec=0.1)

        print(
            f"Connected to {publisher.get_subscription_count()} /cmd_vel subscriber(s).",
            flush=True,
        )

        zero = make_twist(0.0)
        forward = make_twist(FORWARD_SPEED_MPS)

        print(
            f"STAND PHASE: holding zero velocity for {STAND_DURATION_SEC:.1f} seconds.",
            flush=True,
        )
        stand_sent = publish_for(
            node, publisher, zero, STAND_DURATION_SEC
        )
        print(
            f"Standing command stable ({stand_sent} zero-velocity messages sent).",
            flush=True,
        )
        print(
            f"Publishing straight forward: x={FORWARD_SPEED_MPS:.2f} m/s, "
            "y=0.00, yaw=0.00 for 3.0 seconds.",
            flush=True,
        )
        sent = publish_for(node, publisher, forward, COMMAND_VERIFY_SEC)

        observation = latest_observation["data"]
        if observation is None or len(observation) < 9:
            publish_for(node, publisher, zero, 1.0)
            print(
                "STOP: no usable /neural_controller/observation was received; "
                "zero velocity sent.",
                file=sys.stderr,
                flush=True,
            )
            return 4

        observed_x = observation[6]
        observed_y = observation[7]
        observed_yaw = observation[8]
        if abs(observed_x - FORWARD_SPEED_MPS) > 0.05:
            publish_for(node, publisher, zero, 1.0)
            print(
                f"STOP: controller read x={observed_x:.3f}, expected "
                f"{FORWARD_SPEED_MPS:.3f}; zero velocity sent.",
                file=sys.stderr,
                flush=True,
            )
            return 5

        print(
            f"CONTROLLER COMMAND VERIFIED: observation x={observed_x:.2f}, "
            f"y={observed_y:.2f}, yaw={observed_yaw:.2f}.",
            flush=True,
        )
        sent += publish_for(
            node,
            publisher,
            forward,
            FORWARD_DURATION_SEC - COMMAND_VERIFY_SEC,
        )
        publish_for(node, publisher, zero, 1.0)
        print(f"Published {sent} forward messages; zero velocity sent.", flush=True)
        return 0
    except KeyboardInterrupt:
        publish_for(node, publisher, make_twist(0.0), 0.5)
        print("Interrupted; zero velocity sent.", flush=True)
        return 130
    finally:
        del observation_subscription
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())


