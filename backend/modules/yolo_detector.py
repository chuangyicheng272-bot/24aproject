from __future__ import annotations

import os
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from ..env import load_env_file
except ImportError:  # Allows importing from scripts that run inside backend/.
    from env import load_env_file

from .tracker import Box, box_iou

load_env_file()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PERSON_MODEL = PROJECT_ROOT / "person_v2.pt"
DEFAULT_EQUIPMENT_MODEL = PROJECT_ROOT / "best_v3.pt"
ULTRALYTICS_CONFIG_DIR = PROJECT_ROOT / ".ultralytics"


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


DEFAULT_PERSON_MODEL = project_path(os.environ.get("PERSON_MODEL_PATH", DEFAULT_PERSON_MODEL))
DEFAULT_EQUIPMENT_MODEL = project_path(os.environ.get("EQUIPMENT_MODEL_PATH", DEFAULT_EQUIPMENT_MODEL))
def parse_max_people(value: str | None, default: int | None = 1) -> int | None:
    if value is None or value == "":
        return default
    parsed = int(value)
    return parsed if parsed > 0 else None


DEFAULT_MAX_PEOPLE = parse_max_people(os.environ.get("MAX_PEOPLE"), 1)
DEFAULT_YOLO_IMAGE_SIZE = max(320, int(os.environ.get("YOLO_IMAGE_SIZE", "960")))

PERSON_LABELS = {"person", "persona", "worker", "workers", "human", "pedestrian"}
HELMET_LABELS = {"helmet", "hardhat", "hard_hat", "safety helmet", "safe_helmet"}
VEST_LABELS = {"vest", "safety vest", "reflective vest", "safety_vest"}
NEGATIVE_HELMET_LABELS = {"no helmet", "no_helmet", "without helmet"}
NEGATIVE_VEST_LABELS = {"no vest", "no_vest", "without vest"}

EQUIPMENT_MIN_CONFIDENCE = {
    "helmet": 0.40,
    "no_helmet": 0.42,
    "vest": 0.26,
    "no_vest": 0.34,
    "mask": 0.35,
    "no_mask": 0.40,
    "gloves": 0.35,
    "no_gloves": 0.40,
    "goggles": 0.35,
    "no_goggles": 0.40,
}


@dataclass
class Detection:
    box: Box
    label: str
    confidence: float
    class_id: int
    kind: str
    source_model: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "box": [round(value, 2) for value in self.box],
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "class_id": self.class_id,
            "kind": self.kind,
            "source_model": self.source_model,
        }


