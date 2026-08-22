# -*- coding: utf-8 -*-

import argparse
import csv
import math
import os
import statistics
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache

os.environ.setdefault(
    "MPLCONFIGDIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".matplotlib_cache"),
)

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

if not hasattr(mp, "solutions") or not hasattr(mp.solutions, "pose") or not hasattr(mp, "tasks"):
    raise SystemExit(
        "This script needs MediaPipe Solutions and Tasks APIs. "
        "Install the compatible dependency set with: "
        "python -m pip install -r requirements.txt"
    )


DEFAULT_VIDEO_SOURCE = "0"
DEFAULT_POSE_MODEL = "model/pose_landmarker_heavy.task"
DEFAULT_LOG_PATH = "logs/action_status_log.csv"
LOOP_VIDEO = True
DEFAULT_MAX_PEOPLE = 4
PERSON_MATCH_DISTANCE = 0.12
PERSON_LOST_SECONDS = 1.50
POSE_DEDUP_IOU_THRESHOLD = 0.50
POSE_DEDUP_CENTER_DISTANCE = 0.055
POSE_MIN_VISIBLE_LANDMARKS = 5
POSE_MIN_BOX_AREA = 0.002
POSE_MIN_QUALITY = 0.25
POSE_CONFIRM_FRAMES = 2

VISIBILITY_THRESHOLD = 0.45
PRESENCE_THRESHOLD = 0.10
MIN_DETECTION_CONFIDENCE = 0.55
MIN_TRACKING_CONFIDENCE = 0.55
NO_POSE_GRACE_SECONDS = 0.75
FALL_NO_POSE_GRACE_SECONDS = 1.80

FALL_SECONDS = 0.90
FALL_LOST_SECONDS = 0.70
STATIC_FALL_SECONDS = 0.35
TORSO_ANGLE_THRESHOLD = 55.0
SEVERE_TORSO_ANGLE_THRESHOLD = 72.0
WORLD_TORSO_ANGLE_THRESHOLD = 55.0
SEVERE_WORLD_TORSO_ANGLE_THRESHOLD = 72.0
STATIC_FALL_TORSO_ANGLE = 62.0
STATIC_FALL_WORLD_TORSO_ANGLE = 62.0
STATIC_FALL_ASPECT_RATIO = 1.10
STATIC_FALL_STRONG_ASPECT_RATIO = 1.25
STATIC_FALL_CORE_WIDTH_RATIO = 0.45
STATIC_FALL_LIMB_FLAT_RATIO = 0.75
STATIC_FALL_LEG_LEVEL_DELTA = 0.12
STATIC_FALL_MIN_BODY_WIDTH = 0.12
STATIC_FALL_LOW_CENTER_Y = 0.62
STATIC_FALL_LOW_HIP_Y = 0.62
STATIC_FALL_SHORT_BODY_HEIGHT = 0.38
STATIC_FALL_MIN_SCORE = 3
STATIC_FALL_STRONG_SCORE = 4
VERTICAL_VIEW_MAX_TORSO_ANGLE = 35.0
VERTICAL_VIEW_MAX_ASPECT_RATIO = 0.95
VERTICAL_FALL_SECONDS = 0.55
VERTICAL_FALL_MIN_SIGNALS = 3
VERTICAL_FALL_HEIGHT_DROP_RATIO = 0.80
VERTICAL_FALL_TORSO_COLLAPSE_RATIO = 0.72
VERTICAL_FALL_CENTER_DROP_DELTA = 0.06
VERTICAL_FALL_HIP_DROP_DELTA = 0.06
VERTICAL_FALL_CENTER_SPEED = 0.10
VERTICAL_FALL_HIP_SPEED = 0.09
VERTICAL_FALL_LOW_CENTER_Y = 0.58
VERTICAL_FALL_LOW_HIP_Y = 0.58
ASPECT_RATIO_THRESHOLD = 1.05
NEAR_HORIZONTAL_ASPECT_RATIO = 1.25
BODY_HEIGHT_DROP_RATIO = 0.85
BODY_CENTER_DROP_DELTA = 0.08
HIP_DROP_DELTA = 0.08
BODY_CENTER_FALL_SPEED = 0.16
HIP_FALL_SPEED = 0.14
TORSO_ANGLE_CHANGE_THRESHOLD = 22.0
TORSO_COLLAPSE_RATIO = 0.62

WAVE_WINDOW_SECONDS = 2.50
WAVE_MIN_DIRECTION_CHANGES = 2
WAVE_MIN_X_RANGE = 0.08
WAVE_MIN_STEP_X = 0.015

RUN_WINDOW_SECONDS = 2.00
RUN_MIN_CENTER_SPEED = 0.14
RUN_MIN_CADENCE_HZ = 1.80
RUN_MIN_KNEE_SWING = 0.050

UNSTABLE_WINDOW_SECONDS = 4.00
UNSTABLE_MIN_SECONDS = 2.00
UNSTABLE_CENTER_SWAY_STD = 0.025
UNSTABLE_STEP_CV = 0.35
UNSTABLE_TORSO_STD = 8.0
UNSTABLE_CADENCE_CV = 0.45

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils


@lru_cache(maxsize=8)
def get_chinese_font(size):
    font_paths = [
        r"C:\Windows\Fonts\msjh.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\mingliu.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
    ]

    for font_path in font_paths:
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size=size)

    return ImageFont.load_default()


def draw_chinese_text(frame, text, position, font_size=24, color=(255, 255, 255)):
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    rgb_color = (color[2], color[1], color[0])
    draw.text(position, text, font=get_chinese_font(font_size), fill=rgb_color)
    frame[:, :] = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def status_text(detection):
    statuses = []

    if detection.get("fall"):
        statuses.append("\u8dcc\u5012")
    if detection.get("wave"):
        statuses.append("\u63ee\u624b\u6c42\u6551")
    if detection.get("unstable"):
        statuses.append("\u6b65\u4f10\u4e0d\u7a69")
    if detection.get("running"):
        statuses.append("\u8dd1\u6b65")
    if detection.get("tracking_lost") and not statuses:
        statuses.append("\u9aa8\u67b6\u66ab\u6642\u907a\u5931")

    return "\u3001".join(statuses) if statuses else "\u6b63\u5e38"

def open_status_logger(log_path):
    if not log_path:
        return None, None

    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_exists = os.path.exists(log_path)
    log_file = open(log_path, "a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(
        log_file,
        fieldnames=[
            "time_seconds",
            "frame_index",
            "people_count",
            "person_id",
            "status",
            "fall",
            "wave",
            "unstable",
            "running",
            "tracking_lost",
            "fall_counter",
            "fall_signals",
        ],
    )

    if not file_exists or os.path.getsize(log_path) == 0:
        writer.writeheader()

    return log_file, writer


def write_status_log(writer, elapsed_seconds, frame_index, people_count, detections):
    if writer is None:
        return

    if not detections:
        writer.writerow(
            {
                "time_seconds": f"{elapsed_seconds:.2f}",
                "frame_index": frame_index,
                "people_count": people_count,
                "person_id": "",
                "status": "\u7121\u4eba",
                "fall": 0,
                "wave": 0,
                "unstable": 0,
                "running": 0,
                "tracking_lost": 0,
                "fall_counter": 0,
                "fall_signals": 0,
            }
        )
        return

    for person_id, detection, landmarks in detections:
        if landmarks is None and not detection.get("fall"):
            continue

        fall_info = detection.get("fall_info", {})
        writer.writerow(
            {
                "time_seconds": f"{elapsed_seconds:.2f}",
                "frame_index": frame_index,
                "people_count": people_count,
                "person_id": person_id,
                "status": status_text(detection),
                "fall": int(bool(detection.get("fall"))),
                "wave": int(bool(detection.get("wave"))),
                "unstable": int(bool(detection.get("unstable"))),
                "running": int(bool(detection.get("running"))),
                "tracking_lost": int(bool(detection.get("tracking_lost"))),
                "fall_counter": fall_info.get("counter", 0),
                "fall_signals": fall_info.get("signal_count", 0),
            }
        )


