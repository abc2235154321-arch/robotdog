"""Conservative, session-local bounding-box continuity, NOT identity recognition.

No ROS/model dependencies. Loss or ambiguity is latched until explicit restart.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    def valid(self):
        return all(math.isfinite(v) for v in (self.x, self.y, self.w, self.h)) and self.w > 0 and self.h > 0

    def iou(self, other):
        width = max(0.0, min(self.x + self.w / 2, other.x + other.w / 2) - max(self.x - self.w / 2, other.x - other.w / 2))
        height = max(0.0, min(self.y + self.h / 2, other.y + other.h / 2) - max(self.y - self.h / 2, other.y - other.h / 2))
        intersection = width * height
        return intersection / (self.w * self.h + other.w * other.h - intersection)

    def continues(self, other):
        return (self.iou(other) >= 0.40
                and 0.70 <= other.w / self.w <= 1.40
                and 0.70 <= other.h / self.h <= 1.40)


class PersonLock:
    def __init__(self, width=640, height=640):
        self.width, self.height = width, height
        self.timeout = 0.30
        self.reset()

    def reset(self):
        self.state = "IDLE"
        self.reason = "not armed"
        self.target = None
        self.last_frame = None
        self.candidate_since = None
        self.frames = 0

    def arm(self):
        self.reset()
        self.state = "ACQUIRING"
        self.reason = "one person must stand alone near image centre for one second"

    def lose(self, reason):
        self.state, self.reason, self.target = "LOST", reason, None

    def tick(self, now):
        if self.last_frame is not None and now - self.last_frame > self.timeout:
            if self.state == "LOCKED":
                self.lose("detection stream timed out")
            elif self.state == "ACQUIRING":
                self.target, self.candidate_since, self.frames = None, None, 0
                self.reason = "detection stream gap exceeds 0.30 seconds"

    def update(self, boxes, now, candidate_indices=None):
        self.tick(now)
        self.last_frame = now
        if self.state in {"IDLE", "LOST"}:
            return None
        # Invalid geometry fails closed rather than disappearing from the list.
        if any(not b.valid() for b in boxes):
            if self.state == "LOCKED":
                self.lose("invalid detection")
            else:
                self.target, self.candidate_since, self.frames = None, None, 0
                self.reason = "invalid detection geometry"
            return None
        if self.state == "ACQUIRING":
            indices = list(range(len(boxes))) if candidate_indices is None else list(candidate_indices)
            if any(type(i) is not int or not 0 <= i < len(boxes) for i in indices) or len(set(indices)) != len(indices):
                raise ValueError("invalid candidate indices")
            if len(indices) != 1:
                self.target, self.candidate_since, self.frames = None, None, 0
                self.reason = f"need exactly one matching person; matched {len(indices)}, people {len(boxes)}"
                return None
            index = indices[0]
            box = boxes[index]
            if any(i != index and box.iou(other) > 0.05 for i, other in enumerate(boxes)):
                self.target, self.candidate_since, self.frames = None, None, 0
                self.reason = "candidate overlaps another person; cannot safely select"
                return None
            area = box.w * box.h / (self.width * self.height)
            if not (0.08 <= area <= 0.45 and abs(box.x - self.width / 2) <= self.width * 0.20):
                self.target, self.candidate_since, self.frames = None, None, 0
                self.reason = f"centre/distance gate: x={box.x:.0f}, area={area:.3f} (need x=192..448, area=0.08..0.45)"
                return None
            if self.target is None or not self.target.continues(box):
                self.candidate_since, self.frames = now, 0
            self.target = box
            self.frames += 1
            self.reason = f"stable target: {self.frames} frames, {now - self.candidate_since:.2f}/1.00 seconds"
            if self.frames >= 5 and now - self.candidate_since >= 1.0:
                self.state, self.reason = "LOCKED", "session target locked"
                return index
            return None
        matches = [i for i, box in enumerate(boxes) if self.target.continues(box)]
        if len(matches) != 1:
            self.lose("target missing or multiple plausible matches")
            return None
        index = matches[0]
        selected = boxes[index]
        # Stop before overlapping people can swap ordering/identity.
        if any(i != index and (selected.iou(box) > 0.05 or self.target.iou(box) > 0.05)
               for i, box in enumerate(boxes)):
            self.lose("people overlap; identity is ambiguous")
            return None
        self.target = selected
        return index
