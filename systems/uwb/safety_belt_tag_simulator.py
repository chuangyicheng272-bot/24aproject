"""模擬三條智慧安全腰帶的 UWB Tag（座標與距離單位：mm）。"""

import random
import threading
import time
from collections import deque

from flask import Flask, jsonify, request
import requests

app = Flask(__name__)
state_lock = threading.Lock()
sequence_id = 0
timestamp = int(time.time())
MODE_FIXED = "fixed"
MODE_MOVING = "moving"
SIMULATION_MODE = MODE_MOVING
FASTAPI_BELT_URL = "http://127.0.0.1:8000/api/belt/status"

# 保留近期真實模擬座標，供 Flask 依 belt_id + sequence_id 驗證定位誤差。
state_history = deque(maxlen=100)

tags = {
    "BELT-001": {
        "belt_id": "BELT-001",
        "battery": 85, "charging": False,
        "device_type": "safety_belt", "sequence_id": 0,
        "x": 540.0, "y": 720.0, "z": 1000.0,
    },
    "BELT-002": {
        "belt_id": "BELT-002",
        "battery": 85, "charging": False,
        "device_type": "safety_belt", "sequence_id": 0,
        "x": 1410.0, "y": 1830.0, "z": 1000.0,
    },
    "BELT-003": {
        "belt_id": "BELT-003",
        "battery": 85, "charging": False,
        "device_type": "safety_belt", "sequence_id": 0,
        "x": 2220.0, "y": 660.0, "z": 1000.0,
    },
}


def move_tags():
    global sequence_id, timestamp
    while True:
        with state_lock:
            sequence_id += 1
            timestamp = int(time.time())
            for tag in tags.values():
                if SIMULATION_MODE == MODE_MOVING:
                    tag["x"] = max(0.0, min(3000.0, tag["x"] + random.uniform(-80, 80)))
                    tag["y"] = max(0.0, min(3000.0, tag["y"] + random.uniform(-80, 80)))
                    tag["z"] = max(500.0, min(1500.0, tag["z"] + random.uniform(-30, 30)))
                tag["sequence_id"] = sequence_id
            current_tags = [tag.copy() for tag in tags.values()]
            state_history.append({
                "sequence_id": sequence_id,
                "timestamp": timestamp,
                "simulation_mode": SIMULATION_MODE,
                "tags": current_tags,
            })

        print("\n[SMART SAFETY BELT / UWB TAG]")
        print(f"mode={SIMULATION_MODE}")
        print(f"sequence_id={sequence_id}, timestamp={timestamp}")
        for tag in current_tags:
            print(
                f"{tag['belt_id']}: "
                f"x={tag['x']:.1f}, y={tag['y']:.1f}, z={tag['z']:.1f} mm"
            )
            try:
                requests.post(
                    FASTAPI_BELT_URL,
                    json={
                        "belt_id": tag["belt_id"],
                        "timestamp": timestamp,
                        "battery": tag["battery"],
                        "charging": tag["charging"],
                    },
                    timeout=3,
                ).raise_for_status()
            except requests.RequestException as error:
                print(f"{tag['belt_id']} 狀態傳送 FastAPI 失敗：{error}")
        time.sleep(2)


@app.get("/api/tag/state")
def get_tag_state():
    with state_lock:
        requested_sequence = request.args.get("sequence_id", type=int)
        if requested_sequence is not None:
            for snapshot in reversed(state_history):
                if snapshot["sequence_id"] == requested_sequence:
                    return jsonify({
                        "sequence_id": snapshot["sequence_id"],
                        "timestamp": snapshot["timestamp"],
                        "simulation_mode": snapshot["simulation_mode"],
                        "tags": [tag.copy() for tag in snapshot["tags"]],
                    })
            return jsonify({
                "sequence_id": requested_sequence,
                "timestamp": None,
                "simulation_mode": SIMULATION_MODE,
                "tags": [],
            }), 404

        return jsonify({
            "sequence_id": sequence_id,
            "timestamp": timestamp,
            "simulation_mode": SIMULATION_MODE,
            "tags": [tag.copy() for tag in tags.values()],
        })


if __name__ == "__main__":
    threading.Thread(target=move_tags, daemon=True).start()
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)
