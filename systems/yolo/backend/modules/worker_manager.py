from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from .pose_detector import MediaPipePoseDetector, PoseDetection, map_pose_detection_to_frame, smooth_pose_detection
from .tracker import IouTracker, Track, box_iou
from .yolo_detector import YOLOSafetyDetector


@dataclass
class WorkerState:
    track_id: int
    worker_id: str
    camera_id: str
    zone: str
    first_seen: float
    last_seen: float
    first_seen_unix: float
    last_seen_unix: float
    box: list[float]
    confidence: float
    velocity: dict[str, float] = field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    coordinate: dict[str, Any] = field(default_factory=dict)
    helmet_history: deque = field(default_factory=lambda: deque(maxlen=12))
    vest_history: deque = field(default_factory=lambda: deque(maxlen=12))
    ppe_detections: list[dict[str, Any]] = field(default_factory=list)
    behavior: dict[str, Any] = field(default_factory=dict)
    action_detector: Any = None
    risk_level: str = "normal"
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "track_id": self.track_id,
            "camera_id": self.camera_id,
            "zone": self.zone,
            "box": self.box,
            "velocity": {
                "x": round(float(self.velocity.get("x", 0.0)), 2),
                "y": round(float(self.velocity.get("y", 0.0)), 2),
            },
            "coordinate": self.coordinate,
            "confidence": round(self.confidence, 4),
            "ppe": {
                "helmet": stable_boolean(self.helmet_history),
                "vest": stable_boolean(self.vest_history),
            },
            "ppe_detections": self.ppe_detections,
            "behavior": summarize_behavior(self.behavior),
            "risk_level": self.risk_level,
            "alerts": self.alerts,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "first_seen_unix": round(self.first_seen_unix, 3),
            "last_seen_unix": round(self.last_seen_unix, 3),
        }


def stable_boolean(history: deque, min_samples: int = 3, threshold: float = 0.6) -> bool | None:
    if len(history) < min_samples:
        return None
    ratio = sum(1 for value in history if value) / len(history)
    if ratio >= threshold:
        return True
    if ratio <= 1.0 - threshold:
        return False
    return None


def calculate_recent_fps(timestamps: deque[float]) -> float:
    if len(timestamps) < 2:
        return 0.0
    elapsed = max(timestamps[-1] - timestamps[0], 1e-6)
    return (len(timestamps) - 1) / elapsed


def summarize_behavior(behavior: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": behavior.get("status", "正常"),
        "fall": bool(behavior.get("fall", False)),
        "running": bool(behavior.get("running", False)),
        "unstable": bool(behavior.get("unstable", False)),
        "wave": bool(behavior.get("wave", False)),
        "tracking_lost": bool(behavior.get("tracking_lost", False)),
        "fallback": bool(behavior.get("fallback", False)),
        "posture": behavior.get("posture", "unknown"),
        "fall_info": behavior.get("fall_info", {}),
        "running_info": behavior.get("running_info", {}),
        "unstable_info": behavior.get("unstable_info", {}),
    }