class YOLOSafetyDetector:
    def __init__(
        self,
        person_model_path: str | Path = DEFAULT_PERSON_MODEL,
        equipment_model_path: str | Path = DEFAULT_EQUIPMENT_MODEL,
        person_confidence: float = 0.35,
        equipment_confidence: float = 0.25,
        max_people: int | None = DEFAULT_MAX_PEOPLE,
        inference_size: int = DEFAULT_YOLO_IMAGE_SIZE,
    ):
        self.person_model_path = Path(person_model_path)
        self.equipment_model_path = Path(equipment_model_path)
        self.person_confidence = person_confidence
        self.equipment_confidence = equipment_confidence
        self.max_people = max_people
        self.inference_size = max(320, int(inference_size))
        self.person_model = None
        self.equipment_model = None
        self.last_error: str | None = None
        self._yolo_class = None

    def status(self) -> dict[str, Any]:
        return {
            "available": self._dependencies_available(),
            "person_model": str(self.person_model_path),
            "person_model_exists": self.person_model_path.exists(),
            "equipment_model": str(self.equipment_model_path),
            "equipment_model_exists": self.equipment_model_path.exists(),
            "person_confidence": self.person_confidence,
            "equipment_confidence": self.equipment_confidence,
            "equipment_min_confidence": EQUIPMENT_MIN_CONFIDENCE,
            "max_people": self.max_people,
            "inference_size": self.inference_size,
            "loaded": self.person_model is not None or self.equipment_model is not None,
            "last_error": self.last_error,
        }

    def _dependencies_available(self) -> bool:
        try:
            self._get_yolo_class()
            return True
        except Exception:
            return False

    def _get_yolo_class(self):
        if self._yolo_class is not None:
            return self._yolo_class

        os.environ.setdefault("YOLO_CONFIG_DIR", str(ULTRALYTICS_CONFIG_DIR))
        ULTRALYTICS_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        from ultralytics import YOLO

        self._yolo_class = YOLO
        return YOLO

    def _load_model(self, path: Path):
        yolo_class = self._get_yolo_class()
        if not path.exists():
            raise FileNotFoundError(f"YOLO model not found: {path}")
        return yolo_class(str(path))

    def load(self, include_equipment: bool = True) -> None:
        try:
            if self.person_model is None:
                self.person_model = self._load_model(self.person_model_path)
            if include_equipment and self.equipment_model is None:
                self.equipment_model = self._load_model(self.equipment_model_path)
            self.last_error = None
        except Exception as exc:  # pragma: no cover - depends on local model/runtime
            self.last_error = str(exc)
            raise

    def detect(self, frame) -> dict[str, Any]:
        self.load(include_equipment=True)
        people = self.detect_frame_with_model(
            frame,
            self.person_model,
            confidence_threshold=self.person_confidence,
            kind="person",
            source_model="person",
            person_model=True,
        )
        people = select_person_detections(people, frame.shape, self.max_people)
        equipment = self.detect_frame_with_model(
            frame,
            self.equipment_model,
            confidence_threshold=self.equipment_confidence,
            kind="equipment",
            source_model="equipment",
            person_model=False,
        )
        equipment = filter_equipment_for_people(equipment, people)
        assignments = assign_equipment_to_people(people, equipment)
        return {
            "people": [item.to_dict() for item in people],
            "equipment": [item.to_dict() for item in equipment],
            "assignments": assignments,
        }

    def detect_frame_with_model(
        self,
        frame,
        model,
        confidence_threshold: float,
        kind: str,
        source_model: str,
        person_model: bool,
    ) -> list[Detection]:
        ensure_torchvision_nms()
        results = model.predict(
            frame,
            conf=confidence_threshold,
            imgsz=self.inference_size,
            verbose=False,
        )
        return self._parse_results(results, model, confidence_threshold, kind, source_model, person_model)

    def _parse_results(
        self,
        results,
        model,
        confidence_threshold: float,
        kind: str,
        source_model: str,
        person_model: bool,
    ) -> list[Detection]:
        names = getattr(model, "names", {}) or {}
        detections: list[Detection] = []

        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                confidence = float(box.conf[0])
                if confidence < confidence_threshold:
                    continue
                class_id = int(box.cls[0])
                raw_label = str(names.get(class_id, class_id))
                label = normalize_label(raw_label)
                if person_model and names and not is_person_label(label, names):
                    continue
                normalized_kind = normalize_equipment_kind(label) if kind == "equipment" else "person"
                if kind == "equipment" and normalized_kind == "person":
                    continue
                xyxy = box.xyxy[0].tolist()
                detection_box = tuple(float(value) for value in xyxy)
                if person_model and not valid_person_box(detection_box, result.orig_shape):
                    continue
                if kind == "equipment" and not valid_equipment_detection(
                    normalized_kind,
                    confidence,
                    detection_box,
                    result.orig_shape,
                    confidence_threshold,
                ):
                    continue
                detections.append(
                    Detection(
                        box=detection_box,
                        label=label,
                        confidence=confidence,
                        class_id=class_id,
                        kind=normalized_kind,
                        source_model=source_model,
                    )
                )

        return detections

    def detect_people(self, frame) -> list[dict[str, Any]]:
        self.load(include_equipment=False)
        people = self.detect_frame_with_model(
            frame,
            self.person_model,
            self.person_confidence,
            "person",
            "person",
            True,
        )
        people = select_person_detections(people, frame.shape, self.max_people)
        return [item.to_dict() for item in people]

    def detect_safety(self, frame, include_equipment: bool = True) -> dict[str, Any]:
        self.load(include_equipment=include_equipment)
        people = self.detect_frame_with_model(
            frame,
            self.person_model,
            self.person_confidence,
            "person",
            "person",
            True,
        )
        people = select_person_detections(people, frame.shape, self.max_people)
        if not include_equipment:
            return {
                "people": [item.to_dict() for item in people],
                "equipment": [],
                "assignments": {},
                "ppe_updated": False,
            }

        equipment = self.detect_frame_with_model(
            frame,
            self.equipment_model,
            self.equipment_confidence,
            "equipment",
            "equipment",
            False,
        )
        equipment = filter_equipment_for_people(equipment, people)
        return {
            "people": [item.to_dict() for item in people],
            "equipment": [item.to_dict() for item in equipment],
            "assignments": assign_equipment_to_people(people, equipment),
            "ppe_updated": True,
        }


