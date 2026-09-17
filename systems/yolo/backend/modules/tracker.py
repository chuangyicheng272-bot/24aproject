from __future__ import annotations

from dataclasses import dataclass, field
from math import exp, hypot
from typing import Any

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None
    np = None


Box = tuple[float, float, float, float]
Appearance = tuple[float, ...]


def box_area(box: Box) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def box_iou(box_a: Box, box_b: Box) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter = box_area((ix1, iy1, ix2, iy2))
    if inter <= 0:
        return 0.0
    union = box_area(box_a) + box_area(box_b) - inter
    return inter / union if union > 0 else 0.0


def box_center(box: Box) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def box_size(box: Box) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1), max(0.0, y2 - y1)


def center_distance(box_a: Box, box_b: Box) -> float:
    ax, ay = box_center(box_a)
    bx, by = box_center(box_b)
    return hypot(ax - bx, ay - by)


def size_similarity(box_a: Box, box_b: Box) -> float:
    area_a = box_area(box_a)
    area_b = box_area(box_b)
    if area_a <= 0 or area_b <= 0:
        return 0.0
    return min(area_a, area_b) / max(area_a, area_b)


def expanded_box(box: Box, ratio: float) -> Box:
    x1, y1, x2, y2 = box
    width, height = box_size(box)
    pad_x = width * ratio
    pad_y = height * ratio
    return x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y


def appearance_similarity(a: Appearance | None, b: Appearance | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    distance = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
    return exp(-distance * 3.0)


def extract_appearance(frame, box: Box) -> Appearance | None:
    if frame is None or cv2 is None or np is None:
        return None
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = [int(round(value)) for value in box]
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    resized = cv2.resize(crop, (24, 48))
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256])
    hist = cv2.normalize(hist, hist).flatten()
    return tuple(float(value) for value in hist)


@dataclass
class Track:
    track_id: int
    box: Box
    confidence: float
    first_seen: float
    last_seen: float
    hits: int = 1
    missed: int = 0
    velocity: tuple[float, float] = (0.0, 0.0)
    appearance: Appearance | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def predicted_box(self, timestamp: float) -> Box:
        elapsed = max(0.0, timestamp - self.last_seen)
        dx = self.velocity[0] * elapsed
        dy = self.velocity[1] * elapsed
        x1, y1, x2, y2 = self.box
        return x1 + dx, y1 + dy, x2 + dx, y2 + dy

    def update(
        self,
        detection: dict[str, Any],
        timestamp: float,
        smoothing: float = 0.45,
        appearance_smoothing: float = 0.75,
    ) -> None:
        new_box = tuple(detection["box"])
        old_center = box_center(self.box)
        new_center = box_center(new_box)
        elapsed = max(timestamp - self.last_seen, 1e-6)
        self.velocity = (
            (new_center[0] - old_center[0]) / elapsed,
            (new_center[1] - old_center[1]) / elapsed,
        )
        self.box = tuple(
            old_value * smoothing + new_value * (1.0 - smoothing)
            for old_value, new_value in zip(self.box, new_box)
        )
        self.confidence = float(detection.get("confidence", self.confidence))
        new_appearance = detection.get("appearance")
        if new_appearance is not None:
            if self.appearance is None:
                self.appearance = new_appearance
            else:
                self.appearance = tuple(
                    old * appearance_smoothing + new * (1.0 - appearance_smoothing)
                    for old, new in zip(self.appearance, new_appearance)
                )
        self.last_seen = timestamp
        self.hits += 1
        self.missed = 0
        self.metadata = dict(detection)

    def mark_missed(self) -> None:
        self.missed += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "box": [round(value, 2) for value in self.box],
            "confidence": round(self.confidence, 4),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "hits": self.hits,
            "missed": self.missed,
        }


