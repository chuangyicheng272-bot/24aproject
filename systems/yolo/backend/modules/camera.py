from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - handled at runtime for setup guidance
    cv2 = None
    np = None


@dataclass
class VideoInputConfig:
    source: str
    width: int = 960
    height: int = 540
    preserve_aspect: bool = True
    target_fps: float = 30.0
    low_latency: bool = True
    buffer_size: int = 1
    stale_frame_grabs: int = 0
    brightness: float = 0.0
    contrast: float = 1.0
    auto_contrast: bool = False
    clahe_clip_limit: float = 1.8
    clahe_grid_size: int = 8
    sharpen: bool = False
    sharpen_amount: float = 0.3
    denoise: bool = False
    denoise_strength: float = 3.0
    loop_file: bool = True


@dataclass
class FramePacket:
    frame: object
    frame_index: int
    timestamp: float
    source: str
    width: int
    height: int


def source_kind(source: str) -> str:
    normalized = str(source).strip().lower()
    if normalized.startswith("rtsp://"):
        return "rtsp"
    if normalized.startswith(("http://", "https://")):
        if normalized.endswith((".jpg", ".jpeg", ".png")):
            return "snapshot"
        return "http"
    if normalized.isdigit():
        return "webcam"
    return "file"


def resolve_source(source: str):
    normalized = str(source).strip()
    if normalized.isdigit():
        return int(normalized)
    return normalized


def phone_camera_candidates(source: str) -> list[str]:
    normalized = str(source).strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        return [normalized]

    path = parsed.path.rstrip("/")
    if path and path != "":
        return [normalized]

    host = parsed.hostname
    if not host:
        return [normalized]

    ports = [parsed.port] if parsed.port else [8080, 4747, 80]
    suffixes = ["/video", "/mjpegfeed", "/shot.jpg"]
    candidates = []
    for port in ports:
        netloc = host if port in (None, 80) else f"{host}:{port}"
        for suffix in suffixes:
            candidates.append(f"{parsed.scheme}://{netloc}{suffix}")
    candidates.append(normalized)
    return list(dict.fromkeys(candidates))


def is_snapshot_url(source: str) -> bool:
    return source_kind(source) == "snapshot"


def is_realtime_source(source: str) -> bool:
    return source_kind(source) in {"webcam", "rtsp", "http", "snapshot"}


class FramePreprocessor:
    def __init__(self, config: VideoInputConfig):
        self.config = config

    def apply(self, frame):
        if cv2 is None:
            raise RuntimeError("OpenCV is not installed. Install backend requirements first.")

        if self.config.width > 0 and self.config.height > 0:
            if self.config.preserve_aspect:
                frame = resize_with_letterbox(frame, self.config.width, self.config.height)
            else:
                frame = cv2.resize(frame, (self.config.width, self.config.height))

        if self.config.contrast != 1.0 or self.config.brightness != 0.0:
            frame = cv2.convertScaleAbs(
                frame,
                alpha=float(self.config.contrast),
                beta=float(self.config.brightness),
            )

        if self.config.auto_contrast:
            frame = enhance_luminance(
                frame,
                clip_limit=self.config.clahe_clip_limit,
                grid_size=self.config.clahe_grid_size,
            )

        if self.config.denoise:
            strength = max(1.0, float(self.config.denoise_strength))
            frame = cv2.bilateralFilter(
                frame,
                d=5,
                sigmaColor=10.0 + strength * 5.0,
                sigmaSpace=10.0 + strength * 5.0,
            )

        if self.config.sharpen:
            amount = max(0.0, min(1.0, float(self.config.sharpen_amount)))
            blurred = cv2.GaussianBlur(frame, (0, 0), 1.0)
            frame = cv2.addWeighted(
                frame,
                1.0 + amount,
                blurred,
                -amount,
                0,
            )

        return np.ascontiguousarray(frame, dtype=np.uint8)


