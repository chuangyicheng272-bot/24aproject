from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, request


cameras_bp = Blueprint("cameras", __name__)


def runtime():
    return current_app.config["SAFETY_RUNTIME"]


@cameras_bp.get("")
def get_camera_status():
    return jsonify(runtime().camera_status())


@cameras_bp.post("")
def configure_camera():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(runtime().configure_camera(payload))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@cameras_bp.post("/process-once")
def process_once():
    result = runtime().process_once()
    return jsonify(result)


@cameras_bp.get("/pairing-range")
def get_pairing_range():
    return jsonify(runtime().pairing_range.to_dict())


@cameras_bp.post("/pairing-range")
def configure_pairing_range():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(runtime().configure_pairing_range(payload))
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@cameras_bp.post("/overlay-mode")
def configure_overlay_mode():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(runtime().configure_overlay_mode(payload))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@cameras_bp.get("/stream")
def stream():
    response = Response(
        runtime().stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        direct_passthrough=True,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