def has_any_alert(detections):
    for _, detection, _ in detections:
        if (
            detection.get("fall")
            or detection.get("wave")
            or detection.get("unstable")
            or detection.get("running")
        ):
            return True

    return False


@dataclass
class PoseSnapshot:
    timestamp: float
    shoulder_center: tuple
    hip_center: tuple
    body_center: tuple
    left_wrist: tuple
    right_wrist: tuple
    left_ankle: tuple
    right_ankle: tuple
    left_knee: tuple
    right_knee: tuple
    left_foot: tuple
    right_foot: tuple
    torso_angle: float
    aspect_ratio: float
    body_width: float
    body_height: float
    step_distance: float
    torso_angle_3d: float
    torso_vertical_span: float


def parse_video_source(value):
    if isinstance(value, int):
        return value

    value = str(value).strip()
    if value.isdigit():
        return int(value)

    return value


def open_video_source(video_source):
    if isinstance(video_source, int):
        return cv2.VideoCapture(video_source, cv2.CAP_DSHOW)

    return cv2.VideoCapture(video_source)


def reset_video(cap):
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)


def is_visible(landmarks, point):
    landmark = landmarks[point.value]
    return is_reliable_landmark(landmark)


def is_reliable_landmark(landmark):
    presence = getattr(landmark, "presence", 1.0)
    return landmark.visibility >= VISIBILITY_THRESHOLD and presence >= PRESENCE_THRESHOLD


def require_points(landmarks, points):
    return all(is_visible(landmarks, point) for point in points)


def xy(landmarks, point):
    landmark = landmarks[point.value]
    return landmark.x, landmark.y


def xyz(landmarks, point):
    landmark = landmarks[point.value]
    return landmark.x, landmark.y, landmark.z


def optional_xy(landmarks, point):
    if not is_visible(landmarks, point):
        return None
    return xy(landmarks, point)


def average_points(points):
    visible_points = [point for point in points if point is not None]
    if not visible_points:
        return None

    return (
        sum(point[0] for point in visible_points) / len(visible_points),
        sum(point[1] for point in visible_points) / len(visible_points),
    )


def average_points_3d(points):
    visible_points = [point for point in points if point is not None]
    if not visible_points:
        return None

    return (
        sum(point[0] for point in visible_points) / len(visible_points),
        sum(point[1] for point in visible_points) / len(visible_points),
        sum(point[2] for point in visible_points) / len(visible_points),
    )


def center(point_a, point_b):
    return (point_a[0] + point_b[0]) / 2.0, (point_a[1] + point_b[1]) / 2.0


def distance(point_a, point_b):
    if point_a is None or point_b is None:
        return None
    return math.hypot(point_a[0] - point_b[0], point_a[1] - point_b[1])


def draw_pose_landmarks(frame, landmarks, color=(0, 255, 0)):
    height, width = frame.shape[:2]

    for start_idx, end_idx in mp_pose.POSE_CONNECTIONS:
        start = landmarks[start_idx]
        end = landmarks[end_idx]

        if not is_reliable_landmark(start) or not is_reliable_landmark(end):
            continue

        start_point = int(start.x * width), int(start.y * height)
        end_point = int(end.x * width), int(end.y * height)
        cv2.line(frame, start_point, end_point, color, 2)

    for landmark in landmarks:
        if not is_reliable_landmark(landmark):
            continue

        point = int(landmark.x * width), int(landmark.y * height)
        cv2.circle(frame, point, 3, color, -1)


def calculate_torso_angle(shoulder_center, hip_center):
    dx = hip_center[0] - shoulder_center[0]
    dy = hip_center[1] - shoulder_center[1]
    return math.degrees(math.atan2(abs(dx), abs(dy)))


def calculate_torso_angle_3d(world_landmarks):
    if world_landmarks is None:
        return None

    shoulder_center = average_points_3d(
        [
            xyz(world_landmarks, mp_pose.PoseLandmark.LEFT_SHOULDER)
            if is_visible(world_landmarks, mp_pose.PoseLandmark.LEFT_SHOULDER)
            else None,
            xyz(world_landmarks, mp_pose.PoseLandmark.RIGHT_SHOULDER)
            if is_visible(world_landmarks, mp_pose.PoseLandmark.RIGHT_SHOULDER)
            else None,
        ]
    )
    hip_center = average_points_3d(
        [
            xyz(world_landmarks, mp_pose.PoseLandmark.LEFT_HIP)
            if is_visible(world_landmarks, mp_pose.PoseLandmark.LEFT_HIP)
            else None,
            xyz(world_landmarks, mp_pose.PoseLandmark.RIGHT_HIP)
            if is_visible(world_landmarks, mp_pose.PoseLandmark.RIGHT_HIP)
            else None,
        ]
    )

    if shoulder_center is None or hip_center is None:
        return None

    dx = hip_center[0] - shoulder_center[0]
    dy = hip_center[1] - shoulder_center[1]
    dz = hip_center[2] - shoulder_center[2]
    horizontal_component = math.sqrt(dx * dx + dz * dz)

    return math.degrees(math.atan2(horizontal_component, abs(dy)))


def calculate_body_box(landmarks):
    important_points = [
        mp_pose.PoseLandmark.NOSE,
        mp_pose.PoseLandmark.LEFT_SHOULDER,
        mp_pose.PoseLandmark.RIGHT_SHOULDER,
        mp_pose.PoseLandmark.LEFT_HIP,
        mp_pose.PoseLandmark.RIGHT_HIP,
        mp_pose.PoseLandmark.LEFT_KNEE,
        mp_pose.PoseLandmark.RIGHT_KNEE,
        mp_pose.PoseLandmark.LEFT_ANKLE,
        mp_pose.PoseLandmark.RIGHT_ANKLE,
        mp_pose.PoseLandmark.LEFT_FOOT_INDEX,
        mp_pose.PoseLandmark.RIGHT_FOOT_INDEX,
    ]

    xs = []
    ys = []

    for point in important_points:
        landmark = landmarks[point.value]
        if is_reliable_landmark(landmark):
            xs.append(landmark.x)
            ys.append(landmark.y)

    if len(xs) < 4:
        return 0.0, 0.0, 0.0

    body_width = max(xs) - min(xs)
    body_height = max(ys) - min(ys)
    aspect_ratio = body_width / body_height if body_height > 0 else 0.0

    return body_width, body_height, aspect_ratio


def landmark_confidence(landmark):
    presence = getattr(landmark, "presence", 1.0)
    return (landmark.visibility + presence) / 2.0


def pose_box(landmarks):
    xs = []
    ys = []

    for landmark in landmarks:
        presence = getattr(landmark, "presence", 1.0)
        if landmark.visibility < 0.25 or presence < 0.05:
            continue
        xs.append(min(max(landmark.x, 0.0), 1.0))
        ys.append(min(max(landmark.y, 0.0), 1.0))

    if len(xs) < POSE_MIN_VISIBLE_LANDMARKS:
        return None

    return min(xs), min(ys), max(xs), max(ys)


def box_area(box):
    if box is None:
        return 0.0

    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def box_center(box):
    return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0


def box_iou(box_a, box_b):
    left = max(box_a[0], box_b[0])
    top = max(box_a[1], box_b[1])
    right = min(box_a[2], box_b[2])
    bottom = min(box_a[3], box_b[3])

    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = box_area(box_a) + box_area(box_b) - intersection

    if union <= 0:
        return 0.0

    return intersection / union


def pose_quality(landmarks):
    important_points = [
        mp_pose.PoseLandmark.NOSE,
        mp_pose.PoseLandmark.LEFT_SHOULDER,
        mp_pose.PoseLandmark.RIGHT_SHOULDER,
        mp_pose.PoseLandmark.LEFT_HIP,
        mp_pose.PoseLandmark.RIGHT_HIP,
        mp_pose.PoseLandmark.LEFT_KNEE,
        mp_pose.PoseLandmark.RIGHT_KNEE,
        mp_pose.PoseLandmark.LEFT_ANKLE,
        mp_pose.PoseLandmark.RIGHT_ANKLE,
    ]

    scores = []
    for point in important_points:
        landmark = landmarks[point.value]
        if landmark.visibility >= 0.20:
            scores.append(landmark_confidence(landmark))

    if len(scores) < POSE_MIN_VISIBLE_LANDMARKS:
        return 0.0

    scores.sort(reverse=True)
    return statistics.mean(scores[: min(8, len(scores))])