def enhance_luminance(frame, clip_limit: float = 1.8, grid_size: int = 8):
    """Improve local lighting while preserving colors used by PPE detection."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    luminance, channel_a, channel_b = cv2.split(lab)
    grid = max(2, int(grid_size))
    clahe = cv2.createCLAHE(
        clipLimit=max(1.0, float(clip_limit)),
        tileGridSize=(grid, grid),
    )
    enhanced = clahe.apply(luminance)
    merged = cv2.merge((enhanced, channel_a, channel_b))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def resize_with_letterbox(frame, target_width: int, target_height: int):
    source_height, source_width = frame.shape[:2]
    if source_width <= 0 or source_height <= 0:
        return cv2.resize(frame, (target_width, target_height))

    scale = min(target_width / source_width, target_height / source_height)
    resized_width = max(1, int(round(source_width * scale)))
    resized_height = max(1, int(round(source_height * scale)))
    resized = cv2.resize(frame, (resized_width, resized_height))

    pad_left = (target_width - resized_width) // 2
    pad_right = target_width - resized_width - pad_left
    pad_top = (target_height - resized_height) // 2
    pad_bottom = target_height - resized_height - pad_top

    return cv2.copyMakeBorder(
        resized,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )


class VideoInput:
    def __init__(self, config: VideoInputConfig):
        self.config = config
        self.preprocessor = FramePreprocessor(config)
        self.cap = None
        self.http_response = None
        self.http_buffer = bytearray()
        self.http_stream_url: str | None = None
        self.snapshot_url: str | None = None
        self.active_source = config.source
        self.frame_index = 0
        self.last_emit_time = 0.0

    @property
    def is_open(self) -> bool:
        return (
            self.snapshot_url is not None
            or self.http_response is not None
            or (self.cap is not None and self.cap.isOpened())
        )

    def open(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is not installed. Install backend requirements first.")

        kind = source_kind(self.config.source)
        if kind == "file":
            source_path = Path(self.config.source)
            if not source_path.exists():
                raise FileNotFoundError(f"Video file not found: {source_path}")

        self.close()
        if kind in {"http", "snapshot"}:
            self._open_http_source()
        else:
            self.active_source = self.config.source
            self.cap = cv2.VideoCapture(resolve_source(self.config.source))
            self._configure_capture(self.cap)
            if not self.cap.isOpened():
                raise RuntimeError(f"Unable to open video source: {self.config.source}")

    def _configure_capture(self, cap) -> None:
        kind = source_kind(self.config.source)
        if kind == "webcam":
            if self.config.width > 0:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.config.width))
            if self.config.height > 0:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.config.height))
            if self.config.target_fps > 0:
                cap.set(cv2.CAP_PROP_FPS, float(self.config.target_fps))

        if not self.config.low_latency:
            return
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, max(1, int(self.config.buffer_size)))
        except Exception:
            pass

    def _open_http_source(self) -> None:
        errors: list[str] = []
        for candidate in phone_camera_candidates(self.config.source):
            if is_snapshot_url(candidate):
                try:
                    frame = self._read_snapshot(candidate)
                except RuntimeError as exc:
                    errors.append(f"{candidate}: {exc}")
                    continue
                if frame is not None:
                    self.snapshot_url = candidate
                    self.active_source = candidate
                    return
            else:
                try:
                    self._open_http_mjpeg_stream(candidate)
                    frame = self._read_http_mjpeg_frame()
                except RuntimeError as exc:
                    self._close_http_stream()
                    errors.append(f"{candidate}: http stream failed ({exc})")
                else:
                    if frame is not None:
                        self.active_source = candidate
                        return
                    self._close_http_stream()
                    errors.append(f"{candidate}: http stream returned no frame")

        detail = "; ".join(errors[:4]) if errors else "no candidate URL worked"
        raise RuntimeError(f"Unable to open phone camera source: {self.config.source}. {detail}")

    def _open_http_mjpeg_stream(self, url: str) -> None:
        try:
            self.http_response = urlopen(url, timeout=5)
        except (OSError, URLError) as exc:
            raise RuntimeError(exc) from exc
        self.http_buffer = bytearray()
        self.http_stream_url = url

    def _close_http_stream(self) -> None:
        if self.http_response is not None:
            try:
                self.http_response.close()
            except Exception:
                pass
        self.http_response = None
        self.http_buffer = bytearray()
        self.http_stream_url = None

    def _read_http_mjpeg_frame(self):
        if np is None:
            raise RuntimeError("NumPy is not installed. Install backend requirements first.")
        if self.http_response is None:
            raise RuntimeError("HTTP stream is not open")

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            frame = self._pop_latest_mjpeg_frame()
            if frame is not None:
                return frame

            try:
                chunk = self.http_response.read(32768)
            except (OSError, TimeoutError) as exc:
                raise RuntimeError(exc) from exc
            if not chunk:
                raise RuntimeError("stream ended")
            self.http_buffer.extend(chunk)
            if len(self.http_buffer) > 4 * 1024 * 1024:
                del self.http_buffer[: len(self.http_buffer) - 1024 * 1024]

        raise RuntimeError("timed out waiting for JPEG frame")

    def _pop_latest_mjpeg_frame(self):
        latest_jpg = None
        latest_end = -1
        search_from = 0
        while True:
            start = self.http_buffer.find(b"\xff\xd8", search_from)
            if start < 0:
                break
            end = self.http_buffer.find(b"\xff\xd9", start + 2)
            if end < 0:
                break
            latest_jpg = bytes(self.http_buffer[start : end + 2])
            latest_end = end + 2
            search_from = latest_end

        if latest_jpg is None:
            first_start = self.http_buffer.find(b"\xff\xd8")
            if first_start > 0:
                del self.http_buffer[:first_start]
            return None

        del self.http_buffer[:latest_end]
        image = np.frombuffer(latest_jpg, dtype=np.uint8)
        return cv2.imdecode(image, cv2.IMREAD_COLOR)

    def _read_snapshot(self, url: str):
        if np is None:
            raise RuntimeError("NumPy is not installed. Install backend requirements first.")

        try:
            with urlopen(url, timeout=3) as response:
                data = response.read()
        except (OSError, TimeoutError, URLError) as exc:
            raise RuntimeError(f"snapshot request failed: {exc}") from exc

        image = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(image, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("snapshot endpoint did not return an image")
        return frame

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
        self.cap = None
        self._close_http_stream()
        self.snapshot_url = None
        self.active_source = self.config.source

    def reset(self) -> None:
        if self.cap is not None and source_kind(self.config.source) == "file":
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.frame_index = 0

    def read(self) -> FramePacket | None:
        now = time.monotonic()
        interval = 1.0 / max(float(self.config.target_fps), 1.0)
        if self.last_emit_time and now - self.last_emit_time < interval:
            return None

        if not self.is_open:
            self.open()

        if self.snapshot_url is not None:
            try:
                frame = self._read_snapshot(self.snapshot_url)
            except RuntimeError:
                self.close()
                return None
        elif self.http_response is not None:
            try:
                frame = self._read_http_mjpeg_frame()
            except RuntimeError:
                self.close()
                return None
        else:
            ret, frame = self._read_capture_frame()
            if not ret:
                if source_kind(self.config.source) == "file" and self.config.loop_file:
                    self.reset()
                    ret, frame = self._read_capture_frame()
                if not ret:
                    return None

        self.last_emit_time = now
        processed = self.preprocessor.apply(frame)
        height, width = processed.shape[:2]
        packet = FramePacket(
            frame=processed,
            frame_index=self.frame_index,
            timestamp=now,
            source=self.active_source,
            width=width,
            height=height,
        )
        self.frame_index += 1
        return packet

    def _read_capture_frame(self):
        if (
            self.config.low_latency
            and is_realtime_source(self.config.source)
            and self.config.stale_frame_grabs > 0
        ):
            for _ in range(max(0, int(self.config.stale_frame_grabs))):
                if not self.cap.grab():
                    break
            return self.cap.retrieve()
        return self.cap.read()

    def frames(self) -> Iterator[FramePacket]:
        while True:
            packet = self.read()
            if packet is None:
                time.sleep(0.001)
                continue
            yield packet


def encode_jpeg(frame, quality: int = 85) -> bytes:
    if cv2 is None:
        raise RuntimeError("OpenCV is not installed. Install backend requirements first.")
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("Unable to encode frame as JPEG.")
    return buffer.tobytes()
