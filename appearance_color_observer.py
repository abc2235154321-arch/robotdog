#!/usr/bin/env python3
"""NO-MOTION upper-shirt selection, synchronized with Hailo camera frames.

Reads raw frames, detections and annotated-image shape. Colour analysis uses
only a freshly projected CLEAN raw frame, never Hailo's coloured annotations.
All target selection services/topics are separate from robot action services.
"""
import argparse
from collections import OrderedDict
from pathlib import Path
import re
import subprocess
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
from std_srvs.srv import Trigger
from vision_msgs.msg import Detection2DArray

from shirt_color_selector import COLORS, analyse_shirt
from single_person_lock import Box, PersonLock


def stamp_ns(message):
    return message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec


def read_hailo_parameter(name):
    result = subprocess.run(["ros2", "param", "get", "/hailo_detection_node", name],
                            capture_output=True, text=True, timeout=6)
    if result.returncode:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise RuntimeError(f"Hailo parameter {name} unavailable: {detail}. Start the camera/Hailo pipeline first.")
    match = re.search(r"(?:Double|Integer|Boolean) value is:\s*(\S+)", result.stdout)
    if not match:
        raise RuntimeError(f"Cannot read Hailo parameter {name}; refusing guessed projection")
    return match.group(1)


def create_projector():
    from hailo import fisheye_utils
    if read_hailo_parameter("sim").lower() != "false":
        raise RuntimeError("This observer supports the current real fisheye camera, not simulation")
    h_fov = float(read_hailo_parameter("equirect_h_fov_deg"))
    v_fov = float(read_hailo_parameter("equirect_v_fov_deg"))
    if not (0 < h_fov <= 360 and 0 < v_fov <= 180):
        raise RuntimeError("Invalid projection field of view")
    calibration = Path(fisheye_utils.__file__).with_name("camera_params.yaml")
    model = fisheye_utils.create_fisheye_model_from_params(str(calibration), 1400, 1050)
    print(f"Projection: Hailo calibration={calibration}, FOV={h_fov}/{v_fov}; expected 640x640", flush=True)
    return fisheye_utils.FisheyeToEquirectangular(640, 640, h_fov, v_fov, model)


