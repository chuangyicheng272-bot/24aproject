from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from math import acos, atan2, degrees, hypot
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

try:
    import cv2
except ImportError:  # pragma: no cover - handled at runtime for setup guidance
    cv2 = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POSE_MODEL = PROJECT_ROOT / "model" / "pose_landmarker_heavy.task"

NOSE = 0
LEFT_EYE = 2
RIGHT_EYE = 5
LEFT_EAR = 7
RIGHT_EAR = 8
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24
LEFT_KNEE = 25
RIGHT_KNEE = 26
LEFT_ANKLE = 27
RIGHT_ANKLE = 28

PDF_FEATURE_KEYPOINTS = (
    NOSE,
    LEFT_EYE,
    RIGHT_EYE,
    LEFT_EAR,
    RIGHT_EAR,
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_ELBOW,
    RIGHT_ELBOW,
    LEFT_WRIST,
    RIGHT_WRIST,
    LEFT_HIP,
    RIGHT_HIP,
    LEFT_KNEE,
    RIGHT_KNEE,
    LEFT_ANKLE,
    RIGHT_ANKLE,
)


@dataclass
class LandmarkPoint:
    x: float
    y: float
    z: float = 0.0
    visibility: float = 1.0
    presence: float = 1.0


@dataclass
class PoseDetection:
    box: tuple[float, float, float, float] | None
    landmarks: Any
    world_landmarks: Any
    confidence: float
    waist: dict[str, float] | None = None
    features: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "box": None if self.box is None else [round(value, 4) for value in self.box],
            "confidence": round(self.confidence, 4),
            "landmarks": [
                {
                    "x": round(float(getattr(landmark, "x", 0.0)), 4),
                    "y": round(float(getattr(landmark, "y", 0.0)), 4),
                    "visibility": round(float(getattr(landmark, "visibility", 1.0)), 4),
                }
                for landmark in self.landmarks
            ],
            "waist": None
            if self.waist is None
            else {
                "x": round(self.waist["x"], 4),
                "y": round(self.waist["y"], 4),
            },
            "features": self.features or {},
        }


class MediaPipePoseDetector:
    def __init__(
        self,
        model_path: str | Path = DEFAULT_POSE_MODEL,
        max_people: int = 4,
        min_confidence: float = 0.45,
    ):
        self.model_path = Path(model_path)
        self.max_people = max_people
        self.min_confidence = min_confidence
        self.landmarker = None
        self.mp = None
        self.vision = None
        self.BaseOptions = None
        self.loaded = False
        self.load_attempted = False
        self.mode = "not_loaded"
        self.last_timestamp_ms = -1
        self.last_error: str | None = None

    def status(self) -> dict[str, Any]:
        dependencies_available = self._dependencies_available()
        return {
            "available": dependencies_available and self.loaded,
            "dependencies_available": dependencies_available,
            "mode": self.mode,
            "model": str(self.model_path),
            "model_exists": self.model_path.exists(),
            "loaded": self.loaded,
            "max_people": self.max_people,
            "last_error": self.last_error,
        }

    def _dependencies_available(self) -> bool:
        try:
            import mediapipe  # noqa: F401

            return cv2 is not None
        except Exception:
            return False

    def load(self) -> None:
        if self.loaded or self.load_attempted:
            return
        self.load_attempted = True

        if cv2 is None:
            self.mode = "unavailable"
            self.last_error = "OpenCV 未安裝，無法執行 MediaPipe 姿態分析。"
            return

        try:
            import mediapipe as mp
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.core.base_options import BaseOptions
        except Exception as exc:
            self.mode = "unavailable"
            self.last_error = f"MediaPipe 匯入失敗：{exc}"
            return

        self.mp = mp
        self.vision = vision
        self.BaseOptions = BaseOptions

        if not self.model_path.exists():
            self.mode = "model_missing"
            self.last_error = (
                f"找不到 MediaPipe 姿態模型：{self.model_path}。"
                "請放入 pose_landmarker_heavy.task 後重新啟動後端。"
            )
            return

        try:
            options = vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=vision.RunningMode.VIDEO,
                num_poses=max(1, self.max_people),
                min_pose_detection_confidence=self.min_confidence,
                min_pose_presence_confidence=self.min_confidence,
                min_tracking_confidence=self.min_confidence,
                output_segmentation_masks=False,
            )
            self.landmarker = vision.PoseLandmarker.create_from_options(options)
            self.loaded = True
            self.mode = "mediapipe_tasks"
            self.last_error = None
        except Exception as exc:  # pragma: no cover - depends on local model/runtime
            self.mode = "load_failed"
            self.last_error = f"MediaPipe 姿態模型載入失敗：{exc}"

    def detect(self, frame, timestamp: float | None = None) -> list[PoseDetection]:
        self.load()
        if not self.loaded or self.landmarker is None:
            return []

        timestamp = time.monotonic() if timestamp is None else timestamp
        timestamp_ms = max(int(timestamp * 1000), self.last_timestamp_ms + 1)
        self.last_timestamp_ms = timestamp_ms
        image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=image_rgb)
        results = self.landmarker.detect_for_video(mp_image, timestamp_ms)

        detections: list[PoseDetection] = []
        for index, landmarks in enumerate(results.pose_landmarks):
            world_landmarks = (
                results.pose_world_landmarks[index]
                if results.pose_world_landmarks and index < len(results.pose_world_landmarks)
                else None
            )
            features = extract_pose_features(landmarks)
            detections.append(
                PoseDetection(
                    box=pose_box(landmarks),
                    landmarks=landmarks,
                    world_landmarks=world_landmarks,
                    confidence=pose_quality(landmarks),
                    waist=pose_waist(landmarks),
                    features=features,
                )
            )
        return detections

    def create_action_detector(self, fps: float):
        if self.model_path.exists():
            return FeaturePoseActionDetector(fps)
        return BoxMotionActionDetector(fps)

    def status_text(self, detection: dict[str, Any]) -> str:
        return status_text(detection)