def normalize_label(label: str) -> str:
    return " ".join(label.strip().lower().replace("-", " ").replace("_", " ").split())


def is_person_label(label: str, names: dict[int, Any]) -> bool:
    if label in PERSON_LABELS:
        return True
    if len(names) == 1:
        return True
    return False


def normalize_equipment_kind(label: str) -> str:
    normalized = normalize_label(label)
    if normalized in HELMET_LABELS:
        return "helmet"
    if normalized in VEST_LABELS:
        return "vest"
    if normalized in NEGATIVE_HELMET_LABELS:
        return "no_helmet"
    if normalized in NEGATIVE_VEST_LABELS:
        return "no_vest"
    if "helmet" in normalized or "hardhat" in normalized:
        return "helmet" if "no" not in normalized and "without" not in normalized else "no_helmet"
    if "vest" in normalized:
        return "vest" if "no" not in normalized and "without" not in normalized else "no_vest"
    if "mask" in normalized:
        return "mask" if "no" not in normalized and "without" not in normalized else "no_mask"
    if "glove" in normalized:
        return "gloves" if "no" not in normalized and "without" not in normalized else "no_gloves"
    if "goggle" in normalized:
        return "goggles" if "no" not in normalized and "without" not in normalized else "no_goggles"
    return normalized.replace(" ", "_")


def valid_person_box(box: Box, image_shape) -> bool:
    height, width = image_shape[:2]
    x1, y1, x2, y2 = box
    box_width = max(0.0, x2 - x1)
    box_height = max(0.0, y2 - y1)
    if box_width < 12 or box_height < 24:
        return False
    area_ratio = (box_width * box_height) / max(float(width * height), 1.0)
    aspect_ratio = box_height / max(box_width, 1.0)
    return area_ratio >= 0.0015 and 0.7 <= aspect_ratio <= 5.5


def valid_equipment_detection(
    kind: str,
    confidence: float,
    box: Box,
    image_shape,
    base_confidence: float,
) -> bool:
    min_confidence = max(base_confidence, EQUIPMENT_MIN_CONFIDENCE.get(kind, 0.35))
    if confidence < min_confidence:
        return False

    height, width = image_shape[:2]
    x1, y1, x2, y2 = box
    box_width = max(0.0, x2 - x1)
    box_height = max(0.0, y2 - y1)
    area_ratio = (box_width * box_height) / max(float(width * height), 1.0)
    if area_ratio < 0.00008:
        return False

    aspect_ratio = box_width / max(box_height, 1.0)
    if kind in {"helmet", "no_helmet", "mask", "no_mask", "goggles", "no_goggles"}:
        return 0.35 <= aspect_ratio <= 2.8
    if kind in {"vest", "no_vest"}:
        return 0.35 <= aspect_ratio <= 2.4
    return True


def select_person_detections(
    people: list[Detection],
    image_shape,
    max_people: int | None,
    duplicate_iou: float = 0.55,
) -> list[Detection]:
    if not people:
        return []

    height, width = image_shape[:2]

    def rank(detection: Detection) -> float:
        x1, y1, x2, y2 = detection.box
        area_ratio = max(0.0, x2 - x1) * max(0.0, y2 - y1) / max(float(width * height), 1.0)
        return detection.confidence + min(area_ratio * 1.5, 0.18)

    selected: list[Detection] = []
    for detection in sorted(people, key=rank, reverse=True):
        if any(box_iou(detection.box, kept.box) >= duplicate_iou for kept in selected):
            continue
        selected.append(detection)
        if max_people is not None and len(selected) >= max_people:
            break
    return selected