class WorkerManager:
    def __init__(
        self,
        camera_id: str = "CAM-01",
        zone: str = "施工區域",
        fps: float = 15.0,
        yolo: YOLOSafetyDetector | None = None,
        pose: MediaPipePoseDetector | None = None,
        tracker: IouTracker | None = None,
        ppe_interval_seconds: float | None = None,
        event_callback: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    ):
        self.camera_id = camera_id
        self.zone = zone
        self.fps = fps
        self.yolo = yolo or YOLOSafetyDetector()
        self.pose = pose or MediaPipePoseDetector()
        self.tracker = tracker or IouTracker()
        self.ppe_interval_seconds = (
            float(os.environ.get("PPE_INTERVAL_SECONDS", "2.0"))
            if ppe_interval_seconds is None
            else float(ppe_interval_seconds)
        )
        self.last_ppe_timestamp = -1e9
        self.cached_equipment: list[dict[str, Any]] = []
        self.workers: dict[int, WorkerState] = {}
        self.pose_history: dict[int, PoseDetection] = {}
        self.events: deque[dict[str, Any]] = deque(maxlen=200)
        self.process_wall_times: deque[float] = deque(maxlen=30)
        self.last_event_key: dict[int, tuple[str, ...]] = {}
        self.last_errors: dict[str, str] = {}
        self.last_frame_summary: dict[str, Any] = {}
        self.event_callback = event_callback

    def status(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "zone": self.zone,
            "workers": self.active_worker_dicts(),
            "events": list(self.events),
            "models": {
                "yolo": self.yolo.status(),
                "pose": self.pose.status(),
            },
            "performance": {
                "analysis_fps": self.fps,
                "ppe_interval_seconds": self.ppe_interval_seconds,
            },
            "last_errors": self.last_errors,
            "last_frame": self.last_frame_summary,
        }

    def active_worker_dicts(self) -> list[dict[str, Any]]:
        active_track_ids = {
            track_id
            for track_id, track in self.tracker.tracks.items()
            if track.missed == 0
        }
        return [
            worker.to_dict()
            for worker in sorted(self.workers.values(), key=lambda item: item.track_id)
            if worker.track_id in active_track_ids
        ]

    def process_frame(
        self,
        frame,
        timestamp: float | None = None,
        pairing_range: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp = time.monotonic() if timestamp is None else timestamp
        safety_result = self._detect_safety(frame, timestamp)
        people = safety_result.get("people", [])
        assignments = safety_result.get("assignments", {})
        for index, person in enumerate(people):
            person["equipment"] = assignments.get(index, assignments.get(str(index), []))

        tracks = self.tracker.update(people, timestamp, frame)
        pose_detections = self._detect_pose_for_people(frame, people, timestamp)
        smoothed_poses = self._update_workers(tracks, pose_detections, timestamp, frame.shape[:2], pairing_range)
        self._remove_missing_worker_states()

        workers = self.active_worker_dicts()
        person_confidences = [float(person.get("confidence", 0.0)) for person in people]
        self.process_wall_times.append(time.time())
        self.last_frame_summary = {
            "timestamp": timestamp,
            "wall_time": round(time.time(), 3),
            "actual_analysis_fps": round(calculate_recent_fps(self.process_wall_times), 2),
            "people_detected": len(people),
            "person_confidence_min": round(min(person_confidences), 4) if person_confidences else None,
            "person_confidence_avg": round(sum(person_confidences) / len(person_confidences), 4)
            if person_confidences
            else None,
            "person_confidence_threshold": self.yolo.person_confidence,
            "ppe_updated": bool(safety_result.get("ppe_updated", False)),
            "ppe_interval_seconds": round(self.ppe_interval_seconds, 3),
            "tracks": len(tracks),
            "retained_tracks": len(self.tracker.tracks),
            "workers": len(workers),
            "alerts": sum(1 for worker in workers if worker["risk_level"] != "normal"),
        }
        return {
            "workers": workers,
            "events": list(self.events),
            "detections": safety_result,
            "poses": [pose.to_dict() for pose in smoothed_poses],
            "summary": self.last_frame_summary,
            "errors": self.last_errors,
        }

    def _detect_safety(self, frame, timestamp: float) -> dict[str, Any]:
        try:
            self.last_errors.pop("yolo", None)
            include_equipment = timestamp - self.last_ppe_timestamp >= max(0.0, self.ppe_interval_seconds)
            result = self.yolo.detect_safety(frame, include_equipment=include_equipment)
            if result.get("ppe_updated"):
                self.last_ppe_timestamp = timestamp
                self.cached_equipment = list(result.get("equipment", []))
            else:
                result["equipment"] = list(self.cached_equipment)
            return result
        except Exception as exc:
            self.last_errors["yolo"] = str(exc)
            return {"people": [], "equipment": [], "assignments": {}, "ppe_updated": False}

    def _detect_pose_for_people(
        self,
        frame,
        people: list[dict[str, Any]],
        timestamp: float,
    ) -> list[PoseDetection]:
        if not people:
            return []

        height, width = frame.shape[:2]
        detections: list[PoseDetection] = []
        errors: list[str] = []
        for index, person in enumerate(people[: self.pose.max_people]):
            crop_box = expanded_person_crop(tuple(person["box"]), width, height)
            x1, y1, x2, y2 = [int(value) for value in crop_box]
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            try:
                crop_detections = self.pose.detect(crop, timestamp + index * 0.001)
                if crop_detections:
                    best_pose = max(crop_detections, key=lambda item: item.confidence)
                    detections.append(map_pose_detection_to_frame(best_pose, crop_box, width, height))
            except Exception as exc:
                errors.append(str(exc))

        if self.pose.last_error:
            self.last_errors["pose"] = self.pose.last_error
        elif errors:
            self.last_errors["pose"] = errors[-1]
        else:
            self.last_errors.pop("pose", None)
        return detections

    def _update_workers(
        self,
        tracks: list[Track],
        pose_detections: list[PoseDetection],
        timestamp: float,
        frame_shape: tuple[int, int],
        pairing_range: dict[str, Any] | None,
    ) -> list[PoseDetection]:
        smoothed_poses: list[PoseDetection] = []
        for track in tracks:
            worker = self._ensure_worker(track, timestamp)
            pose = best_pose_for_track(track, pose_detections, frame_shape)
            if pose is not None:
                pose = smooth_pose_detection(self.pose_history.get(track.track_id), pose)
                self.pose_history[track.track_id] = pose
                smoothed_poses.append(pose)
            worker.last_seen = track.last_seen
            worker.last_seen_unix = time.time()
            worker.box = [round(value, 2) for value in track.box]
            worker.velocity = {
                "x": float(track.velocity[0]),
                "y": float(track.velocity[1]),
            }
            worker.coordinate = calculate_worker_coordinate(track.box, frame_shape, pairing_range, pose)
            worker.confidence = track.confidence
            self._update_ppe(worker, track.metadata.get("equipment", []), ppe_updated=bool(timestamp == self.last_ppe_timestamp))
            self._update_behavior(worker, track, pose, timestamp, frame_shape)
            worker.risk_level, worker.alerts = self._evaluate_risk(worker)
            self._record_event_if_needed(worker, timestamp)
        return smoothed_poses

    def _ensure_worker(self, track: Track, timestamp: float) -> WorkerState:
        if track.track_id not in self.workers:
            self.workers[track.track_id] = WorkerState(
                track_id=track.track_id,
                worker_id=f"worker-{track.track_id:03d}",
                camera_id=self.camera_id,
                zone=self.zone,
                first_seen=timestamp,
                last_seen=timestamp,
                first_seen_unix=time.time(),
                last_seen_unix=time.time(),
                box=[round(value, 2) for value in track.box],
                velocity={"x": float(track.velocity[0]), "y": float(track.velocity[1])},
                coordinate={},
                confidence=track.confidence,
                action_detector=self.pose.create_action_detector(self.fps),
            )
        return self.workers[track.track_id]

    def _update_ppe(self, worker: WorkerState, equipment: list[dict[str, Any]], ppe_updated: bool = True) -> None:
        if not ppe_updated:
            return

        worker.ppe_detections = list(equipment)
        kinds = {item.get("kind") for item in equipment}
        if "helmet" in kinds or "no_helmet" in kinds:
            worker.helmet_history.append("helmet" in kinds and "no_helmet" not in kinds)
        if "vest" in kinds or "no_vest" in kinds:
            worker.vest_history.append("vest" in kinds and "no_vest" not in kinds)

    def _update_behavior(
        self,
        worker: WorkerState,
        track: Track,
        pose: PoseDetection | None,
        timestamp: float,
        frame_shape: tuple[int, int],
    ) -> None:
        if worker.action_detector is None:
            worker.behavior = {"status": "姿態分析未啟用"}
            return

        if hasattr(worker.action_detector, "update_box") and pose is None:
            detection = worker.action_detector.update_box(track.box, frame_shape, timestamp)
        elif pose is None:
            detection = worker.action_detector.update_no_pose(timestamp)
        else:
            detection = worker.action_detector.update(
                pose.landmarks,
                timestamp,
                pose.world_landmarks,
            )

        if any(detection.get(key) for key in ("fall", "running", "unstable", "wave")):
            detection["status"] = self.pose.status_text(detection)
        else:
            detection["status"] = detection.get("status") or self.pose.status_text(detection)
        worker.behavior = detection

    def _evaluate_risk(self, worker: WorkerState) -> tuple[str, list[str]]:
        alerts: list[str] = []
        helmet = stable_boolean(worker.helmet_history)
        vest = stable_boolean(worker.vest_history)
        behavior = summarize_behavior(worker.behavior)

        if helmet is False:
            alerts.append("未配戴安全帽")
        if vest is False:
            alerts.append("未穿戴安全背心")
        if behavior["fall"]:
            alerts.append("疑似跌倒")
        if behavior["wave"]:
            alerts.append("揮手求救")
        if behavior["unstable"]:
            alerts.append("步伐不穩")
        if behavior["running"]:
            alerts.append("奔跑")

        if behavior["fall"] or behavior["wave"]:
            return "danger", alerts
        if alerts:
            return "warning", alerts
        return "normal", alerts

    def _record_event_if_needed(self, worker: WorkerState, timestamp: float) -> None:
        if not worker.alerts:
            self.last_event_key.pop(worker.track_id, None)
            return

        key = tuple(sorted(worker.alerts))
        last_key = self.last_event_key.get(worker.track_id)
        if key == last_key:
            return

        self.last_event_key[worker.track_id] = key
        event = {
            "event_id": f"evt-{int(timestamp * 1000)}-{worker.track_id}",
            "worker_id": worker.worker_id,
            "track_id": worker.track_id,
            "camera_id": worker.camera_id,
            "zone": worker.zone,
            "risk_level": worker.risk_level,
            "alerts": list(worker.alerts),
            "timestamp": timestamp,
            "wall_time": round(time.time(), 3),
        }
        self.events.appendleft(event)
        if self.event_callback is not None:
            try:
                event["safeguard_forward"] = self.event_callback(
                    event, worker.to_dict()
                )
                self.last_errors.pop("safeguard", None)
            except Exception as exc:
                event["safeguard_forward"] = {
                    "status": "failed",
                    "error": str(exc),
                }
                self.last_errors["safeguard"] = str(exc)

    def _remove_missing_worker_states(self) -> None:
        active_ids = set(self.tracker.tracks.keys())
        for track_id in list(self.workers.keys()):
            if track_id not in active_ids:
                del self.workers[track_id]
                self.pose_history.pop(track_id, None)
                self.last_event_key.pop(track_id, None)


def expanded_person_crop(
    box: tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
    padding_ratio: float = 0.18,
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box
    width = max(x2 - x1, 1.0)
    height = max(y2 - y1, 1.0)
    pad_x = width * padding_ratio
    pad_y = height * padding_ratio
    return (
        max(0.0, x1 - pad_x),
        max(0.0, y1 - pad_y),
        min(float(frame_width), x2 + pad_x),
        min(float(frame_height), y2 + pad_y),
    )


def best_pose_for_track(
    track: Track,
    pose_detections: list[PoseDetection],
    frame_shape: tuple[int, int],
) -> PoseDetection | None:
    if not pose_detections:
        return None

    height, width = frame_shape
    best_pose = None
    best_score = 0.08
    for pose in pose_detections:
        if pose.box is None:
            continue
        pose_box = normalized_box_to_pixels(pose.box, width, height)
        score = box_iou(track.box, pose_box)
        if pose.waist is not None:
            waist_x = pose.waist["x"] * width
            waist_y = pose.waist["y"] * height
            x1, y1, x2, y2 = track.box
            if x1 <= waist_x <= x2 and y1 <= waist_y <= y2:
                score += 0.2
        if score > best_score:
            best_score = score
            best_pose = pose
    return best_pose


def normalized_box_to_pixels(
    box: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box
    return x1 * width, y1 * height, x2 * width, y2 * height


def calculate_worker_coordinate(
    box: tuple[float, float, float, float],
    frame_shape: tuple[int, int],
    pairing_range: dict[str, Any] | None = None,
    pose_detection: PoseDetection | None = None,
) -> dict[str, Any]:
    height, width = frame_shape
    x1, y1, x2, y2 = box
    source = "box_waist_center"

    if pose_detection is not None and pose_detection.waist is not None:
        normalized_x = pose_detection.waist["x"]
        normalized_y = pose_detection.waist["y"]
        pixel_x = normalized_x * width
        pixel_y = normalized_y * height
        source = "mediapipe_waist"
    else:
        pixel_x = (x1 + x2) / 2.0
        pixel_y = y1 + (y2 - y1) * 0.55
        normalized_x = pixel_x / width if width else 0.0
        normalized_y = pixel_y / height if height else 0.0

    frame_coordinate = {
        "source": source,
        "pixel": {
            "x": round(pixel_x, 2),
            "y": round(pixel_y, 2),
        },
        "normalized": {
            "x": round(normalized_x, 4),
            "y": round(normalized_y, 4),
        },
    }
    return {
        "source": source,
        "frame": frame_coordinate,
        "range": calculate_range_coordinate(normalized_x, normalized_y, width, height, pairing_range),
    }


def calculate_range_coordinate(
    normalized_x: float,
    normalized_y: float,
    frame_width: int,
    frame_height: int,
    pairing_range: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not pairing_range:
        return None

    points = pairing_range.get("points", [])
    if len(points) < 3:
        return None
    if not point_in_polygon(normalized_x, normalized_y, points):
        return None

    min_x = min(point["x"] for point in points)
    max_x = max(point["x"] for point in points)
    min_y = min(point["y"] for point in points)
    max_y = max(point["y"] for point in points)
    range_width = max(max_x - min_x, 1e-6)
    range_height = max(max_y - min_y, 1e-6)
    range_normalized_x = (normalized_x - min_x) / range_width
    range_normalized_y = (normalized_y - min_y) / range_height
    range_pixel_x = range_normalized_x * range_width * frame_width
    range_pixel_y = range_normalized_y * range_height * frame_height

    return {
        "source": "pairing_range_bounding_box",
        "inside": True,
        "pixel": {
            "x": round(range_pixel_x, 2),
            "y": round(range_pixel_y, 2),
        },
        "normalized": {
            "x": round(range_normalized_x, 4),
            "y": round(range_normalized_y, 4),
        },
    }


def point_in_polygon(x: float, y: float, polygon: list[dict[str, float]]) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        xi, yi = current["x"], current["y"]
        xj, yj = previous["x"], previous["y"]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        previous = current
    return inside
