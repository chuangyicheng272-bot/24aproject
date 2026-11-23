"""Flask routes and per-user runtime management for the Rail subsystem."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from flask import Blueprint, jsonify, render_template, request

from .engine import RailEngine


MAX_FRAME_BYTES = 3 * 1024 * 1024
ALLOWED_DIRECTIONS = {"x", "y", "xy"}


class RailRuntime:
    def __init__(self, engine: RailEngine, owner_id: int):
        self.engine = engine
        self.owner_id = owner_id
        self.lock = threading.RLock()
        self.capture = None
        self.worker = None
        self.stop_event = threading.Event()
        self.source = "browser"
        self.last_error = None


class RailRuntimeManager:
    """In-process runtime registry. One active Rail session per logged-in user."""
    def __init__(self):
        self._lock = threading.RLock()
        self._items = {}

    def get(self, owner_id):
        with self._lock:
            return self._items.get(owner_id)

    def set(self, owner_id, runtime):
        self.stop(owner_id)
        with self._lock:
            self._items[owner_id] = runtime

    def stop(self, owner_id):
        with self._lock:
            runtime = self._items.pop(owner_id, None)
        if runtime is None:
            return
        runtime.stop_event.set()
        if runtime.capture is not None:
            runtime.capture.release()
            runtime.capture = None
        if runtime.worker and runtime.worker.is_alive():
            runtime.worker.join(timeout=2.0)


manager = RailRuntimeManager()


def _decode_frame(file_storage):
    raw = file_storage.read(MAX_FRAME_BYTES + 1)
    if not raw or len(raw) > MAX_FRAME_BYTES:
        raise ValueError("影格資料為空或超過 3 MB")
    encoded = np.frombuffer(raw, dtype=np.uint8)
    frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        raise ValueError("無法解碼影格，請確認影像格式")
    height, width = frame.shape[:2]
    if width > 1920 or height > 1080:
        raise ValueError("影格尺寸不可超過 1920 × 1080")
    return frame


def _parse_roi(value, frame):
    try:
        roi = tuple(int(v) for v in value)
    except (TypeError, ValueError):
        raise ValueError("ROI 必須是 [x, y, width, height]")
    if len(roi) != 4:
        raise ValueError("ROI 必須包含 x、y、寬度及高度")
    x, y, w, h = roi
    fh, fw = frame.shape[:2]
    if w < 20 or h < 20 or x < 0 or y < 0 or x + w > fw or y + h > fh:
        raise ValueError("ROI 至少需 20 × 20，且必須位於影格範圍內")
    return roi


def _user_id(current_user):
    user = current_user()
    return int(user["id"])


def register_rail_routes(app, login_required, current_user):
    bp = Blueprint("rail", __name__)

    @bp.get("/rail")
    @login_required
    def rail_page():
        return render_template("rail.html")

    @bp.get("/api/rail/status")
    @login_required
    def rail_status():
        runtime = manager.get(_user_id(current_user))
        if runtime is None:
            return jsonify(ok=True, active=False, initialized=False, source=None)
        with runtime.lock:
            data = runtime.engine.get_status()
            data.update(ok=True, active=True, source=runtime.source,
                        last_error=runtime.last_error)
        return jsonify(data)

    @bp.post("/api/rail/initialize")
    @login_required
    def rail_initialize():
        try:
            frame_file = request.files.get("frame")
            if frame_file is None:
                return jsonify(ok=False, error="缺少初始化影格"), 400
            frame = _decode_frame(frame_file)
            roi = _parse_roi(request.form.getlist("roi[]") or request.form.get("roi", "").split(","), frame)
            fps = float(request.form.get("fps", "30"))
            direction = request.form.get("direction", "y")
            source = request.form.get("source", "browser")
            if not 1 <= fps <= 120:
                raise ValueError("FPS 必須介於 1 至 120")
            if direction not in ALLOWED_DIRECTIONS:
                raise ValueError("位移方向設定錯誤")
            if source not in {"browser", "upload", "server"}:
                raise ValueError("影像來源設定錯誤")
            engine = RailEngine(fps=fps, direction=direction,
                                blur_detect=True, low_light=False,
                                denoise=True, shake_compensation=True)
            engine.initialize_roi(frame, roi)
            owner_id = _user_id(current_user)
            _, baseline_path = _baseline_paths(app, owner_id)
            if os.path.exists(baseline_path):
                engine.load_baselines(baseline_path)
            runtime = RailRuntime(engine, owner_id)
            runtime.source = source
            manager.set(owner_id, runtime)
            return jsonify(ok=True, initialized=True, status=engine.get_status())
        except (ValueError, RuntimeError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @bp.post("/api/rail/frame")
    @login_required
    def rail_frame():
        runtime = manager.get(_user_id(current_user))
        if runtime is None:
            return jsonify(ok=False, error="請先初始化 Rail 分析"), 409
        try:
            frame = _decode_frame(request.files.get("frame")) if request.files.get("frame") else None
            if frame is None:
                return jsonify(ok=False, error="缺少影格"), 400
            timestamp = float(request.form.get("timestamp", "nan"))
            if not np.isfinite(timestamp):
                return jsonify(ok=False, error="timestamp 必須是有效秒數"), 400
            with runtime.lock:
                result = runtime.engine.process_frame(frame, timestamp=timestamp)
                runtime.last_error = None
            return jsonify(ok=True, result=result.to_dict())
        except (ValueError, RuntimeError, TypeError) as exc:
            runtime.last_error = str(exc)
            return jsonify(ok=False, error=str(exc)), 400

    @bp.get("/api/rail/server-camera/preview")
    @login_required
    def rail_server_camera_preview():
        try:
            device_index = int(request.args.get("device_index", "0"))
            if device_index < 0 or device_index > 4:
                raise ValueError("攝影機編號只允許 0 至 4")
            cap = cv2.VideoCapture(device_index)
            if not cap.isOpened():
                cap.release()
                return jsonify(ok=False, error=f"無法開啟伺服器攝影機 {device_index}"), 503
            ok, frame = cap.read()
            cap.release()
            if not ok:
                return jsonify(ok=False, error="無法讀取伺服器攝影機影格"), 503
            success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not success:
                return jsonify(ok=False, error="影格 JPEG 編碼失敗"), 500
            from flask import Response
            return Response(encoded.tobytes(), mimetype="image/jpeg",
                            headers={"Cache-Control": "no-store"})
        except (ValueError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @bp.post("/api/rail/server-camera/start")
    @login_required
    def rail_server_camera_start():
        owner_id = _user_id(current_user)
        runtime = manager.get(owner_id)
        if runtime is None or not runtime.engine.roi:
            return jsonify(ok=False, error="請先以攝影機預覽影格完成 ROI 初始化，再啟動伺服器攝影機"), 409
        if runtime.source != "server":
            return jsonify(ok=False, error="目前分析工作階段不是伺服器攝影機來源，請重新初始化"), 409
        payload = request.get_json(silent=True) or {}
        try:
            device_index = int(payload.get("device_index", 0))
            if device_index < 0 or device_index > 4:
                raise ValueError("攝影機編號只允許 0 至 4")
            cap = cv2.VideoCapture(device_index)
            if not cap.isOpened():
                cap.release()
                return jsonify(ok=False, error=f"無法開啟伺服器攝影機 {device_index}"), 503
            runtime.capture = cap
            runtime.stop_event.clear()

            def capture_loop():
                while not runtime.stop_event.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        runtime.last_error = "伺服器攝影機讀取影格失敗"
                        break
                    ts = time.monotonic()
                    try:
                        with runtime.lock:
                            runtime.engine.process_frame(frame, timestamp=ts)
                    except Exception as exc:  # keep worker failure visible to status endpoint
                        runtime.last_error = str(exc)
                        break
                cap.release()
                runtime.capture = None

            runtime.worker = threading.Thread(target=capture_loop,
                                              name=f"rail-camera-{owner_id}", daemon=True)
            runtime.worker.start()
            return jsonify(ok=True, message="伺服器攝影機已啟動")
        except (ValueError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @bp.post("/api/rail/stop")
    @login_required
    def rail_stop():
        manager.stop(_user_id(current_user))
        return jsonify(ok=True, active=False)

    @bp.get("/api/rail/analyze")
    @login_required
    def rail_analyze():
        runtime = manager.get(_user_id(current_user))
        if runtime is None:
            return jsonify(ok=False, error="目前沒有分析工作階段"), 409
        try:
            with runtime.lock:
                analysis = runtime.engine.analyze_signal(
                    direction=request.args.get("direction") or None,
                    band_low_hz=_optional_float(request.args.get("band_low_hz")),
                    band_high_hz=_optional_float(request.args.get("band_high_hz")),
                )
            return jsonify(ok=True, analysis=analysis)
        except (ValueError, RuntimeError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @bp.post("/api/rail/baseline/record")
    @login_required
    def rail_record_baseline():
        runtime = manager.get(_user_id(current_user))
        if runtime is None:
            return jsonify(ok=False, error="目前沒有分析工作階段"), 409
        payload = request.get_json(silent=True) or {}
        label = str(payload.get("label", "normal")).strip()[:40] or "normal"
        sample_path, _ = _baseline_paths(app, _user_id(current_user))
        try:
            with runtime.lock:
                row = runtime.engine.record_normal_sample(
                    sample_path, label=label,
                    mode=runtime.source,
                )
            return jsonify(ok=True, sample=row)
        except (ValueError, RuntimeError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @bp.post("/api/rail/baseline/build")
    @login_required
    def rail_build_baseline():
        owner_id = _user_id(current_user)
        runtime = manager.get(owner_id)
        if runtime is None:
            return jsonify(ok=False, error="請先初始化 Rail 分析"), 409
        sample_path, baseline_path = _baseline_paths(app, owner_id)
        if not os.path.exists(sample_path):
            return jsonify(ok=False, error="尚無正常樣本，請先記錄樣本"), 400
        try:
            with runtime.lock:
                rows = runtime.engine.build_baseline(sample_path, baseline_path)
            return jsonify(ok=True, baselines=rows)
        except (ValueError, RuntimeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def _optional_float(value):
        if value in (None, ""):
            return None
        result = float(value)
        if not np.isfinite(result):
            raise ValueError("頻帶設定必須是有效數值")
        return result

    def _baseline_paths(flask_app, owner_id):
        folder = Path(flask_app.instance_path) / "rail_data"
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder / f"user_{owner_id}_samples.csv"), str(folder / f"user_{owner_id}_baseline.csv")

    app.register_blueprint(bp)
    return bp