def are_duplicate_poses(candidate, kept_candidate):
    iou = box_iou(candidate["box"], kept_candidate["box"])
    center_distance = distance(box_center(candidate["box"]), box_center(kept_candidate["box"]))

    if iou >= POSE_DEDUP_IOU_THRESHOLD:
        return True

    return center_distance is not None and center_distance <= POSE_DEDUP_CENTER_DISTANCE and iou > 0.10


def deduplicate_pose_results(pose_landmarks, pose_world_landmarks):
    candidates = []

    for index, landmarks in enumerate(pose_landmarks):
        box = pose_box(landmarks)
        quality = pose_quality(landmarks)
        if box is None or box_area(box) < POSE_MIN_BOX_AREA or quality < POSE_MIN_QUALITY:
            continue

        candidates.append(
            {
                "index": index,
                "landmarks": landmarks,
                "world_landmarks": (
                    pose_world_landmarks[index]
                    if pose_world_landmarks and index < len(pose_world_landmarks)
                    else None
                ),
                "box": box,
                "quality": quality,
            }
        )

    candidates.sort(key=lambda item: item["quality"], reverse=True)
    kept = []

    for candidate in candidates:
        if any(are_duplicate_poses(candidate, kept_candidate) for kept_candidate in kept):
            continue
        kept.append(candidate)

    kept.sort(key=lambda item: box_center(item["box"])[0])

    return (
        [candidate["landmarks"] for candidate in kept],
        [candidate["world_landmarks"] for candidate in kept],
        kept,
    )


def build_pose_snapshot(landmarks, timestamp, world_landmarks=None):
    left_shoulder = optional_xy(landmarks, mp_pose.PoseLandmark.LEFT_SHOULDER)
    right_shoulder = optional_xy(landmarks, mp_pose.PoseLandmark.RIGHT_SHOULDER)
    left_hip = optional_xy(landmarks, mp_pose.PoseLandmark.LEFT_HIP)
    right_hip = optional_xy(landmarks, mp_pose.PoseLandmark.RIGHT_HIP)
    left_ankle = optional_xy(landmarks, mp_pose.PoseLandmark.LEFT_ANKLE)
    right_ankle = optional_xy(landmarks, mp_pose.PoseLandmark.RIGHT_ANKLE)

    shoulder_center = average_points([left_shoulder, right_shoulder])
    hip_center = average_points([left_hip, right_hip])

    if shoulder_center is None or hip_center is None:
        return None

    body_center = center(shoulder_center, hip_center)
    body_width, body_height, aspect_ratio = calculate_body_box(landmarks)

    return PoseSnapshot(
        timestamp=timestamp,
        shoulder_center=shoulder_center,
        hip_center=hip_center,
        body_center=body_center,
        left_wrist=optional_xy(landmarks, mp_pose.PoseLandmark.LEFT_WRIST),
        right_wrist=optional_xy(landmarks, mp_pose.PoseLandmark.RIGHT_WRIST),
        left_ankle=left_ankle,
        right_ankle=right_ankle,
        left_knee=optional_xy(landmarks, mp_pose.PoseLandmark.LEFT_KNEE),
        right_knee=optional_xy(landmarks, mp_pose.PoseLandmark.RIGHT_KNEE),
        left_foot=xy(landmarks, mp_pose.PoseLandmark.LEFT_FOOT_INDEX)
        if is_visible(landmarks, mp_pose.PoseLandmark.LEFT_FOOT_INDEX)
        else left_ankle,
        right_foot=xy(landmarks, mp_pose.PoseLandmark.RIGHT_FOOT_INDEX)
        if is_visible(landmarks, mp_pose.PoseLandmark.RIGHT_FOOT_INDEX)
        else right_ankle,
        torso_angle=calculate_torso_angle(shoulder_center, hip_center),
        aspect_ratio=aspect_ratio,
        body_width=body_width,
        body_height=body_height,
        step_distance=distance(left_ankle, right_ankle),
        torso_angle_3d=calculate_torso_angle_3d(world_landmarks),
        torso_vertical_span=abs(hip_center[1] - shoulder_center[1]),
    )


def recent_items(history, seconds):
    if not history:
        return []

    cutoff = history[-1].timestamp - seconds
    return [item for item in history if item.timestamp >= cutoff]


def stddev(values):
    if len(values) < 2:
        return 0.0
    return statistics.pstdev(values)


def coefficient_of_variation(values):
    if len(values) < 2:
        return 0.0

    mean_value = statistics.mean(values)
    if abs(mean_value) < 1e-6:
        return 0.0

    return stddev(values) / abs(mean_value)


def alternating_events(history):
    events = []
    last_sign = 0

    for item in history:
        if item.left_ankle is None or item.right_ankle is None:
            continue

        diff = item.left_ankle[1] - item.right_ankle[1]
        if abs(diff) < 0.015:
            continue

        sign = 1 if diff > 0 else -1
        if last_sign and sign != last_sign:
            events.append(item.timestamp)
        last_sign = sign

    return events