class IouTracker:
    def __init__(
        self,
        iou_threshold: float = 0.12,
        center_distance_ratio: float = 1.05,
        min_center_distance: float = 130.0,
        min_size_similarity: float = 0.22,
        max_missed: int = 45,
        max_lost_seconds: float = 6.0,
        box_smoothing: float = 0.45,
        appearance_weight: float = 0.45,
    ):
        self.iou_threshold = iou_threshold
        self.center_distance_ratio = center_distance_ratio
        self.min_center_distance = min_center_distance
        self.min_size_similarity = min_size_similarity
        self.max_missed = max_missed
        self.max_lost_seconds = max_lost_seconds
        self.box_smoothing = box_smoothing
        self.appearance_weight = appearance_weight
        self.next_track_id = 1
        self.tracks: dict[int, Track] = {}

    def update(self, detections: list[dict[str, Any]], timestamp: float, frame=None) -> list[Track]:
        enriched = []
        for detection in detections:
            item = dict(detection)
            item["appearance"] = extract_appearance(frame, tuple(item["box"]))
            enriched.append(item)

        unmatched_track_ids = set(self.tracks.keys())
        assignments: list[tuple[int, dict[str, Any]]] = []

        for detection in sorted(enriched, key=lambda item: item.get("confidence", 0), reverse=True):
            best_track_id = None
            best_score = 0.0
            for track_id in list(unmatched_track_ids):
                score = self._match_score(detection, self.tracks[track_id], timestamp)
                if score > best_score:
                    best_score = score
                    best_track_id = track_id

            if best_track_id is None or best_score <= 0.0:
                track = Track(
                    track_id=self.next_track_id,
                    box=tuple(detection["box"]),
                    confidence=float(detection.get("confidence", 0.0)),
                    first_seen=timestamp,
                    last_seen=timestamp,
                    appearance=detection.get("appearance"),
                    metadata=dict(detection),
                )
                self.tracks[track.track_id] = track
                assignments.append((track.track_id, detection))
                self.next_track_id += 1
            else:
                unmatched_track_ids.discard(best_track_id)
                assignments.append((best_track_id, detection))

        for track_id, detection in assignments:
            self.tracks[track_id].update(detection, timestamp, self.box_smoothing)

        for track_id in unmatched_track_ids:
            self.tracks[track_id].mark_missed()

        self._remove_lost(timestamp)
        return sorted(
            (track for track in self.tracks.values() if track.missed == 0),
            key=lambda track: track.track_id,
        )

    def _match_score(self, detection: dict[str, Any], track: Track, timestamp: float) -> float:
        detection_box = tuple(detection["box"])
        predicted = track.predicted_box(timestamp)
        iou = box_iou(detection_box, predicted)
        relaxed_iou = box_iou(detection_box, expanded_box(predicted, 0.28))
        similarity = size_similarity(detection_box, predicted)
        distance = center_distance(detection_box, predicted)
        track_width, track_height = box_size(predicted)
        detection_width, detection_height = box_size(detection_box)
        allowed_distance = max(
            self.min_center_distance,
            hypot(track_width, track_height) * self.center_distance_ratio,
            hypot(detection_width, detection_height) * 0.65,
        )
        appearance = appearance_similarity(detection.get("appearance"), track.appearance)

        if iou >= self.iou_threshold:
            return 2.0 + iou + self.appearance_weight * appearance

        if relaxed_iou >= self.iou_threshold * 0.5 and similarity >= self.min_size_similarity:
            return 1.35 + relaxed_iou + self.appearance_weight * appearance

        if distance <= allowed_distance and similarity >= self.min_size_similarity:
            distance_score = 1.0 - (distance / allowed_distance)
            age_bonus = min(track.hits, 12) * 0.025
            appearance_bonus = self.appearance_weight * appearance
            if appearance >= 0.45 or distance_score >= 0.35:
                return 0.9 + distance_score + age_bonus + appearance_bonus

        if appearance >= 0.62 and distance <= allowed_distance * 1.35:
            distance_score = max(0.0, 1.0 - (distance / (allowed_distance * 1.35)))
            age_bonus = min(track.hits, 12) * 0.02
            return 0.75 + distance_score + age_bonus + self.appearance_weight * appearance

        return 0.0

    def _remove_lost(self, timestamp: float) -> None:
        for track_id in list(self.tracks.keys()):
            track = self.tracks[track_id]
            lost_seconds = timestamp - track.last_seen
            if track.missed > self.max_missed or lost_seconds > self.max_lost_seconds:
                del self.tracks[track_id]

    def reset(self) -> None:
        self.tracks.clear()
        self.next_track_id = 1
