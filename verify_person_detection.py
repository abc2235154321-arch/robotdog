#!/usr/bin/env python3
"""Require several recent Hailo person detections before enabling motion."""

import argparse
from datetime import datetime
from pathlib import Path
import sys
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from vision_msgs.msg import Detection2DArray


IMAGE_WIDTH = 640.0
IMAGE_AREA = 640.0 * 640.0
MIN_START_AREA_RATIO = 0.08
MAX_START_AREA_RATIO = 0.45
MAX_START_CENTER_ERROR = 0.50


class PersonDetectionVerifier(Node):
    def __init__(self, seconds: float, required: int, save_dir: str) -> None:
        super().__init__("person_detection_verifier")
        self.deadline = time.monotonic() + seconds
        self.required = required
        self.person_frames = 0
        self.person_seen_frames = 0
        self.total_frames = 0
        self.best_score = 0.0
        self.last_report = 0.0
        self.success = False
        self.save_dir = Path(save_dir)
        self.latest_annotated_image = None
        self.subscription = self.create_subscription(
            Detection2DArray, "/detections", self.on_detections, 10
        )
        self.image_subscription = self.create_subscription(
            CompressedImage,
            "/annotated_image",
            self.on_annotated_image,
            10,
        )
        self.timer = self.create_timer(0.1, self.on_timer)

    def on_annotated_image(self, message: CompressedImage) -> None:
        self.latest_annotated_image = bytes(message.data)

    def save_evidence_image(self, label: str) -> None:
        if not self.latest_annotated_image:
            print("NOTE: no annotated frame was available to save.", flush=True)
            return
        self.save_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self.save_dir / f"{label}_{stamp}.jpg"
        output_path.write_bytes(self.latest_annotated_image)
        print(f"Saved verification image: {output_path}", flush=True)

    def on_detections(self, message: Detection2DArray) -> None:
        self.total_frames += 1
        people = []
        for detection in message.detections:
            for result in detection.results:
                if str(result.hypothesis.class_id) == "0":
                    people.append(detection)
                    self.best_score = max(
                        self.best_score, float(result.hypothesis.score)
                    )
                    break

        if people:
            self.person_seen_frames += 1
            best = max(
                people,
                key=lambda item: float(item.bbox.size_x) * float(item.bbox.size_y),
            )
            center_x = float(best.bbox.center.position.x)
            area = float(best.bbox.size_x) * float(best.bbox.size_y)
            area_ratio = area / IMAGE_AREA
            center_error = abs(center_x - IMAGE_WIDTH / 2.0) / (IMAGE_WIDTH / 2.0)

            if area_ratio > MAX_START_AREA_RATIO:
                print(
                    "PERSON TOO CLOSE: "
                    f"area={area_ratio:.2f}; step farther from the camera.",
                    flush=True,
                )
                return
            if area_ratio < MIN_START_AREA_RATIO:
                print(
                    "PERSON TOO FAR: "
                    f"area={area_ratio:.2f}; step closer to the camera.",
                    flush=True,
                )
                return
            if center_error > MAX_START_CENTER_ERROR:
                direction = "right" if center_x < IMAGE_WIDTH / 2.0 else "left"
                print(
                    f"MOVE {direction.upper()}: person is too close to the image edge.",
                    flush=True,
                )
                return

            self.person_frames += 1
            print(
                "PERSON FRAME "
                f"{self.person_frames}/{self.required}: "
                f"people={len(people)}, center_x={center_x:.1f}, "
                f"area={area_ratio:.2f}, best_score={self.best_score:.3f}",
                flush=True,
            )
            if self.person_frames >= self.required:
                self.success = True
                print("PERSON VERIFIED: stable detections received.", flush=True)
                self.save_evidence_image("verified_person")
                rclpy.shutdown()
        else:
            now = time.monotonic()
            if now - self.last_report >= 1.0:
                remaining = max(0.0, self.deadline - now)
                print(
                    "WAITING FOR PERSON: "
                    f"frames={self.total_frames}, time_left={remaining:.1f}s",
                    flush=True,
                )
                self.last_report = now

    def on_timer(self) -> None:
        if time.monotonic() >= self.deadline:
            print(
                "NO STABLE PERSON DETECTION: "
                f"received {self.total_frames} detection messages and "
                f"saw a person in {self.person_seen_frames} frames, but only "
                f"{self.person_frames}/{self.required} frames had a safe "
                "starting distance and position.",
                flush=True,
            )
            self.save_evidence_image("no_person")
            rclpy.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--required", type=int, default=3)
    parser.add_argument(
        "--save-dir",
        default="/home/pi/pupper-tests/diagnostics",
    )
    args = parser.parse_args()
    if args.seconds <= 0.0 or args.required <= 0:
        parser.error("--seconds and --required must be positive")

    rclpy.init()
    node = PersonDetectionVerifier(args.seconds, args.required, args.save_dir)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0 if node.success else 1


if __name__ == "__main__":
    sys.exit(main())