class ActionDetector:
    def __init__(self, fps):
        self.fps = max(float(fps), 1.0)
        self.history = deque(maxlen=int(self.fps * 6))
        self.fall_counter = 0
        self.static_fall_counter = 0
        self.vertical_fall_counter = 0
        self.last_pose_timestamp = None
        self.last_detection = None
        self.wave_states = {
            "left": self._new_wave_state(),
            "right": self._new_wave_state(),
        }

    @staticmethod
    def _new_wave_state():
        return {
            "positions": deque(),
            "turns": deque(),
            "last_x": None,
            "last_direction": 0,
        }

    def update(self, landmarks, timestamp, world_landmarks=None):
        snapshot = build_pose_snapshot(landmarks, timestamp, world_landmarks)
        if snapshot is None:
            return self.update_no_pose(timestamp)

        self.last_pose_timestamp = timestamp
        self.history.append(snapshot)

        fall, fall_info = self.detect_fall(snapshot)
        running, running_info = self.detect_running()
        unstable, unstable_info = self.detect_unstable()
        wave, wave_hand = self.detect_wave(snapshot)

        if running:
            unstable = False

        detection = {
            "pose": snapshot,
            "fall": fall,
            "running": running,
            "unstable": unstable,
            "wave": wave,
            "wave_hand": wave_hand,
            "tracking_lost": False,
            "fall_info": fall_info,
            "running_info": running_info,
            "unstable_info": unstable_info,
        }

        self.last_detection = detection
        return detection

    def update_no_pose(self, timestamp):
        if self.last_pose_timestamp is None:
            return self.empty_detection(tracking_lost=True)

        missing_seconds = timestamp - self.last_pose_timestamp
        short_gap = missing_seconds <= NO_POSE_GRACE_SECONDS
        fall_gap = missing_seconds <= FALL_NO_POSE_GRACE_SECONDS
        last_fall_info = {}

        if self.last_detection is not None:
            last_fall_info = self.last_detection.get("fall_info", {})

        likely_fall_before_loss = (
            last_fall_info.get("condition", False)
            or last_fall_info.get("static_condition", False)
            or last_fall_info.get("vertical_condition", False)
            or last_fall_info.get("static_score", 0) >= STATIC_FALL_MIN_SCORE
            or last_fall_info.get("pre_fall_motion", False)
            or last_fall_info.get("signal_count", 0) >= 2
        )

        if fall_gap and (self.fall_counter > 0 or likely_fall_before_loss):
            self.fall_counter += 1
            self.static_fall_counter = max(self.static_fall_counter, self.fall_counter)
            self.vertical_fall_counter = max(self.vertical_fall_counter, self.fall_counter)
        elif not short_gap:
            self.fall_counter = max(0, self.fall_counter - 1)
            self.static_fall_counter = max(0, self.static_fall_counter - 1)
            self.vertical_fall_counter = max(0, self.vertical_fall_counter - 1)

        if self.last_detection is None or not short_gap:
            detection = self.empty_detection(tracking_lost=True)
            detection["fall_info"]["counter"] = self.fall_counter
            detection["fall_info"]["static_counter"] = self.static_fall_counter
            detection["fall_info"]["vertical_counter"] = self.vertical_fall_counter
            detection["fall_info"]["likely_fall_before_loss"] = likely_fall_before_loss
            detection["fall"] = self.is_fall_confirmed()
            return detection

        detection = dict(self.last_detection)
        fall_info = dict(detection.get("fall_info", {}))
        fall_info["counter"] = self.fall_counter
        fall_info["static_counter"] = self.static_fall_counter
        fall_info["vertical_counter"] = self.vertical_fall_counter
        fall_info["missing_seconds"] = missing_seconds
        fall_info["likely_fall_before_loss"] = likely_fall_before_loss
        detection["fall_info"] = fall_info
        detection["tracking_lost"] = True
        detection["fall"] = self.is_fall_confirmed()
        detection["running"] = False
        detection["unstable"] = False
        detection["wave"] = False
        detection["wave_hand"] = ""
        return detection

    @staticmethod
    def empty_detection(tracking_lost=False):
        return {
            "pose": None,
            "fall": False,
            "running": False,
            "unstable": False,
            "wave": False,
            "wave_hand": "",
            "tracking_lost": tracking_lost,
            "fall_info": {
                "counter": 0,
                "static_counter": 0,
                "vertical_counter": 0,
                "static_score": 0,
                "vertical_score": 0,
                "signal_count": 0,
            },
            "running_info": {
                "speed": 0.0,
                "cadence": 0.0,
                "knee_swing": 0.0,
            },
            "unstable_info": {
                "sway": 0.0,
                "step_cv": 0.0,
                "torso_std": 0.0,
                "cadence_cv": 0.0,
            },
        }

    def is_fall_confirmed(self):
        dynamic_frames = max(1, int(self.fps * FALL_SECONDS))
        static_frames = max(1, int(self.fps * STATIC_FALL_SECONDS))
        vertical_frames = max(1, int(self.fps * VERTICAL_FALL_SECONDS))
        return (
            self.fall_counter >= dynamic_frames
            or self.static_fall_counter >= static_frames
            or self.vertical_fall_counter >= vertical_frames
        )

    @staticmethod
    def _point_bounds(points):
        visible_points = [point for point in points if point is not None]
        if len(visible_points) < 2:
            return None

        xs = [point[0] for point in visible_points]
        ys = [point[1] for point in visible_points]
        return min(xs), min(ys), max(xs), max(ys), len(visible_points)

    def detect_static_fall(self, snapshot):
        torso_horizontal = snapshot.torso_angle >= STATIC_FALL_TORSO_ANGLE
        world_torso_horizontal = (
            snapshot.torso_angle_3d is not None
            and snapshot.torso_angle_3d >= STATIC_FALL_WORLD_TORSO_ANGLE
        )
        flat_box = snapshot.aspect_ratio >= STATIC_FALL_ASPECT_RATIO
        strong_flat_box = snapshot.aspect_ratio >= STATIC_FALL_STRONG_ASPECT_RATIO

        core_width_ratio = 99.0
        core_flat = False
        if snapshot.body_width > 0:
            core_width_ratio = snapshot.torso_vertical_span / snapshot.body_width
            core_flat = core_width_ratio <= STATIC_FALL_CORE_WIDTH_RATIO

        pose_points = [
            snapshot.shoulder_center,
            snapshot.hip_center,
            snapshot.left_knee,
            snapshot.right_knee,
            snapshot.left_ankle,
            snapshot.right_ankle,
            snapshot.left_foot,
            snapshot.right_foot,
        ]
        point_box = self._point_bounds(pose_points)

        limb_flat_ratio = 99.0
        limb_flat = False
        enough_horizontal_span = snapshot.body_width >= STATIC_FALL_MIN_BODY_WIDTH
        if point_box is not None:
            min_x, min_y, max_x, max_y, point_count = point_box
            point_width = max_x - min_x
            point_height = max_y - min_y
            if point_width > 0:
                limb_flat_ratio = point_height / point_width
                limb_flat = (
                    point_count >= 5
                    and point_width >= STATIC_FALL_MIN_BODY_WIDTH
                    and limb_flat_ratio <= STATIC_FALL_LIMB_FLAT_RATIO
                )

        lower_points = [
            snapshot.left_knee,
            snapshot.right_knee,
            snapshot.left_ankle,
            snapshot.right_ankle,
            snapshot.left_foot,
            snapshot.right_foot,
        ]
        lower_center = average_points(lower_points)
        leg_level_delta = 99.0
        legs_near_core_level = False
        if lower_center is not None:
            leg_level_delta = abs(lower_center[1] - snapshot.hip_center[1])
            legs_near_core_level = leg_level_delta <= STATIC_FALL_LEG_LEVEL_DELTA

        low_body = (
            snapshot.body_center[1] >= STATIC_FALL_LOW_CENTER_Y
            or snapshot.hip_center[1] >= STATIC_FALL_LOW_HIP_Y
        )
        short_body = (
            0.0 < snapshot.body_height <= STATIC_FALL_SHORT_BODY_HEIGHT
            and snapshot.body_width >= 0.06
        )

        static_score = sum(
            [
                torso_horizontal,
                world_torso_horizontal,
                flat_box,
                strong_flat_box,
                core_flat,
                limb_flat,
                legs_near_core_level,
                low_body,
                short_body,
            ]
        )
        has_orientation_evidence = (
            torso_horizontal
            or world_torso_horizontal
            or strong_flat_box
            or core_flat
        )
        low_compact_fall = (
            low_body
            and short_body
            and (legs_near_core_level or limb_flat or core_flat)
            and static_score >= STATIC_FALL_MIN_SCORE + 1
        )
        clear_upright = (
            snapshot.torso_angle < 35.0
            and (snapshot.torso_angle_3d is None or snapshot.torso_angle_3d < 35.0)
            and snapshot.aspect_ratio < 0.85
            and not low_compact_fall
            and not core_flat
        )

        static_condition = (
            (
                static_score >= STATIC_FALL_MIN_SCORE
                and has_orientation_evidence
                and enough_horizontal_span
            )
            or low_compact_fall
        ) and not clear_upright
        strong_static_condition = (
            (
                static_score >= STATIC_FALL_STRONG_SCORE
                and (strong_flat_box or torso_horizontal or world_torso_horizontal)
                and (core_flat or limb_flat or legs_near_core_level)
                and enough_horizontal_span
            )
            or (
                low_compact_fall
                and static_score >= STATIC_FALL_STRONG_SCORE + 1
            )
        )
        strong_static_condition = strong_static_condition and not clear_upright

        return {
            "condition": static_condition,
            "strong_condition": strong_static_condition,
            "score": static_score,
            "torso_horizontal": torso_horizontal,
            "world_torso_horizontal": world_torso_horizontal,
            "flat_box": flat_box,
            "strong_flat_box": strong_flat_box,
            "core_flat": core_flat,
            "limb_flat": limb_flat,
            "legs_near_core_level": legs_near_core_level,
            "low_body": low_body,
            "short_body": short_body,
            "low_compact_fall": low_compact_fall,
            "core_width_ratio": core_width_ratio,
            "limb_flat_ratio": limb_flat_ratio,
            "leg_level_delta": leg_level_delta,
        }

    def detect_vertical_view_fall(
        self,
        snapshot,
        max_height,
        max_torso_span,
        min_body_center_y,
        min_hip_y,
        center_fall_speed,
        hip_fall_speed,
        static_fall_info,
    ):
        vertical_view_pose = (
            snapshot.torso_angle <= VERTICAL_VIEW_MAX_TORSO_ANGLE
            and snapshot.aspect_ratio <= VERTICAL_VIEW_MAX_ASPECT_RATIO
        )
        if snapshot.torso_angle_3d is not None:
            vertical_view_pose = (
                vertical_view_pose
                and snapshot.torso_angle_3d <= VERTICAL_VIEW_MAX_TORSO_ANGLE + 8.0
            )

        height_compressed = (
            max_height > 0
            and snapshot.body_height <= max_height * VERTICAL_FALL_HEIGHT_DROP_RATIO
        )
        torso_compressed = (
            max_torso_span > 0
            and snapshot.torso_vertical_span <= max_torso_span * VERTICAL_FALL_TORSO_COLLAPSE_RATIO
        )
        center_dropped = snapshot.body_center[1] >= min_body_center_y + VERTICAL_FALL_CENTER_DROP_DELTA
        hip_dropped = snapshot.hip_center[1] >= min_hip_y + VERTICAL_FALL_HIP_DROP_DELTA
        fast_drop = (
            center_fall_speed >= VERTICAL_FALL_CENTER_SPEED
            or hip_fall_speed >= VERTICAL_FALL_HIP_SPEED
        )
        low_body = (
            snapshot.body_center[1] >= VERTICAL_FALL_LOW_CENTER_Y
            or snapshot.hip_center[1] >= VERTICAL_FALL_LOW_HIP_Y
        )
        low_compact_static = static_fall_info.get("low_compact_fall", False)
        lower_level_static = (
            static_fall_info.get("legs_near_core_level", False)
            or static_fall_info.get("limb_flat", False)
        )

        vertical_score = sum(
            [
                height_compressed,
                torso_compressed,
                center_dropped,
                hip_dropped,
                fast_drop,
                low_body,
                low_compact_static,
                lower_level_static,
            ]
        )
        motion_evidence = fast_drop or center_dropped or hip_dropped
        compression_evidence = height_compressed or torso_compressed or low_compact_static
        ground_evidence = low_body or lower_level_static

        vertical_condition = (
            vertical_view_pose
            and motion_evidence
            and compression_evidence
            and ground_evidence
            and vertical_score >= VERTICAL_FALL_MIN_SIGNALS
        )
        strong_vertical_condition = (
            vertical_condition
            and vertical_score >= VERTICAL_FALL_MIN_SIGNALS + 2
            and fast_drop
        )

        return {
            "condition": vertical_condition,
            "strong_condition": strong_vertical_condition,
            "score": vertical_score,
            "vertical_view_pose": vertical_view_pose,
            "height_compressed": height_compressed,
            "torso_compressed": torso_compressed,
            "center_dropped": center_dropped,
            "hip_dropped": hip_dropped,
            "fast_drop": fast_drop,
            "low_body": low_body,
            "lower_level_static": lower_level_static,
        }

    def detect_fall(self, snapshot):
        recent = recent_items(self.history, 2.0)
        short_recent = recent_items(self.history, 0.75)
        recent_heights = [item.body_height for item in recent if item.body_height > 0]
        max_height = max(recent_heights, default=snapshot.body_height)
        min_body_center_y = min((item.body_center[1] for item in recent), default=snapshot.body_center[1])
        min_hip_y = min((item.hip_center[1] for item in recent), default=snapshot.hip_center[1])
        max_torso_span = max((item.torso_vertical_span for item in recent), default=snapshot.torso_vertical_span)

        height_drop = max_height > 0 and snapshot.body_height < max_height * BODY_HEIGHT_DROP_RATIO
        center_drop = snapshot.body_center[1] > min_body_center_y + BODY_CENTER_DROP_DELTA
        hip_drop = snapshot.hip_center[1] > min_hip_y + HIP_DROP_DELTA
        torso_collapse = (
            max_torso_span > 0
            and snapshot.torso_vertical_span < max_torso_span * TORSO_COLLAPSE_RATIO
        )
        wide_body = snapshot.aspect_ratio >= ASPECT_RATIO_THRESHOLD
        near_horizontal = snapshot.aspect_ratio >= NEAR_HORIZONTAL_ASPECT_RATIO
        torso_tilted = snapshot.torso_angle >= TORSO_ANGLE_THRESHOLD
        severe_tilt = snapshot.torso_angle >= SEVERE_TORSO_ANGLE_THRESHOLD
        world_tilted = (
            snapshot.torso_angle_3d is not None
            and snapshot.torso_angle_3d >= WORLD_TORSO_ANGLE_THRESHOLD
        )
        severe_world_tilt = (
            snapshot.torso_angle_3d is not None
            and snapshot.torso_angle_3d >= SEVERE_WORLD_TORSO_ANGLE_THRESHOLD
        )

        center_fall_speed = 0.0
        hip_fall_speed = 0.0
        torso_angle_change = 0.0

        if len(short_recent) >= 2:
            first = short_recent[0]
            duration = max(snapshot.timestamp - first.timestamp, 1e-6)
            center_fall_speed = (snapshot.body_center[1] - first.body_center[1]) / duration
            hip_fall_speed = (snapshot.hip_center[1] - first.hip_center[1]) / duration
            torso_angle_change = snapshot.torso_angle - first.torso_angle

        fast_center_drop = center_fall_speed >= BODY_CENTER_FALL_SPEED
        fast_hip_drop = hip_fall_speed >= HIP_FALL_SPEED
        torso_angle_jump = torso_angle_change >= TORSO_ANGLE_CHANGE_THRESHOLD
        static_fall_info = self.detect_static_fall(snapshot)
        static_fall_condition = static_fall_info["condition"]
        strong_static_fall = static_fall_info["strong_condition"]
        vertical_fall_info = self.detect_vertical_view_fall(
            snapshot,
            max_height,
            max_torso_span,
            min_body_center_y,
            min_hip_y,
            center_fall_speed,
            hip_fall_speed,
            static_fall_info,
        )
        vertical_fall_condition = vertical_fall_info["condition"]
        strong_vertical_fall = vertical_fall_info["strong_condition"]

        orientation_signal = torso_tilted or world_tilted
        shape_or_drop_signal = (
            wide_body
            or height_drop
            or center_drop
            or hip_drop
            or near_horizontal
            or torso_collapse
            or fast_center_drop
            or fast_hip_drop
        )
        signal_count = sum(
            [
                torso_tilted,
                world_tilted,
                wide_body,
                height_drop,
                center_drop,
                hip_drop,
                near_horizontal,
                torso_collapse,
                fast_center_drop,
                fast_hip_drop,
                torso_angle_jump,
            ]
        )

        pre_fall_motion = (
            (fast_center_drop or fast_hip_drop)
            and (torso_tilted or world_tilted or torso_angle_jump or torso_collapse or height_drop)
        )

        fall_condition = (
            orientation_signal
            and shape_or_drop_signal
        ) or (
            (severe_tilt or severe_world_tilt)
            and signal_count >= 2
        ) or (
            pre_fall_motion
            and signal_count >= 2
        ) or (
            static_fall_condition
        ) or (
            vertical_fall_condition
        )

        if fall_condition:
            self.fall_counter += 1
        else:
            self.fall_counter = max(0, self.fall_counter - 1)

        if static_fall_condition:
            self.static_fall_counter += 2 if strong_static_fall else 1
        else:
            self.static_fall_counter = max(0, self.static_fall_counter - 1)

        if vertical_fall_condition:
            self.vertical_fall_counter += 2 if strong_vertical_fall else 1
        else:
            self.vertical_fall_counter = max(0, self.vertical_fall_counter - 1)

        return self.is_fall_confirmed(), {
            "condition": fall_condition,
            "counter": self.fall_counter,
            "static_condition": static_fall_condition,
            "strong_static_condition": strong_static_fall,
            "static_counter": self.static_fall_counter,
            "static_score": static_fall_info["score"],
            "vertical_condition": vertical_fall_condition,
            "strong_vertical_condition": strong_vertical_fall,
            "vertical_counter": self.vertical_fall_counter,
            "vertical_score": vertical_fall_info["score"],
            "vertical_view_pose": vertical_fall_info["vertical_view_pose"],
            "vertical_height_compressed": vertical_fall_info["height_compressed"],
            "vertical_torso_compressed": vertical_fall_info["torso_compressed"],
            "vertical_center_dropped": vertical_fall_info["center_dropped"],
            "vertical_hip_dropped": vertical_fall_info["hip_dropped"],
            "vertical_fast_drop": vertical_fall_info["fast_drop"],
            "vertical_low_body": vertical_fall_info["low_body"],
            "vertical_lower_level_static": vertical_fall_info["lower_level_static"],
            "static_core_width_ratio": static_fall_info["core_width_ratio"],
            "static_limb_flat_ratio": static_fall_info["limb_flat_ratio"],
            "static_leg_level_delta": static_fall_info["leg_level_delta"],
            "static_torso_horizontal": static_fall_info["torso_horizontal"],
            "static_world_torso_horizontal": static_fall_info["world_torso_horizontal"],
            "static_flat_box": static_fall_info["flat_box"],
            "static_core_flat": static_fall_info["core_flat"],
            "static_limb_flat": static_fall_info["limb_flat"],
            "static_legs_near_core_level": static_fall_info["legs_near_core_level"],
            "static_low_body": static_fall_info["low_body"],
            "static_short_body": static_fall_info["short_body"],
            "static_low_compact_fall": static_fall_info["low_compact_fall"],
            "height_drop": height_drop,
            "center_drop": center_drop,
            "hip_drop": hip_drop,
            "wide_body": wide_body,
            "near_horizontal": near_horizontal,
            "torso_collapse": torso_collapse,
            "fast_center_drop": fast_center_drop,
            "fast_hip_drop": fast_hip_drop,
            "torso_angle_jump": torso_angle_jump,
            "pre_fall_motion": pre_fall_motion,
            "signal_count": signal_count,
            "max_height": max_height,
            "center_fall_speed": center_fall_speed,
            "hip_fall_speed": hip_fall_speed,
        }

    def detect_running(self):
        window = recent_items(self.history, RUN_WINDOW_SECONDS)
        if len(window) < max(6, int(self.fps * 0.6)):
            return False, {"speed": 0.0, "cadence": 0.0, "knee_swing": 0.0}

        duration = window[-1].timestamp - window[0].timestamp
        if duration <= 0:
            return False, {"speed": 0.0, "cadence": 0.0, "knee_swing": 0.0}

        center_speed = distance(window[0].body_center, window[-1].body_center) / duration
        if any(
            item.left_ankle is None
            or item.right_ankle is None
            or item.left_knee is None
            or item.right_knee is None
            for item in window
        ):
            return False, {"speed": center_speed, "cadence": 0.0, "knee_swing": 0.0}

        events = alternating_events(window)
        cadence = len(events) / duration
        left_knee_swing = stddev([item.left_knee[1] for item in window])
        right_knee_swing = stddev([item.right_knee[1] for item in window])
        knee_swing = (left_knee_swing + right_knee_swing) / 2.0

        fast_motion = center_speed >= RUN_MIN_CENTER_SPEED and cadence >= RUN_MIN_CADENCE_HZ
        running_in_place = cadence >= RUN_MIN_CADENCE_HZ + 0.4 and knee_swing >= RUN_MIN_KNEE_SWING

        return fast_motion or running_in_place, {
            "speed": center_speed,
            "cadence": cadence,
            "knee_swing": knee_swing,
        }

    def detect_unstable(self):
        window = recent_items(self.history, UNSTABLE_WINDOW_SECONDS)
        if len(window) < max(8, int(self.fps * UNSTABLE_MIN_SECONDS)):
            return False, {
                "sway": 0.0,
                "step_cv": 0.0,
                "torso_std": 0.0,
                "cadence_cv": 0.0,
            }

        sway = stddev([item.body_center[0] for item in window])
        step_distances = [item.step_distance for item in window if item.step_distance is not None]
        step_cv = coefficient_of_variation(step_distances)
        torso_std = stddev([item.torso_angle for item in window])

        events = alternating_events(window)
        intervals = [
            events[index] - events[index - 1]
            for index in range(1, len(events))
            if events[index] > events[index - 1]
        ]
        cadence_cv = coefficient_of_variation(intervals)

        unstable_signals = [
            sway >= UNSTABLE_CENTER_SWAY_STD,
            step_cv >= UNSTABLE_STEP_CV,
            torso_std >= UNSTABLE_TORSO_STD,
            cadence_cv >= UNSTABLE_CADENCE_CV and len(intervals) >= 3,
        ]

        return sum(unstable_signals) >= 2, {
            "sway": sway,
            "step_cv": step_cv,
            "torso_std": torso_std,
            "cadence_cv": cadence_cv,
        }

    def detect_wave(self, snapshot):
        left_wave = self._update_wave_state(
            "left",
            snapshot.left_wrist,
            snapshot.shoulder_center,
            snapshot.timestamp,
        )
        right_wave = self._update_wave_state(
            "right",
            snapshot.right_wrist,
            snapshot.shoulder_center,
            snapshot.timestamp,
        )

        if left_wave and right_wave:
            return True, "both"
        if left_wave:
            return True, "left"
        if right_wave:
            return True, "right"
        return False, ""

    def _update_wave_state(self, hand, wrist, shoulder_center, timestamp):
        state = self.wave_states[hand]

        if wrist is None:
            state["last_x"] = None
            state["last_direction"] = 0
            return False

        hand_is_high = wrist[1] < shoulder_center[1]

        cutoff = timestamp - WAVE_WINDOW_SECONDS
        while state["positions"] and state["positions"][0][0] < cutoff:
            state["positions"].popleft()
        while state["turns"] and state["turns"][0] < cutoff:
            state["turns"].popleft()

        if not hand_is_high:
            state["last_x"] = None
            state["last_direction"] = 0
            return False

        state["positions"].append((timestamp, wrist[0]))

        last_x = state["last_x"]
        if last_x is not None:
            dx = wrist[0] - last_x
            if abs(dx) >= WAVE_MIN_STEP_X:
                direction = 1 if dx > 0 else -1
                if state["last_direction"] and direction != state["last_direction"]:
                    state["turns"].append(timestamp)
                state["last_direction"] = direction

        state["last_x"] = wrist[0]

        xs = [point[1] for point in state["positions"]]
        x_range = max(xs) - min(xs) if xs else 0.0

        return (
            len(state["turns"]) >= WAVE_MIN_DIRECTION_CHANGES
            and x_range >= WAVE_MIN_X_RANGE
        )


