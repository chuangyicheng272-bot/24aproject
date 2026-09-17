from __future__ import annotations

from flask import Blueprint, current_app, jsonify


workers_bp = Blueprint("workers", __name__)


def runtime():
    return current_app.config["SAFETY_RUNTIME"]


@workers_bp.get("")
def list_workers():
    return jsonify(runtime().worker_status())