def ensure_torchvision_nms() -> None:
    try:
        import torchvision  # noqa: F401
        return
    except Exception:
        pass

    import torch

    def nms(boxes, scores, iou_threshold):
        if boxes.numel() == 0:
            return torch.empty((0,), dtype=torch.long, device=boxes.device)

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        areas = (x2 - x1).clamp(min=0) * (y2 - y1).clamp(min=0)
        order = scores.argsort(descending=True)
        keep = []

        while order.numel() > 0:
            current = order[0]
            keep.append(current)
            if order.numel() == 1:
                break

            rest = order[1:]
            xx1 = torch.maximum(x1[current], x1[rest])
            yy1 = torch.maximum(y1[current], y1[rest])
            xx2 = torch.minimum(x2[current], x2[rest])
            yy2 = torch.minimum(y2[current], y2[rest])
            inter = (xx2 - xx1).clamp(min=0) * (yy2 - yy1).clamp(min=0)
            union = areas[current] + areas[rest] - inter
            iou = torch.where(union > 0, inter / union, torch.zeros_like(inter))
            order = rest[iou <= iou_threshold]

        return torch.stack(keep).to(dtype=torch.long)

    torchvision_module = types.ModuleType("torchvision")
    ops_module = types.ModuleType("torchvision.ops")
    ops_module.nms = nms
    torchvision_module.ops = ops_module
    torchvision_module.__version__ = "0.0-local-nms"
    sys.modules["torchvision"] = torchvision_module
    sys.modules["torchvision.ops"] = ops_module


def box_center(box: Box) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def center_inside(inner_box: Box, outer_box: Box) -> bool:
    x, y = box_center(inner_box)
    x1, y1, x2, y2 = outer_box
    return x1 <= x <= x2 and y1 <= y <= y2


def equipment_family(kind: str) -> str:
    if kind in {"helmet", "no_helmet"}:
        return "helmet"
    if kind in {"vest", "no_vest"}:
        return "vest"
    if kind in {"mask", "no_mask"}:
        return "mask"
    if kind in {"gloves", "no_gloves"}:
        return "gloves"
    if kind in {"goggles", "no_goggles"}:
        return "goggles"
    return kind


def relative_center_y(item_box: Box, person_box: Box) -> float:
    _, center_y = box_center(item_box)
    _, y1, _, y2 = person_box
    return (center_y - y1) / max(y2 - y1, 1.0)


def relative_center_x(item_box: Box, person_box: Box) -> float:
    center_x, _ = box_center(item_box)
    x1, _, x2, _ = person_box
    return (center_x - x1) / max(x2 - x1, 1.0)


def plausible_equipment_position(item: Detection, person: Detection) -> bool:
    rel_x = relative_center_x(item.box, person.box)
    rel_y = relative_center_y(item.box, person.box)
    if rel_x < -0.12 or rel_x > 1.12:
        return False

    family = equipment_family(item.kind)
    if family in {"helmet", "mask", "goggles"}:
        return -0.08 <= rel_y <= 0.34
    if family == "vest":
        return 0.16 <= rel_y <= 0.72
    if family == "gloves":
        return 0.22 <= rel_y <= 0.88
    return 0.0 <= rel_y <= 1.0


def equipment_match_score(item: Detection, person: Detection) -> float:
    if not plausible_equipment_position(item, person):
        return 0.0

    score = box_iou(item.box, person.box)
    if center_inside(item.box, person.box):
        score += 0.7

    rel_y = relative_center_y(item.box, person.box)
    family = equipment_family(item.kind)
    if family in {"helmet", "mask", "goggles"}:
        score += max(0.0, 0.35 - abs(rel_y - 0.12))
    elif family == "vest":
        score += max(0.0, 0.35 - abs(rel_y - 0.42))
    score += item.confidence
    return score


def filter_equipment_for_people(equipment: list[Detection], people: list[Detection]) -> list[Detection]:
    if not equipment or not people:
        return []
    return [
        item
        for item in equipment
        if any(equipment_match_score(item, person) > 0.0 for person in people)
    ]


def assign_equipment_to_people(
    people: list[Detection],
    equipment: list[Detection],
    score_threshold: float = 0.55,
) -> dict[int, list[dict[str, Any]]]:
    assignments: dict[int, list[dict[str, Any]]] = {index: [] for index in range(len(people))}
    best_by_person_family: dict[tuple[int, str], tuple[float, Detection]] = {}

    for item in equipment:
        best_index = None
        best_score = 0.0
        for index, person in enumerate(people):
            score = equipment_match_score(item, person)
            if score > best_score:
                best_score = score
                best_index = index

        if best_index is not None and best_score >= score_threshold:
            key = (best_index, equipment_family(item.kind))
            current = best_by_person_family.get(key)
            if current is None or best_score > current[0]:
                best_by_person_family[key] = (best_score, item)

    for (person_index, _), (_, item) in best_by_person_family.items():
        assignments[person_index].append(item.to_dict())

    return assignments