class MultiPersonTracker:
    def __init__(self, fps):
        self.fps = fps
        self.detectors = {}
        self.seen_frames = {}
        self.next_person_id = 1

    @staticmethod
    def _last_center(detector):
        if detector.last_detection is None:
            return None

        snapshot = detector.last_detection.get("pose")
        if snapshot is None:
            return None

        return snapshot.body_center

    def update(self, pose_landmarks, pose_world_landmarks, timestamp):
        candidates = []

        for index, landmarks in enumerate(pose_landmarks):
            world_landmarks = (
                pose_world_landmarks[index]
                if pose_world_landmarks and index < len(pose_world_landmarks)
                else None
            )
            snapshot = build_pose_snapshot(landmarks, timestamp, world_landmarks)
            if snapshot is None:
                continue
            if not self._is_valid_person_snapshot(snapshot):
                continue
            candidates.append(
                {
                    "index": index,
                    "landmarks": landmarks,
                    "world_landmarks": world_landmarks,
                    "center": snapshot.body_center,
                }
            )

        assignments = {}
        unused_person_ids = set(self.detectors.keys())

        for candidate in sorted(candidates, key=lambda item: item["center"][0]):
            best_person_id = None
            best_distance = PERSON_MATCH_DISTANCE

            for person_id in list(unused_person_ids):
                center_point = self._last_center(self.detectors[person_id])
                if center_point is None:
                    continue

                center_distance = distance(candidate["center"], center_point)
                if center_distance is not None and center_distance < best_distance:
                    best_distance = center_distance
                    best_person_id = person_id

            if best_person_id is None:
                best_person_id = self.next_person_id
                self.next_person_id += 1
                self.detectors[best_person_id] = ActionDetector(self.fps)
                self.seen_frames[best_person_id] = 0
            else:
                unused_person_ids.discard(best_person_id)

            assignments[best_person_id] = candidate

        detections = []

        for person_id, candidate in assignments.items():
            detector = self.detectors[person_id]
            detection = detector.update(
                candidate["landmarks"],
                timestamp,
                candidate["world_landmarks"],
            )
            self.seen_frames[person_id] = self.seen_frames.get(person_id, 0) + 1

            confirmed = self.seen_frames[person_id] >= POSE_CONFIRM_FRAMES
            has_alert = detection["fall"] or detection["wave"] or detection["unstable"] or detection["running"]

            if confirmed or has_alert:
                detections.append((person_id, detection, candidate["landmarks"]))

        for person_id in list(unused_person_ids):
            detector = self.detectors[person_id]
            detection = detector.update_no_pose(timestamp)

            if (
                detector.last_pose_timestamp is not None
                and timestamp - detector.last_pose_timestamp > PERSON_LOST_SECONDS
                and not detection["fall"]
            ):
                del self.detectors[person_id]
                self.seen_frames.pop(person_id, None)
                continue

            if detection["fall"]:
                detections.append((person_id, detection, None))

        return sorted(detections, key=lambda item: item[0])

    def reset(self):
        self.detectors.clear()
        self.seen_frames.clear()
        self.next_person_id = 1

    @staticmethod
    def _is_valid_person_snapshot(snapshot):
        return (
            snapshot.body_height >= 0.08
            and snapshot.body_width >= 0.03
            and 0.0 <= snapshot.body_center[0] <= 1.0
            and 0.0 <= snapshot.body_center[1] <= 1.0
        )