class AppearanceObserver(Node):
    def __init__(self, projector, color, preview=True, preview_port=8766,
                 mode="OBSERVATION_ONLY", node_name="appearance_color_observer"):
        super().__init__(node_name)
        self.mode = mode
        self.projector, self.color, self.preview = projector, color, preview
        self.lock = PersonLock()
        self.lock.arm()
        self.buffers = {topic: OrderedDict() for topic in ("raw", "detections", "annotated")}
        self.last_stamp = 0
        self.last_image = None
        self.last_image_received = None
        self.evidence = []
        self.people = 0
        self.matches = 0
        self.frame_age = None
        self.geometry_ok = False
        self.last_state = None
        self.last_log = 0.0
        self.wait_reason = "waiting for raw camera + detections + annotated image with the SAME timestamp"
        self.running = True
        self.web_preview = None
        self.last_preview = 0.0
        self.title = "Pupper - shirt colour OBSERVATION ONLY"
        self.status_pub = self.create_publisher(String, "/appearance_test/status" if mode == "OBSERVATION_ONLY" else "/appearance_follow/status", 10)
        self.create_subscription(CompressedImage, "/camera/image_raw/compressed", lambda m: self.receive("raw", m), 1)
        self.create_subscription(CompressedImage, "/annotated_image", lambda m: self.receive("annotated", m), 1)
        self.create_subscription(Detection2DArray, "/detections", lambda m: self.receive("detections", m), 1)
        if mode == "OBSERVATION_ONLY":
            self.create_subscription(String, "/appearance_test/target_color", self.change_color, 1)
            self.create_service(Trigger, "/appearance_test/check", self.check)
        self.create_timer(0.05, self.tick)
        if preview:
            from appearance_web_preview import AppearanceWebPreview
            self.web_preview = AppearanceWebPreview(preview_port, read_only=mode != "OBSERVATION_ONLY")
            print(f"BROWSER_PREVIEW: {self.web_preview.url} (on the DOG; no OpenCV GUI required)", flush=True)
        self.get_logger().info(f"{mode}: wanted shirt={color}")

    def receive(self, topic, message):
        stamp = stamp_ns(message)
        if stamp <= self.last_stamp or stamp <= 0:
            return
        if topic == "raw" and self.web_preview is not None:
            # Preview the entire original JPEG even if detection synchronisation
            # is waiting. Raw pixels are NEVER used as projected-box coordinates.
            age = (self.get_clock().now().nanoseconds - stamp) / 1e9
            self.web_preview.update_raw(message.data, age)
        buffer = self.buffers[topic]
        buffer[stamp] = message
        while len(buffer) > 12:
            buffer.popitem(last=False)

    def change_color(self, message):
        if message.data not in COLORS:
            self.get_logger().info("Rejected unsupported colour request; target unchanged")
            return
        self.color = message.data
        self.lock.arm()
        self.evidence = []
        self.last_image = None
        self.last_image_received = None
        self.frame_age = None
        self.people, self.matches = 0, 0
        self.geometry_ok = False
        self.wait_reason = "new observation target; waiting for fresh synchronized frames"
        # Never reuse queued pre-request images to select a new target.
        for buffer in self.buffers.values():
            buffer.clear()
        self.get_logger().info(f"New {self.mode} colour selection: {self.color}; selection does not arm movement")

    def check(self, request, response):
        self.lock.tick(time.monotonic())
        response.success = self.geometry_ok and self.lock.state == "LOCKED"
        response.message = f"OBSERVATION_ONLY {self.color}: {self.lock.state}; {self.lock.reason}"
        return response

    def reject_frame(self, reason):
        if self.lock.state == "LOCKED":
            self.lock.lose(reason)
        elif self.lock.state != "LOST":
            self.lock.arm()
            self.lock.reason = reason
        self.wait_reason = reason
        self.evidence = []

    def update_lock(self, boxes, candidates, stamp, camera_age, now):
        # One seam for the observation and execution policies. Pixels/boxes are
        # synchronised and geometrically checked before either policy sees them.
        return self.lock.update(boxes, now, candidates)

    def process_frame(self, stamp, raw_message, detections, annotated_message):
        self.frame_age = (self.get_clock().now().nanoseconds - stamp) / 1e9
        fresh = -0.05 <= self.frame_age <= 0.30
        raw = cv2.imdecode(np.frombuffer(raw_message.data, dtype=np.uint8), cv2.IMREAD_COLOR)
        annotated = cv2.imdecode(np.frombuffer(annotated_message.data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if raw is None or annotated is None or raw.shape[:2] != (1050, 1400) or annotated.shape[:2] != (640, 640):
            self.geometry_ok = False
            self.reject_frame(f"geometry mismatch: raw={None if raw is None else raw.shape[:2]}, Hailo={None if annotated is None else annotated.shape[:2]}")
            return
        self.geometry_ok = True
        image = self.projector.project(raw)
        if image.shape != (640, 640, 3):
            self.geometry_ok = False
            self.reject_frame(f"clean projection has unexpected shape: {image.shape}")
            return
        boxes = []
        for detection in detections.detections:
            if any(str(r.hypothesis.class_id) == "0" for r in detection.results):
                b = detection.bbox
                boxes.append(Box(float(b.center.position.x), float(b.center.position.y), float(b.size_x), float(b.size_y)))
        # Score BEFORE drawing any labels/boxes on the clean image.
        evidence = [analyse_shirt(image, box, self.color) for box in boxes]
        candidates = [i for i, item in enumerate(evidence) if item["match"]]
        self.people, self.matches = len(boxes), len(candidates)
        if fresh:
            self.update_lock(boxes, candidates, stamp, self.frame_age, time.monotonic())
            self.wait_reason = "synchronized clean image"
        else:
            # Still show diagnostic pixels, but NEVER use old images to lock.
            self.reject_frame(f"camera age={self.frame_age:.3f}s; require <=0.30s")
        self.evidence = evidence
        for index, (box, result) in enumerate(zip(boxes, evidence)):
            if not box.valid():
                continue
            color = (0, 200, 255) if result["match"] else (170, 170, 170)
            cv2.rectangle(image, (int(box.x - box.w / 2), int(box.y - box.h / 2)),
                          (int(box.x + box.w / 2), int(box.y + box.h / 2)), color, 2)
            if result["roi"] is not None:
                left, top, right, bottom = result["roi"]
                cv2.rectangle(image, (left, top), (right, bottom), color, 1)
            cv2.putText(image, f"#{index} {result['label']} {self.color}={result['ratio']:.0%}",
                        (max(0, int(box.x - box.w / 2)), max(18, int(box.y - box.h / 2))),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        if self.lock.target is not None and self.lock.state == "LOCKED":
            b = self.lock.target
            cv2.rectangle(image, (int(b.x - b.w / 2), int(b.y - b.h / 2)),
                          (int(b.x + b.w / 2), int(b.y + b.h / 2)), (0, 255, 0), 3)
        self.last_image, self.last_image_received = image, time.monotonic()

    def tick(self):
        if self.web_preview is not None:
            for kind, value in self.web_preview.commands():
                self.change_color(String(data=value if kind == "color" else self.color))
        now = time.monotonic()
        self.lock.tick(now)
        common = set.intersection(*(set(b) for b in self.buffers.values()))
        if common:
            stamp = max(common)
            try:
                self.process_frame(stamp, *(self.buffers[key][stamp] for key in ("raw", "detections", "annotated")))
            except Exception as exc:
                self.reject_frame(f"image analysis failed: {exc}")
            self.last_stamp = stamp
            for buffer in self.buffers.values():
                for old in list(buffer):
                    if old <= stamp:
                        del buffer[old]
        counts = ", ".join(f"{k}={len(b)}" for k, b in self.buffers.items())
        message = f"{self.mode} shirt={self.color} {self.lock.state}: {self.lock.reason}; people={self.people}, matches={self.matches}"
        self.status_pub.publish(String(data=message))
        if self.lock.state != self.last_state or now - self.last_log > 2.0:
            self.get_logger().info(message + "; " + self.wait_reason + "; buffers " + counts)
            self.last_state, self.last_log = self.lock.state, now
        if self.preview:
            self.show(counts)

    def show(self, counts):
        if time.monotonic() - self.last_preview < 0.20:
            return
        self.last_preview = time.monotonic()
        canvas = np.zeros((820, 960, 3), dtype=np.uint8)
        if self.last_image is not None:
            canvas[:540, 210:750] = cv2.resize(self.last_image, (540, 540))
        gap = None if self.last_image_received is None else time.monotonic() - self.last_image_received
        camera_age = None if gap is None or self.frame_age is None else self.frame_age + gap
        age = "?" if camera_age is None else f"{camera_age:.3f}s"
        live = gap is not None and gap <= 0.30 and camera_age is not None and -0.05 <= camera_age <= 0.30
        lines = [f"{self.mode} - wanted UPPER SHIRT: {self.color}",
                 self.lock.state + ": " + self.lock.reason,
                 f"People={self.people}, matching={self.matches}, camera age={age}; {'LIVE' if live else 'NO FRESH DISPLAY FRAME'}",
                 self.wait_reason, "Pending buffers: " + counts,
                 "Green=locked; yellow=colour match; inner box=shirt sample",
                 "Preview is READ ONLY" if self.mode != "OBSERVATION_ONLY" else "Choose colour / reset using the browser buttons",
                 "Closing preview DOES NOT stop movement" if self.mode != "OBSERVATION_ONLY" else "Stop the observer with Ctrl+C in SSH | NO MOTOR COMMANDS"]
        y = 565
        for line in lines:
            for offset in range(0, len(line), 106):
                cv2.putText(canvas, line[offset:offset + 106], (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.47, (0, 220, 255), 1)
                y += 22
        ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            self.web_preview.update(encoded.tobytes(), {
                "color": self.color, "state": self.lock.state, "reason": self.lock.reason,
                "people": self.people, "matches": self.matches, "camera_age": camera_age,
                "wait_reason": self.wait_reason, "mode": self.mode,
                "active": getattr(self, "active", False), "frame_live": live,
            })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--color", choices=COLORS, default="red")
    parser.add_argument("--headless", action="store_true", help="Diagnostics without a desktop window; still NEVER moves motors")
    parser.add_argument("--web-preview", action="store_true", help="Browser preview (also the default); no OpenCV GUI dependency")
    parser.add_argument("--preview-port", type=int, default=8766)
    args = parser.parse_args()
    if args.headless and args.web_preview:
        parser.error("Choose either --headless or --web-preview")
    if not 1 <= args.preview_port <= 65535:
        parser.error("Invalid preview port")
    projector = create_projector()
    rclpy.init(args=[])
    node = AppearanceObserver(projector, args.color, not args.headless, args.preview_port)
    try:
        while rclpy.ok() and node.running:
            rclpy.spin_once(node, timeout_sec=0.02)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node.web_preview is not None:
            node.web_preview.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
