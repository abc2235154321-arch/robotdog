"""Optional local desktop viewer. No velocity publishers or action services."""
import time
import cv2
import numpy as np
from sensor_msgs.msg import CompressedImage


class SinglePersonPreview:
    def __init__(self, node):
        self.node = node
        self.running = True
        self.title = "Pupper - single person OBSERVATION ONLY"
        self.images = {}
        self.last_draw = 0.0
        self.subscriptions = []
        for topic in ("/annotated_image", "/camera/image_raw/compressed"):
            self.subscriptions.append(node.create_subscription(
                CompressedImage, topic,
                lambda message, topic=topic: self.receive(topic, message), 1))
        cv2.namedWindow(self.title, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.title, 960, 760)

    def receive(self, topic, message):
        image = cv2.imdecode(np.frombuffer(message.data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is not None:
            stamp = message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec
            self.images[topic] = (image, time.monotonic(), stamp)

    def show(self):
        now = time.monotonic()
        if now - self.last_draw < 0.10:
            return
        self.last_draw = now
        canvas = np.zeros((760, 960, 3), dtype=np.uint8)
        selected = self.images.get("/annotated_image")
        source = "HAILO ANNOTATED IMAGE"
        annotated = True
        if selected is None or now - selected[1] > 1.0:
            selected = self.images.get("/camera/image_raw/compressed")
            source = "RAW CAMERA - NO RECENT HAILO IMAGE"
            annotated = False
        detail = "NO CAMERA IMAGE RECEIVED"
        if selected is not None:
            image, received, stamp = selected
            image = image.copy()
            h, w = image.shape[:2]
            detail = f"Image {w}x{h}, received {now - received:.2f}s ago; lock geometry 640x640"
            target = self.node.lock.target
            if annotated:
                # Show the actual acquisition gate, in the assumed detection
                # coordinate system. Do NOT project boxes onto raw fisheye video.
                cv2.line(image, (192, 0), (192, h - 1), (0, 200, 255), 2)
                cv2.line(image, (448, 0), (448, h - 1), (0, 200, 255), 2)
                if target and stamp == self.node.last_stamp:
                    colour = (0, 255, 0) if self.node.lock.state == "LOCKED" else (0, 200, 255)
                    cv2.rectangle(image,
                                  (int(target.x - target.w / 2), int(target.y - target.h / 2)),
                                  (int(target.x + target.w / 2), int(target.y + target.h / 2)), colour, 3)
            ratio = min(960 / w, 540 / h)
            resized = cv2.resize(image, (max(1, int(w * ratio)), max(1, int(h * ratio))))
            left = (960 - resized.shape[1]) // 2
            canvas[0:resized.shape[0], left:left + resized.shape[1]] = resized
            if now - received > 1.0:
                source = "STALE IMAGE - NOT LIVE"
            elif annotated and (w, h) != (640, 640):
                source += " - GEOMETRY MISMATCH: DO NOT EXECUTE"
        state = self.node.lock.state
        colour = (0, 255, 0) if state == "LOCKED" else (0, 180, 255)
        lines = [source, detail, state + ": " + self.node.lock.reason,
                 self.node.diagnostic(), "NO MOTOR COMMANDS | R: reset target | Q/ESC: close"]
        y = 565
        for line in lines:
            # Keep longer explanations readable without requiring CJK fonts.
            for offset in range(0, len(line), 106):
                cv2.putText(canvas, line[offset:offset + 106], (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, colour, 1)
                y += 23
        cv2.imshow(self.title, canvas)
        key = cv2.waitKey(1) & 0xff
        if key in (ord("q"), 27):
            self.running = False
        elif key == ord("r"):
            self.node.stop(None, type("Response", (), {})())
            self.node.arm(None, type("Response", (), {})())
        if cv2.getWindowProperty(self.title, cv2.WND_PROP_VISIBLE) < 1:
            self.running = False

    def close(self):
        cv2.destroyAllWindows()