def draw_panel(frame, detection, person_id=1, panel_index=0, show_debug=False):
    panel_x = 15
    panel_y = 15 + panel_index * 150
    text_x = panel_x + 15
    snapshot = detection.get("pose")
    fall = detection["fall"]
    wave = detection["wave"]
    unstable = detection["unstable"]
    running = detection["running"]
    tracking_lost = detection.get("tracking_lost", False)

    active_alerts = []
    if fall:
        active_alerts.append(("\u5075\u6e2c\u5230\u8dcc\u5012", (0, 0, 255)))
    if wave:
        active_alerts.append(("\u63ee\u624b\u6c42\u6551", (0, 140, 255)))
    if unstable:
        active_alerts.append(("\u6b65\u4f10\u4e0d\u7a69", (0, 220, 255)))
    if running:
        active_alerts.append(("\u8dd1\u6b65", (255, 180, 0)))
    if tracking_lost and not active_alerts:
        active_alerts.append(("\u9aa8\u67b6\u66ab\u6642\u907a\u5931", (180, 180, 180)))

    if not active_alerts and not show_debug:
        return False

    if not active_alerts:
        active_alerts.append(("\u6b63\u5e38", (0, 200, 0)))

    panel_height = 56 + len(active_alerts) * 28
    if show_debug:
        panel_height += 210
    elif fall:
        panel_height += 76

    cv2.rectangle(frame, (panel_x, panel_y), (panel_x + 300, panel_y + panel_height), (20, 20, 20), -1)
    cv2.rectangle(frame, (panel_x, panel_y), (panel_x + 300, panel_y + panel_height), active_alerts[0][1], 2)

    draw_chinese_text(
        frame,
        f"\u7b2c {person_id} \u4eba",
        (text_x, panel_y + 8),
        font_size=19,
        color=(255, 255, 255),
    )

    y = panel_y + 56
    for text, color in active_alerts:
        draw_chinese_text(frame, text, (text_x, y - 22), font_size=22, color=color)
        y += 28

    if snapshot is None:
        draw_chinese_text(
            frame,
            "\u672a\u5075\u6e2c\u5230\u4e3b\u8981\u9aa8\u67b6",
            (text_x, y - 8),
            font_size=20,
            color=(220, 220, 220),
        )
        draw_chinese_text(
            frame,
            "\u9700\u80a9\u8180\u8207\u81c0\u90e8\u6838\u5fc3\u9ede",
            (text_x, y + 18),
            font_size=16,
            color=(180, 180, 180),
        )
        return True

    if tracking_lost:
        draw_chinese_text(
            frame,
            "\u77ed\u66ab\u6cbf\u7528\u4e0a\u4e00\u500b\u59ff\u614b",
            (text_x, y - 8),
            font_size=18,
            color=(190, 190, 190),
        )

    running_info = detection.get("running_info", {})
    unstable_info = detection.get("unstable_info", {})
    fall_info = detection.get("fall_info", {})

    if show_debug:
        metric_lines = [
            f"2D\u8ec0\u5e79\uff1a{snapshot.torso_angle:5.1f}",
            f"3D\u8ec0\u5e79\uff1a{snapshot.torso_angle_3d if snapshot.torso_angle_3d is not None else 0.0:5.1f}",
            f"\u5bec\u9ad8\u6bd4\uff1a{snapshot.aspect_ratio:5.2f}",
            f"\u8dcc\u5012\u7d2f\u7a4d\uff1a{fall_info.get('counter', 0):5.0f}",
            f"\u975c\u614b\u5206\u6578\uff1a{fall_info.get('static_score', 0):5.0f}",
            f"\u975c\u614b\u7d2f\u7a4d\uff1a{fall_info.get('static_counter', 0):5.0f}",
            f"\u5782\u76f4\u5206\u6578\uff1a{fall_info.get('vertical_score', 0):5.0f}",
            f"\u5782\u76f4\u7d2f\u7a4d\uff1a{fall_info.get('vertical_counter', 0):5.0f}",
            f"\u4e2d\u5fc3\u4e0b\u964d\uff1a{fall_info.get('center_fall_speed', 0.0):5.2f}/s",
            f"\u81c0\u90e8\u4e0b\u964d\uff1a{fall_info.get('hip_fall_speed', 0.0):5.2f}/s",
        ]
    elif fall:
        metric_lines = [
            f"\u8dcc\u5012\u7d2f\u7a4d\uff1a{fall_info.get('counter', 0):5.0f}",
            f"\u975c\u614b\u5206\u6578\uff1a{fall_info.get('static_score', 0):5.0f}",
            f"\u5782\u76f4\u5206\u6578\uff1a{fall_info.get('vertical_score', 0):5.0f}",
            f"\u8dcc\u5012\u7dda\u7d22\uff1a{fall_info.get('signal_count', 0):5.0f}",
        ]
    else:
        metric_lines = []

    for line in metric_lines:
        draw_chinese_text(
            frame,
            line,
            (text_x, y - 18),
            font_size=16,
            color=(230, 230, 230),
        )
        y += 20

    return True

