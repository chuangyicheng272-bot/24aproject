from __future__ import annotations

from flask import Blueprint, current_app, jsonify


alerts_bp = Blueprint("alerts", __name__)


def runtime():
    return current_app.config["SAFETY_RUNTIME"]


@alerts_bp.get("")
def list_alerts():
    return jsonify(runtime().alert_status())
