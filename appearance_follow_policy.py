"""Session-local colour lock and bounded motion, independent of ROS/images.

Selecting a colour stops first and NEVER arms movement. Each explicit arm needs
new, timestamped observations. Loss is latched until stop/select/arm again.
This is geometry/colour continuity, not identity or obstacle avoidance.
"""
import math

from shirt_color_selector import COLORS
from single_person_lock import PersonLock


class AppearanceFollowPolicy:
    def __init__(self):
        self.lock = PersonLock()
        self.stop()

    def stop(self):
        self.active = False
        self.color = None
        self.lock.reset()
        self.last_stamp = None
        self.received = self.capture_age = None
        self.x = self.yaw = 0.0

    def select(self, color):
        if color not in COLORS:
            self.reject("unsupported colour")
            raise ValueError("unsupported shirt colour")
        self.stop()
        self.color = color

    def arm(self):
        if self.active or self.color not in COLORS:
            return False
        self.lock.arm()
        self.active = True
        self.received = self.capture_age = None
        self.last_stamp = None
        self.x = self.yaw = 0.0
        return True

    def reject(self, reason):
        self.x = self.yaw = 0.0
        if self.active:
            self.lock.lose(reason)

    def observe(self, boxes, candidates, stamp, camera_age, now):
        if not self.active:
            return None
        if (type(stamp) is not int or stamp <= 0
                or not math.isfinite(camera_age) or not -0.05 <= camera_age <= 0.30
                or self.last_stamp is not None and stamp <= self.last_stamp):
            self.reject("stale, repeated or out-of-order camera frame")
            return None
        self.last_stamp, self.received, self.capture_age = stamp, now, camera_age
        if (any(type(i) is not int or not 0 <= i < len(boxes) for i in candidates)
                or len(set(candidates)) != len(candidates)):
            self.reject("invalid colour candidate indices")
            return None
        # After locking, geometry AND the selected shirt colour must agree.
        # Even a non-overlapping second matching shirt makes the request ambiguous.
        if self.lock.state == "LOCKED" and len(candidates) != 1:
            self.reject("selected colour missing or multiple matching people")
            return None
        index = self.lock.update(boxes, now, candidates)
        if self.lock.state == "LOCKED" and index not in candidates:
            self.reject("session target no longer matches selected shirt colour")
            return None
        return index

    def command(self, now):
        self.lock.tick(now)
        age = None if self.received is None else self.capture_age + now - self.received
        if self.active and self.lock.state == "LOCKED" and (age is None or not -0.05 <= age <= 0.30):
            self.reject("camera capture has expired")
        if not self.active or self.lock.state != "LOCKED" or self.lock.target is None:
            self.x = self.yaw = 0.0
            return 0.0, 0.0
        box = self.lock.target
        if not box.valid():
            self.reject("invalid target geometry")
            return 0.0, 0.0
        error = (box.x - 320.0) / 320.0
        yaw = max(-0.15, min(0.15, -0.8 * error)) if abs(error) >= 0.10 else 0.0
        area_error = 0.25 - box.w * box.h / (640.0 * 640.0)
        forward = min(0.10, max(0.0, 1.2 * area_error)) if area_error >= 0.06 else 0.0
        self.yaw += max(-0.03, min(0.03, yaw - self.yaw))
        self.x += max(-0.01, min(0.01, forward - self.x))
        if abs(yaw) > 0.07 or abs(self.yaw) > 0.07:
            self.x = 0.0
        if not all(math.isfinite(value) for value in (self.x, self.yaw)):
            self.reject("non-finite velocity")
            return 0.0, 0.0
        return self.x, self.yaw