def choose_default_source():
    if os.path.exists(DEFAULT_VIDEO_SOURCE):
        return DEFAULT_VIDEO_SOURCE
    return 0


def main():
    global POSE_MIN_QUALITY
    global POSE_DEDUP_IOU_THRESHOLD
    global POSE_DEDUP_CENTER_DISTANCE
    global POSE_CONFIRM_FRAMES

    parser = argparse.ArgumentParser(
        description="MediaPipe \u591a\u52d5\u4f5c\u5075\u6e2c\u7cfb\u7d71"
    )
    parser.add_argument(
        "--source",
        default=choose_default_source(),
        help="\u5f71\u7247\u8def\u5f91\u6216\u651d\u5f71\u6a5f\u7de8\u865f\uff0c\u4f8b\u5982\uff1a--source 0",
    )
    parser.add_argument(
        "--no-loop",
        action="store_true",
        help="\u5f71\u7247\u64ad\u653e\u5b8c\u4e0d\u81ea\u52d5\u91cd\u64ad",
    )
    parser.add_argument(
        "--max-people",
        type=int,
        default=DEFAULT_MAX_PEOPLE,
        help="\u6700\u591a\u540c\u6642\u5075\u6e2c\u7684\u4eba\u6578",
    )
    parser.add_argument(
        "--pose-model",
        default=DEFAULT_POSE_MODEL,
        help="PoseLandmarker .task \u6a21\u578b\u6a94\u8def\u5f91",
    )
    parser.add_argument(
        "--show-debug",
        action="store_true",
        help="\u986f\u793a\u6bcf\u500b\u4eba\u7684\u8a73\u7d30\u6578\u503c\u9762\u677f",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=MIN_DETECTION_CONFIDENCE,
        help="\u59ff\u614b\u5075\u6e2c\u4fe1\u5fc3\u9580\u6abb\uff0c\u504f\u591a\u8aa4\u6293\u53ef\u63d0\u9ad8\uff0c\u6f0f\u6293\u53ef\u964d\u4f4e",
    )
    parser.add_argument(
        "--min-pose-quality",
        type=float,
        default=POSE_MIN_QUALITY,
        help="\u9aa8\u67b6\u6700\u4f4e\u54c1\u8cea\u9580\u6abb\uff0c\u8d8a\u9ad8\u8d8a\u4e0d\u5bb9\u6613\u8aa4\u6293",
    )
    parser.add_argument(
        "--dedup-iou",
        type=float,
        default=POSE_DEDUP_IOU_THRESHOLD,
        help="\u9aa8\u67b6\u5916\u6846\u91cd\u758a\u53bb\u91cd\u9580\u6abb",
    )
    parser.add_argument(
        "--dedup-center",
        type=float,
        default=POSE_DEDUP_CENTER_DISTANCE,
        help="\u9aa8\u67b6\u4e2d\u5fc3\u8ddd\u96e2\u53bb\u91cd\u9580\u6abb",
    )
    parser.add_argument(
        "--confirm-frames",
        type=int,
        default=POSE_CONFIRM_FRAMES,
        help="\u9023\u7e8c\u5e7e\u5e40\u90fd\u5075\u6e2c\u5230\u624d\u8a08\u5165\u4eba\u6578",
    )
    parser.add_argument(
        "--log-path",
        default=DEFAULT_LOG_PATH,
        help="\u72c0\u614b\u7d00\u9304 CSV \u6a94\u6848\u8def\u5f91",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="\u4e0d\u8f38\u51fa\u72c0\u614b\u7d00\u9304",
    )
    parser.add_argument(
        "--log-every",
        type=int,
        default=5,
        help="\u6bcf\u5e7e\u5e40\u7d00\u9304\u4e00\u6b21\uff1b\u6709\u7570\u5e38\u6642\u6703\u6bcf\u5e40\u7d00\u9304",
    )
    args = parser.parse_args()

    POSE_MIN_QUALITY = max(0.0, args.min_pose_quality)
    POSE_DEDUP_IOU_THRESHOLD = max(0.0, args.dedup_iou)
    POSE_DEDUP_CENTER_DISTANCE = max(0.0, args.dedup_center)
    POSE_CONFIRM_FRAMES = max(1, args.confirm_frames)

    video_source = parse_video_source(args.source)
    loop_video = LOOP_VIDEO and not args.no_loop

    if not os.path.exists(args.pose_model):
        print("\u627e\u4e0d\u5230\u591a\u4eba\u59ff\u614b\u6a21\u578b\uff1a", args.pose_model)
        print("\u8acb\u653e\u5165 pose_landmarker_full.task \u5230 model \u8cc7\u6599\u593e")
        print("\u9810\u8a2d\u8def\u5f91\uff1a", DEFAULT_POSE_MODEL)
        return

    cap = open_video_source(video_source)
    if not cap.isOpened():
        print("\u7121\u6cd5\u958b\u555f\u5f71\u50cf\u4f86\u6e90\uff1a", video_source)
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps is None or fps <= 0 or isinstance(video_source, int):
        fps = 30.0

    wait_time = max(1, int(1000 / fps))
    tracker = MultiPersonTracker(fps=fps)
    log_file, log_writer = open_status_logger(None if args.no_log else args.log_path)
    frame_index = 0
    start_time = time.monotonic()

    print("MediaPipe \u591a\u52d5\u4f5c\u5075\u6e2c\u7cfb\u7d71\u5df2\u555f\u52d5")
    print("\u5f71\u50cf\u4f86\u6e90\uff1a", video_source)
    print("\u6700\u591a\u5075\u6e2c\u4eba\u6578\uff1a", args.max_people)
    print("\u5075\u6e2c\u4fe1\u5fc3\u9580\u6abb\uff1a", args.min_confidence)
    if log_writer is not None:
        print("\u72c0\u614b\u7d00\u9304\uff1a", args.log_path)
    print("\u6309 q \u96e2\u958b\uff0c\u6309 r \u91cd\u64ad\u5f71\u7247")

    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=args.pose_model),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=max(1, args.max_people),
        min_pose_detection_confidence=args.min_confidence,
        min_pose_presence_confidence=args.min_confidence,
        min_tracking_confidence=args.min_confidence,
        output_segmentation_masks=False,
    )

    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        while True:
            ret, frame = cap.read()

            if not ret:
                if loop_video and not isinstance(video_source, int):
                    reset_video(cap)
                    tracker.reset()
                    continue
                print("\u7121\u6cd5\u8b80\u53d6\u756b\u9762")
                break

            if isinstance(video_source, int):
                frame = cv2.flip(frame, 1)

            image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)
            timestamp = time.monotonic()
            timestamp_ms = int(timestamp * 1000)
            results = landmarker.detect_for_video(mp_image, timestamp_ms)
            filtered_pose_landmarks, filtered_world_landmarks, filtered_candidates = deduplicate_pose_results(
                results.pose_landmarks,
                results.pose_world_landmarks,
            )

            detections = tracker.update(
                filtered_pose_landmarks,
                filtered_world_landmarks,
                timestamp,
            )

            current_people_count = sum(1 for _, _, landmarks in detections if landmarks is not None)
            elapsed_seconds = timestamp - start_time
            should_log = (
                args.log_every <= 1
                or frame_index % args.log_every == 0
                or has_any_alert(detections)
            )
            if should_log:
                write_status_log(
                    log_writer,
                    elapsed_seconds,
                    frame_index,
                    current_people_count,
                    detections,
                )
            frame_index += 1

            draw_chinese_text(
                frame,
                f"\u76ee\u524d\u4eba\u6578\uff1a{current_people_count}",
                (30, 16),
                font_size=22,
                color=(255, 255, 255),
            )
            if args.show_debug:
                draw_chinese_text(
                    frame,
                    f"\u539f\u59cb\uff1a{len(results.pose_landmarks)} / \u53bb\u91cd\uff1a{len(filtered_pose_landmarks)} / \u78ba\u8a8d\uff1a{current_people_count}",
                    (30, 44),
                    font_size=16,
                    color=(210, 210, 210),
                )

            if len(filtered_pose_landmarks) == 0:
                draw_chinese_text(
                    frame,
                    "\u672a\u5075\u6e2c\u5230\u4efb\u4f55\u4eba\u7269",
                    (30, 66 if args.show_debug else 48),
                    font_size=26,
                    color=(0, 0, 255),
                )
            elif current_people_count == 0:
                draw_chinese_text(
                    frame,
                    "\u5075\u6e2c\u5230\u4eba\u7269\uff0c\u6b63\u5728\u78ba\u8a8d",
                    (30, 66 if args.show_debug else 48),
                    font_size=22,
                    color=(0, 220, 255),
                )

            alert_panel_index = 0

            for person_id, detection, landmarks in detections[: args.max_people]:
                if landmarks is not None:
                    color_palette = [
                        (0, 255, 0),
                        (255, 180, 0),
                        (0, 180, 255),
                        (255, 0, 255),
                        (255, 255, 0),
                    ]
                    color = color_palette[(person_id - 1) % len(color_palette)]
                    draw_pose_landmarks(frame, landmarks, color=color)

                    snapshot = detection.get("pose")
                    if snapshot is not None:
                        label_x = int(snapshot.body_center[0] * frame.shape[1])
                        label_y = int(snapshot.body_center[1] * frame.shape[0])
                        draw_chinese_text(
                            frame,
                            f"\u7b2c {person_id} \u4eba",
                            (label_x, max(0, label_y - 35)),
                            font_size=20,
                            color=color,
                        )

                panel_drawn = draw_panel(
                    frame,
                    detection,
                    person_id=person_id,
                    panel_index=alert_panel_index,
                    show_debug=args.show_debug,
                )
                if panel_drawn:
                    alert_panel_index += 1

            cv2.imshow("MediaPipe \u591a\u52d5\u4f5c\u5075\u6e2c\u7cfb\u7d71", frame)

            key = cv2.waitKey(wait_time) & 0xFF
            if key == ord("q"):
                break
            if key == ord("r") and not isinstance(video_source, int):
                reset_video(cap)
                tracker.reset()
                frame_index = 0
                start_time = time.monotonic()

    cap.release()
    if log_file is not None:
        log_file.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