class FeaturePoseActionDetector:
    def __init__(self, fps: float, window_seconds: float = 2.0):
        self.fps = fps
        self.snapshots: deque[dict[str, Any]] = deque(maxlen=max(4, int(fps * window_seconds)))
        self.last_detection = normal_detection("等待姿態資料")
        self.missing_since: float | None = None
        self.fall_confirm_frames = max(2, int(round(fps * 1.3)))
        self.running_confirm_frames = max(3, int(round(fps * 0.9)))
        self.unstable_confirm_frames = max(3, int(round(fps * 1.8)))
        self.wave_confirm_frames = max(2, int(round(fps * 1.0)))
        self.fall_counter = 0
        self.wave_counter = 0
        self.unstable_counter = 0
        self.running_counter = 0

    def update(self, landmarks, timestamp: float, world_landmarks=None) -> dict[str, Any]:
        snapshot = pose_snapshot(landmarks, timestamp)
        if snapshot is None:
            return self.update_no_pose(timestamp)

        self.missing_since = None
        self.snapshots.append(snapshot)
        fall_condition, fall_info = self._fall_condition(snapshot)
        running_condition, running_info = self._running_condition(snapshot)
        unstable_condition = self._unstable_condition()
        wave_condition = self._wave_condition(snapshot)
        posture = classify_posture(snapshot)

        detection = {
            "fall": self._confirmed("fall", fall_condition, limit=self.fall_confirm_frames),
            "running": self._confirmed("running", running_condition, limit=self.running_confirm_frames),
            "unstable": self._confirmed("unstable", unstable_condition, limit=self.unstable_confirm_frames),
            "wave": self._confirmed("wave", wave_condition, limit=self.wave_confirm_frames),
            "wave_hand": self._wave_hand(snapshot),
            "tracking_lost": False,
            "fallback": False,
            "posture": posture,
            "features": snapshot["features"],
            "fall_info": {
                **fall_info,
                "counter": self.fall_counter,
            },
            "running_info": {
                **running_info,
                "counter": self.running_counter,
            },
            "unstable_info": {
                "lateral_jitter": round(self._lateral_jitter(), 3),
                "y_std": round(snapshot["features"].get("keypoint_y_std", 0.0), 3),
                "counter": self.unstable_counter,
            },
        }
        detection["status"] = status_text(detection)
        self.last_detection = detection
        return detection

    def update_no_pose(self, timestamp: float) -> dict[str, Any]:
        if self.missing_since is None:
            self.missing_since = timestamp
        missing_seconds = timestamp - self.missing_since
        detection = dict(self.last_detection)
        detection["tracking_lost"] = missing_seconds > 0.5
        detection["fallback"] = False
        detection["status"] = "姿態追蹤中斷" if detection["tracking_lost"] else "等待姿態資料"
        self.last_detection = detection
        return detection

    def _confirmed(self, name: str, condition: bool, limit: int) -> bool:
        counter_name = f"{name}_counter"
        counter = getattr(self, counter_name)
        counter = min(limit + 3, counter + 1) if condition else max(0, counter - 1)
        setattr(self, counter_name, counter)
        return counter >= limit

    def _fall_condition(self, snapshot: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        features = snapshot["features"]
        posture = classify_posture(snapshot)
        tilt = features.get("torso_tilt", 0.0)
        hip_height = features.get("hip_height_ratio", 0.0)
        head_delta = features.get("head_shoulder_delta_y", 0.0)
        y_std = features.get("keypoint_y_std", 0.0)
        body_ratio = features.get("body_aspect_ratio", 2.0)
        tilt_rise = self._tilt_rise_per_second()
        hip_drop = self._hip_drop_speed()
        height_drop = self._body_height_drop_ratio()

        posture_transition = self._recent_posture_transition_to("fallen", within_seconds=1.2)
        static_fall_score = sum(
            [
                tilt >= 58.0,
                body_ratio <= 1.2,
                hip_height >= 0.62,
                head_delta >= -0.02,
                y_std <= 0.19,
            ]
        )
        dynamic_fall = posture_transition and (tilt_rise >= 35.0 or hip_drop >= 0.18 or height_drop >= 0.22)
        condition = posture == "fallen" and (static_fall_score >= 3 or dynamic_fall)
        return condition, {
            "posture": posture,
            "static_score": static_fall_score,
            "torso_tilt": round(tilt, 2),
            "hip_height_ratio": round(hip_height, 3),
            "head_shoulder_delta_y": round(head_delta, 3),
            "body_aspect_ratio": round(body_ratio, 3),
            "tilt_rise_per_second": round(tilt_rise, 2),
            "hip_drop_speed": round(hip_drop, 3),
            "height_drop_ratio": round(height_drop, 3),
            "transition_to_fallen": posture_transition,
        }

    def _running_condition(self, snapshot: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        required_samples = 3 if self.fps < 3 else 4
        if len(self.snapshots) < required_samples:
            return False, {
                "hip_speed": 0.0,
                "leg_delta": 0.0,
                "arm_delta": 0.0,
                "ankle_delta": 0.0,
                "elapsed": 0.0,
                "required_samples": required_samples,
                "sample_count": len(self.snapshots),
                "lower_body_quality": 0.0,
                "motion_consistency": 0.0,
                "vertical_bounce": 0.0,
                "alternating_gait": False,
                "gait_phase_changes": 0,
                "fast_translation": False,
                "active_stride": False,
                "active_arm_swing": False,
                "stride_motion": False,
                "motion_score": 0,
                "reason": "insufficient_samples",
            }

        speed = self._hip_speed()
        leg_delta = max(
            self._feature_delta("left_knee_angle"),
            self._feature_delta("right_knee_angle"),
        )
        arm_delta = max(
            self._feature_delta("left_wrist_y"),
            self._feature_delta("right_wrist_y"),
        )
        ankle_delta = max(
            self._feature_delta("left_ankle_y"),
            self._feature_delta("right_ankle_y"),
        )
        elapsed = self.snapshots[-1]["timestamp"] - self.snapshots[0]["timestamp"]
        lower_body_quality = self._recent_feature_average("lower_body_visibility", required_samples)
        motion_consistency = self._motion_consistency()
        vertical_bounce = self._hip_vertical_range()
        gait = self._alternating_gait()
        fast_translation = speed >= 0.30 and motion_consistency >= 0.55
        very_fast_translation = speed >= 0.42 and motion_consistency >= 0.45
        active_stride = (leg_delta >= 34.0 and ankle_delta >= 0.04) or ankle_delta >= 0.085
        active_arm_swing = arm_delta >= 0.055
        stride_motion = (leg_delta >= 38.0 and ankle_delta >= 0.038) or (leg_delta >= 52.0 and ankle_delta >= 0.028)
        quality_ok = lower_body_quality >= 0.45
        gait_ok = gait["alternating"] and gait["phase_changes"] >= 1
        posture_ok = snapshot.get("posture") not in {"sitting", "fallen"}
        motion_score = sum(
            [
                fast_translation,
                very_fast_translation,
                active_stride,
                active_arm_swing,
                stride_motion,
                gait_ok,
            ]
        )
        condition = (
            elapsed >= 0.55
            and quality_ok
            and gait_ok
            and posture_ok
            and (
                (fast_translation and stride_motion and (active_arm_swing or vertical_bounce >= 0.012))
                or (very_fast_translation and active_stride and stride_motion)
            )
        )
        return condition, {
            "hip_speed": round(speed, 3),
            "leg_delta": round(leg_delta, 2),
            "arm_delta": round(arm_delta, 3),
            "ankle_delta": round(ankle_delta, 3),
            "elapsed": round(elapsed, 3),
            "required_samples": required_samples,
            "sample_count": len(self.snapshots),
            "lower_body_quality": round(lower_body_quality, 3),
            "motion_consistency": round(motion_consistency, 3),
            "vertical_bounce": round(vertical_bounce, 3),
            "alternating_gait": gait["alternating"],
            "gait_phase_changes": gait["phase_changes"],
            "ankle_phase_range": round(gait["ankle_phase_range"], 3),
            "knee_phase_range": round(gait["knee_phase_range"], 2),
            "fast_translation": fast_translation,
            "very_fast_translation": very_fast_translation,
            "active_stride": active_stride,
            "active_arm_swing": active_arm_swing,
            "stride_motion": stride_motion,
            "motion_score": motion_score,
            "reason": "running_gait_confirmed" if condition else "gait_or_speed_not_confirmed",
        }

    def _unstable_condition(self) -> bool:
        required_samples = min(4, self.snapshots.maxlen or 4)
        if len(self.snapshots) < required_samples:
            return False
        return self._lateral_jitter() >= 0.055 and self._hip_speed() < 0.55

    def _wave_condition(self, snapshot: dict[str, Any]) -> bool:
        features = snapshot["features"]
        return bool(features.get("left_wrist_above_shoulder") or features.get("right_wrist_above_shoulder"))

    def _wave_hand(self, snapshot: dict[str, Any]) -> str:
        features = snapshot["features"]
        left = bool(features.get("left_wrist_above_shoulder"))
        right = bool(features.get("right_wrist_above_shoulder"))
        if left and right:
            return "both"
        if left:
            return "left"
        if right:
            return "right"
        return ""

    def _recent_posture_transition_to(self, target: str, within_seconds: float) -> bool:
        if len(self.snapshots) < 2 or self.snapshots[-1]["posture"] != target:
            return False
        latest_time = self.snapshots[-1]["timestamp"]
        for snapshot in reversed(self.snapshots):
            if latest_time - snapshot["timestamp"] > within_seconds:
                break
            if snapshot["posture"] in {"standing", "sitting"}:
                return True
        return False

    def _hip_speed(self) -> float:
        if len(self.snapshots) < 2:
            return 0.0
        first = self.snapshots[0]
        last = self.snapshots[-1]
        duration = max(last["timestamp"] - first["timestamp"], 1e-6)
        return hypot(
            last["hip_center"][0] - first["hip_center"][0],
            last["hip_center"][1] - first["hip_center"][1],
        ) / duration

    def _hip_drop_speed(self) -> float:
        if len(self.snapshots) < 2:
            return 0.0
        first = self.snapshots[0]
        last = self.snapshots[-1]
        duration = max(last["timestamp"] - first["timestamp"], 1e-6)
        return max(0.0, last["hip_center"][1] - first["hip_center"][1]) / duration

    def _tilt_rise_per_second(self) -> float:
        if len(self.snapshots) < 2:
            return 0.0
        first = self.snapshots[0]
        last = self.snapshots[-1]
        duration = max(last["timestamp"] - first["timestamp"], 1e-6)
        return max(0.0, last["features"]["torso_tilt"] - first["features"]["torso_tilt"]) / duration

    def _body_height_drop_ratio(self) -> float:
        if len(self.snapshots) < 2:
            return 0.0
        heights = [item["features"].get("body_height", 0.0) for item in self.snapshots]
        baseline = max(heights[:-1] or heights, default=0.0)
        if baseline <= 1e-6:
            return 0.0
        return max(0.0, baseline - heights[-1]) / baseline

    def _feature_delta(self, feature_name: str) -> float:
        if len(self.snapshots) < 2:
            return 0.0
        values = [snapshot["features"].get(feature_name) for snapshot in self.snapshots]
        values = [float(value) for value in values if value is not None]
        return max(values) - min(values) if len(values) >= 2 else 0.0

    def _recent_feature_average(self, feature_name: str, count: int) -> float:
        values = [
            float(snapshot["features"].get(feature_name, 0.0))
            for snapshot in list(self.snapshots)[-count:]
        ]
        return sum(values) / len(values) if values else 0.0

    def _alternating_gait(self) -> dict[str, Any]:
        ankle_phase = [
            snapshot["features"].get("left_ankle_y", 0.0) - snapshot["features"].get("right_ankle_y", 0.0)
            for snapshot in self.snapshots
        ]
        knee_phase = [
            snapshot["features"].get("left_knee_angle", 180.0) - snapshot["features"].get("right_knee_angle", 180.0)
            for snapshot in self.snapshots
        ]
        ankle_changes = count_phase_changes(ankle_phase, epsilon=0.012)
        knee_changes = count_phase_changes(knee_phase, epsilon=8.0)
        ankle_range = max(ankle_phase) - min(ankle_phase) if len(ankle_phase) >= 2 else 0.0
        knee_range = max(knee_phase) - min(knee_phase) if len(knee_phase) >= 2 else 0.0
        phase_changes = max(ankle_changes, knee_changes)
        alternating = phase_changes >= 1 and (ankle_range >= 0.035 or knee_range >= 24.0)
        return {
            "alternating": alternating,
            "phase_changes": phase_changes,
            "ankle_phase_range": ankle_range,
            "knee_phase_range": knee_range,
        }

    def _motion_consistency(self) -> float:
        if len(self.snapshots) < 3:
            return 0.0
        points = [snapshot["hip_center"] for snapshot in self.snapshots]
        path = sum(distance(a, b) for a, b in zip(points, points[1:]))
        if path <= 1e-6:
            return 0.0
        net = distance(points[0], points[-1])
        return max(0.0, min(1.0, net / path))

    def _hip_vertical_range(self) -> float:
        if len(self.snapshots) < 2:
            return 0.0
        ys = [snapshot["hip_center"][1] for snapshot in self.snapshots]
        return max(ys) - min(ys)

    def _lateral_jitter(self) -> float:
        if len(self.snapshots) < 4:
            return 0.0
        xs = [snapshot["hip_center"][0] for snapshot in self.snapshots]
        mean_x = sum(xs) / len(xs)
        return sum(abs(x - mean_x) for x in xs) / len(xs)


class BoxMotionActionDetector:
    def __init__(self, fps: float, window_seconds: float = 2.0):
        self.samples: deque[dict[str, float]] = deque(maxlen=max(4, int(fps * window_seconds)))
        self.last_detection = normal_detection("姿態模型未啟用")
        self.fall_confirm_frames = max(2, int(round(fps * 1.3)))
        self.running_confirm_frames = max(4, int(round(fps * 1.2)))
        self.unstable_confirm_frames = max(3, int(round(fps * 1.8)))
        self.fall_counter = 0
        self.running_counter = 0
        self.unstable_counter = 0

    def update_box(
        self,
        box: tuple[float, float, float, float],
        frame_shape: tuple[int, int],
        timestamp: float,
    ) -> dict[str, Any]:
        height, width = frame_shape
        x1, y1, x2, y2 = box
        box_width = max(x2 - x1, 1.0)
        box_height = max(y2 - y1, 1.0)
        sample = {
            "timestamp": timestamp,
            "x": ((x1 + x2) / 2.0) / max(width, 1),
            "y": ((y1 + y2) / 2.0) / max(height, 1),
            "w": box_width / max(width, 1),
            "h": box_height / max(height, 1),
            "aspect": box_height / box_width,
        }
        self.samples.append(sample)

        speed = self._speed()
        drop_speed = self._drop_speed()
        fall_condition = sample["aspect"] <= 1.05 and (drop_speed >= 0.2 or sample["y"] >= 0.72)
        required_samples = min(4, self.samples.maxlen or 4)
        motion_consistency = self._motion_consistency()
        size_jitter = self._size_jitter()
        running_condition = (
            len(self.samples) >= required_samples
            and speed >= 0.85
            and motion_consistency >= 0.70
            and size_jitter <= 0.18
        )
        unstable_condition = len(self.samples) >= required_samples and self._lateral_jitter() >= 0.065 and speed < 0.65

        detection = {
            "fall": self._confirmed("fall", fall_condition, limit=self.fall_confirm_frames),
            "running": self._confirmed("running", running_condition, limit=self.running_confirm_frames),
            "unstable": self._confirmed("unstable", unstable_condition, limit=self.unstable_confirm_frames),
            "wave": False,
            "wave_hand": "",
            "tracking_lost": False,
            "fallback": True,
            "posture": "unknown",
            "fall_info": {
                "aspect_ratio": round(sample["aspect"], 3),
                "drop_speed": round(drop_speed, 3),
                "counter": self.fall_counter,
            },
            "running_info": {
                "box_speed": round(speed, 3),
                "motion_consistency": round(motion_consistency, 3),
                "size_jitter": round(size_jitter, 3),
                "required_samples": required_samples,
                "sample_count": len(self.samples),
                "counter": self.running_counter,
                "reason": "fast_consistent_box_motion" if running_condition else "pose_required_or_box_motion_not_confirmed",
            },
            "unstable_info": {
                "lateral_jitter": round(self._lateral_jitter(), 3),
                "counter": self.unstable_counter,
            },
        }
        detection["status"] = status_text(detection, fallback_label="姿態模型未啟用")
        self.last_detection = detection
        return detection

    def update_no_pose(self, timestamp: float) -> dict[str, Any]:
        detection = dict(self.last_detection)
        detection["tracking_lost"] = True
        detection["status"] = "姿態模型未啟用"
        return detection

    def _confirmed(self, name: str, condition: bool, limit: int) -> bool:
        counter_name = f"{name}_counter"
        counter = getattr(self, counter_name)
        counter = min(limit + 3, counter + 1) if condition else max(0, counter - 1)
        setattr(self, counter_name, counter)
        return counter >= limit

    def _speed(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        first = self.samples[0]
        last = self.samples[-1]
        duration = max(last["timestamp"] - first["timestamp"], 1e-6)
        return hypot(last["x"] - first["x"], last["y"] - first["y"]) / duration

    def _drop_speed(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        first = self.samples[0]
        last = self.samples[-1]
        duration = max(last["timestamp"] - first["timestamp"], 1e-6)
        return max(0.0, last["y"] - first["y"]) / duration

    def _motion_consistency(self) -> float:
        if len(self.samples) < 3:
            return 0.0
        points = [(sample["x"], sample["y"]) for sample in self.samples]
        path = sum(distance(a, b) for a, b in zip(points, points[1:]))
        if path <= 1e-6:
            return 0.0
        net = distance(points[0], points[-1])
        return max(0.0, min(1.0, net / path))

    def _size_jitter(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        widths = [sample["w"] for sample in self.samples]
        heights = [sample["h"] for sample in self.samples]
        return (max(widths) - min(widths)) + (max(heights) - min(heights))

    def _lateral_jitter(self) -> float:
        if len(self.samples) < 4:
            return 0.0
        xs = [sample["x"] for sample in self.samples]
        mean_x = sum(xs) / len(xs)
        return sum(abs(x - mean_x) for x in xs) / len(xs)


def normal_detection(status: str = "正常") -> dict[str, Any]:
    return {
        "status": status,
        "fall": False,
        "running": False,
        "unstable": False,
        "wave": False,
        "wave_hand": "",
        "tracking_lost": False,
        "fallback": False,
        "posture": "unknown",
    }


def status_text(detection: dict[str, Any], fallback_label: str | None = None) -> str:
    if detection.get("fall"):
        return "疑似跌倒"
    if detection.get("wave"):
        return "揮手求救"
    if detection.get("unstable"):
        return "步伐不穩"
    if detection.get("running"):
        return "奔跑"
    if detection.get("tracking_lost"):
        return "姿態追蹤中斷"
    posture = detection.get("posture")
    if posture == "standing":
        return "站立"
    if posture == "sitting":
        return "坐姿"
    if posture == "fallen":
        return "疑似跌倒姿態"
    return fallback_label or "正常"


def pose_snapshot(landmarks, timestamp: float) -> dict[str, Any] | None:
    features = extract_pose_features(landmarks)
    if not features:
        return None
    hip = pose_waist(landmarks)
    if hip is None:
        return None
    snapshot = {
        "timestamp": timestamp,
        "hip_center": (hip["x"], hip["y"]),
        "features": features,
    }
    snapshot["posture"] = classify_posture(snapshot)
    return snapshot


def extract_pose_features(landmarks) -> dict[str, float]:
    required = [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE]
    if any(point(landmarks, index, min_visibility=0.2) is None for index in required):
        return {}

    left_shoulder = point(landmarks, LEFT_SHOULDER)
    right_shoulder = point(landmarks, RIGHT_SHOULDER)
    left_elbow = point(landmarks, LEFT_ELBOW, min_visibility=0.2)
    right_elbow = point(landmarks, RIGHT_ELBOW, min_visibility=0.2)
    left_wrist = point(landmarks, LEFT_WRIST, min_visibility=0.2)
    right_wrist = point(landmarks, RIGHT_WRIST, min_visibility=0.2)
    left_hip = point(landmarks, LEFT_HIP)
    right_hip = point(landmarks, RIGHT_HIP)
    left_knee = point(landmarks, LEFT_KNEE)
    right_knee = point(landmarks, RIGHT_KNEE)
    left_ankle = point(landmarks, LEFT_ANKLE, min_visibility=0.2)
    right_ankle = point(landmarks, RIGHT_ANKLE, min_visibility=0.2)
    nose = point(landmarks, NOSE, min_visibility=0.2)

    shoulder_center = midpoint(left_shoulder, right_shoulder)
    hip_center = midpoint(left_hip, right_hip)
    box = pose_box(landmarks) or (0.0, 0.0, 1.0, 1.0)
    body_width = max(box[2] - box[0], 1e-6)
    body_height = max(box[3] - box[1], 1e-6)
    y_values = [
        float(landmarks[index].y)
        for index in PDF_FEATURE_KEYPOINTS
        if index < len(landmarks)
        and getattr(landmarks[index], "visibility", 1.0) >= 0.2
        and getattr(landmarks[index], "presence", 1.0) >= 0.1
    ]

    left_arm_angle = joint_angle(left_shoulder, left_elbow, left_wrist)
    right_arm_angle = joint_angle(right_shoulder, right_elbow, right_wrist)
    left_knee_angle = joint_angle(left_hip, left_knee, left_ankle)
    right_knee_angle = joint_angle(right_hip, right_knee, right_ankle)
    left_hip_angle = joint_angle(left_shoulder, left_hip, left_knee)
    right_hip_angle = joint_angle(right_shoulder, right_hip, right_knee)
    left_torso_angle = torso_angle_from_vertical(left_shoulder, left_hip)
    right_torso_angle = torso_angle_from_vertical(right_shoulder, right_hip)
    left_thigh_angle = angle_from_horizontal(left_hip, left_knee)
    right_thigh_angle = angle_from_horizontal(right_hip, right_knee)
    head_y = nose[1] if nose else min(left_shoulder[1], right_shoulder[1])
    shoulder_y = shoulder_center[1]
    lower_body_visibility = mean(
        [
            landmark_score(landmarks, LEFT_HIP),
            landmark_score(landmarks, RIGHT_HIP),
            landmark_score(landmarks, LEFT_KNEE),
            landmark_score(landmarks, RIGHT_KNEE),
            landmark_score(landmarks, LEFT_ANKLE),
            landmark_score(landmarks, RIGHT_ANKLE),
        ]
    )
    arm_visibility = mean(
        [
            landmark_score(landmarks, LEFT_WRIST),
            landmark_score(landmarks, RIGHT_WRIST),
            landmark_score(landmarks, LEFT_ELBOW),
            landmark_score(landmarks, RIGHT_ELBOW),
        ]
    )

    return {
        "left_arm_angle": left_arm_angle,
        "right_arm_angle": right_arm_angle,
        "left_knee_angle": left_knee_angle,
        "right_knee_angle": right_knee_angle,
        "left_hip_angle": left_hip_angle,
        "right_hip_angle": right_hip_angle,
        "left_torso_angle": left_torso_angle,
        "right_torso_angle": right_torso_angle,
        "torso_tilt": torso_angle_from_vertical(shoulder_center, hip_center),
        "hip_height_ratio": hip_center[1],
        "head_above_shoulder": 1.0 if head_y < shoulder_y else 0.0,
        "head_shoulder_delta_y": head_y - shoulder_y,
        "left_thigh_horizontal": left_thigh_angle,
        "right_thigh_horizontal": right_thigh_angle,
        "keypoint_y_std": pstdev(y_values) if len(y_values) >= 2 else 0.0,
        "left_wrist_y": left_wrist[1] if left_wrist else shoulder_y,
        "right_wrist_y": right_wrist[1] if right_wrist else shoulder_y,
        "left_ankle_y": left_ankle[1] if left_ankle else hip_center[1],
        "right_ankle_y": right_ankle[1] if right_ankle else hip_center[1],
        "left_leg_dynamic_proxy": left_knee_angle,
        "right_leg_dynamic_proxy": right_knee_angle,
        "left_wrist_above_shoulder": 1.0 if left_wrist and left_wrist[1] < shoulder_y - 0.06 else 0.0,
        "right_wrist_above_shoulder": 1.0 if right_wrist and right_wrist[1] < shoulder_y - 0.06 else 0.0,
        "body_aspect_ratio": body_height / body_width,
        "body_height": body_height,
        "body_width": body_width,
        "shoulder_width": distance(left_shoulder, right_shoulder),
        "hip_width": distance(left_hip, right_hip),
        "lower_body_visibility": lower_body_visibility,
        "arm_visibility": arm_visibility,
    }


def classify_posture(snapshot: dict[str, Any]) -> str:
    features = snapshot["features"]
    tilt = features.get("torso_tilt", 0.0)
    ratio = features.get("body_aspect_ratio", 2.0)
    hip_height = features.get("hip_height_ratio", 0.0)
    left_thigh = features.get("left_thigh_horizontal", 90.0)
    right_thigh = features.get("right_thigh_horizontal", 90.0)
    knee_bent = mean(
        [
            180.0 - features.get("left_knee_angle", 180.0),
            180.0 - features.get("right_knee_angle", 180.0),
        ]
    )

    if tilt >= 58.0 and (ratio <= 1.25 or hip_height >= 0.64):
        return "fallen"
    if knee_bent >= 45.0 and min(left_thigh, right_thigh) <= 38.0 and tilt < 50.0:
        return "sitting"
    if tilt < 35.0 and ratio >= 1.25:
        return "standing"
    return "unknown"


def pose_box(landmarks) -> tuple[float, float, float, float] | None:
    points = []
    for landmark in landmarks:
        visibility = getattr(landmark, "visibility", 1.0)
        presence = getattr(landmark, "presence", 1.0)
        if visibility >= 0.25 and presence >= 0.1:
            points.append((float(landmark.x), float(landmark.y)))
    if not points:
        return None
    xs = [item[0] for item in points]
    ys = [item[1] for item in points]
    return max(0.0, min(xs)), max(0.0, min(ys)), min(1.0, max(xs)), min(1.0, max(ys))


def pose_quality(landmarks) -> float:
    scores = []
    for landmark in landmarks:
        visibility = getattr(landmark, "visibility", 1.0)
        presence = getattr(landmark, "presence", 1.0)
        scores.append(min(float(visibility), float(presence)))
    return sum(scores) / len(scores) if scores else 0.0


def pose_waist(landmarks) -> dict[str, float] | None:
    left_hip = point(landmarks, LEFT_HIP, min_visibility=0.25)
    right_hip = point(landmarks, RIGHT_HIP, min_visibility=0.25)
    if not left_hip or not right_hip:
        return None
    x, y, _ = midpoint(left_hip, right_hip)
    return {"x": clamp01(x), "y": clamp01(y)}


def point(landmarks, index: int, min_visibility: float = 0.35) -> tuple[float, float, float] | None:
    if index >= len(landmarks):
        return None
    landmark = landmarks[index]
    visibility = getattr(landmark, "visibility", 1.0)
    presence = getattr(landmark, "presence", 1.0)
    if visibility < min_visibility or presence < 0.1:
        return None
    return clamp01(float(landmark.x)), clamp01(float(landmark.y)), float(getattr(landmark, "z", 0.0))


def landmark_score(landmarks, index: int) -> float:
    if index >= len(landmarks):
        return 0.0
    landmark = landmarks[index]
    visibility = float(getattr(landmark, "visibility", 1.0))
    presence = float(getattr(landmark, "presence", 1.0))
    return max(0.0, min(1.0, min(visibility, presence)))


def count_phase_changes(values: list[float], epsilon: float) -> int:
    signs = []
    for value in values:
        if value > epsilon:
            signs.append(1)
        elif value < -epsilon:
            signs.append(-1)
    if len(signs) < 2:
        return 0
    return sum(1 for before, after in zip(signs, signs[1:]) if before != after)


def midpoint(point_a, point_b) -> tuple[float, float, float]:
    return (
        (point_a[0] + point_b[0]) / 2.0,
        (point_a[1] + point_b[1]) / 2.0,
        (point_a[2] + point_b[2]) / 2.0,
    )


def distance(point_a, point_b) -> float:
    if point_a is None or point_b is None:
        return 0.0
    return hypot(point_a[0] - point_b[0], point_a[1] - point_b[1])


def joint_angle(point_a, point_b, point_c) -> float:
    if point_a is None or point_b is None or point_c is None:
        return 180.0
    vector_a = (
        point_a[0] - point_b[0],
        point_a[1] - point_b[1],
        point_a[2] - point_b[2],
    )
    vector_b = (
        point_c[0] - point_b[0],
        point_c[1] - point_b[1],
        point_c[2] - point_b[2],
    )
    dot = sum(a * b for a, b in zip(vector_a, vector_b))
    norm_a = max(sum(value * value for value in vector_a) ** 0.5, 1e-6)
    norm_b = max(sum(value * value for value in vector_b) ** 0.5, 1e-6)
    cosine = max(-1.0, min(1.0, dot / (norm_a * norm_b)))
    return degrees(acos(cosine))


def torso_angle_from_vertical(point_a, point_b) -> float:
    if point_a is None or point_b is None:
        return 0.0
    dx = point_b[0] - point_a[0]
    dy = point_b[1] - point_a[1]
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return 0.0
    return abs(degrees(atan2(dx, dy)))


def angle_from_horizontal(point_a, point_b) -> float:
    if point_a is None or point_b is None:
        return 90.0
    dx = abs(point_b[0] - point_a[0])
    dy = abs(point_b[1] - point_a[1])
    if dx < 1e-6 and dy < 1e-6:
        return 90.0
    return abs(degrees(atan2(dy, dx)))


def map_pose_detection_to_frame(
    pose: PoseDetection,
    crop_box: tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
) -> PoseDetection:
    x1, y1, x2, y2 = crop_box
    crop_width = max(x2 - x1, 1.0)
    crop_height = max(y2 - y1, 1.0)
    mapped_landmarks = [
        LandmarkPoint(
            x=clamp01((x1 + landmark.x * crop_width) / frame_width),
            y=clamp01((y1 + landmark.y * crop_height) / frame_height),
            z=float(getattr(landmark, "z", 0.0)),
            visibility=float(getattr(landmark, "visibility", 1.0)),
            presence=float(getattr(landmark, "presence", 1.0)),
        )
        for landmark in pose.landmarks
    ]
    return PoseDetection(
        box=pose_box(mapped_landmarks),
        landmarks=mapped_landmarks,
        world_landmarks=pose.world_landmarks,
        confidence=pose.confidence,
        waist=pose_waist(mapped_landmarks),
        features=extract_pose_features(mapped_landmarks),
    )


def smooth_pose_detection(
    previous: PoseDetection | None,
    current: PoseDetection,
    alpha: float = 0.48,
) -> PoseDetection:
    if previous is None or len(previous.landmarks) != len(current.landmarks):
        return current

    smoothed_landmarks = []
    for previous_landmark, current_landmark in zip(previous.landmarks, current.landmarks):
        visibility = float(getattr(current_landmark, "visibility", 1.0))
        presence = float(getattr(current_landmark, "presence", 1.0))
        quality = min(visibility, presence)
        current_alpha = alpha if quality >= 0.45 else 0.32
        jump = distance(
            (float(previous_landmark.x), float(previous_landmark.y)),
            (float(current_landmark.x), float(current_landmark.y)),
        )
        if jump >= 0.16:
            current_alpha = 0.72

        smoothed_landmarks.append(
            LandmarkPoint(
                x=clamp01(
                    float(previous_landmark.x) * (1.0 - current_alpha)
                    + float(current_landmark.x) * current_alpha
                ),
                y=clamp01(
                    float(previous_landmark.y) * (1.0 - current_alpha)
                    + float(current_landmark.y) * current_alpha
                ),
                z=float(previous_landmark.z) * (1.0 - current_alpha)
                + float(getattr(current_landmark, "z", 0.0)) * current_alpha,
                visibility=visibility,
                presence=presence,
            )
        )

    smoothed_confidence = previous.confidence * 0.35 + current.confidence * 0.65
    return PoseDetection(
        box=pose_box(smoothed_landmarks),
        landmarks=smoothed_landmarks,
        world_landmarks=current.world_landmarks,
        confidence=smoothed_confidence,
        waist=pose_waist(smoothed_landmarks),
        features=extract_pose_features(smoothed_landmarks),
    )


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
