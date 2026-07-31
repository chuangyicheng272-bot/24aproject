"""
此為舊版單一 UWB 模擬器。

目前六終端展示不使用本程式。
正式流程請執行：
helmet_tag_simulator.py
anchor_simulator.py × 4
app.py
"""

import math
import random
import time

import requests


# 若 Flask 執行於區域網路中的其他電腦，只需修改此處的 IP。
API_URL = "http://127.0.0.1:5000/api/uwb"

HEADERS = {
    "Content-Type": "application/json"
}

UWB_ANCHORS = {
    "distance_a1": {"id": "Anchor1", "x": 0.0, "y": 0.0, "z": 150.0},
    "distance_a2": {"id": "Anchor2", "x": 300.0, "y": 0.0, "z": 50.0},
    "distance_a3": {"id": "Anchor3", "x": 0.0, "y": 300.0, "z": 50.0},
    "distance_a4": {"id": "Anchor4", "x": 300.0, "y": 300.0, "z": 150.0},
}

# 這些座標只存在模擬器內，不會包含在送給 Flask 的 payload 中。
WORKERS = {
    "W-001": {"x": 54.0, "y": 72.0, "z": 100.0},
    "W-002": {"x": 141.0, "y": 183.0, "z": 100.0},
    "W-003": {"x": 222.0, "y": 66.0, "z": 100.0},
}


def calculate_distance_to_anchors(x, y, z):
    """計算 Tag 座標到四個 Anchor 的 3D 歐式距離。"""
    return {
        key: math.sqrt(
            (x - anchor["x"]) ** 2
            + (y - anchor["y"]) ** 2
            + (z - anchor["z"]) ** 2
        )
        for key, anchor in UWB_ANCHORS.items()
    }


def move_worker(position):
    """小幅移動工人，並將座標限制在模擬場域內。"""
    position["x"] = max(0.0, min(300.0, position["x"] + random.uniform(-8, 8)))
    position["y"] = max(0.0, min(300.0, position["y"] + random.uniform(-8, 8)))
    position["z"] = max(50.0, min(150.0, position["z"] + random.uniform(-3, 3)))


def send_uwb_data(worker_id, position):
    """建立 ESP32 格式的 payload，送往 Flask 並顯示結果。"""
    distances = calculate_distance_to_anchors(
        position["x"], position["y"], position["z"]
    )
    payload = {"worker_id": worker_id, **distances}

    try:
        response = requests.post(
            API_URL,
            json=payload,
            headers=HEADERS,
            timeout=5,
        )
    except requests.exceptions.ConnectionError:
        print(f"[{worker_id}] 連線失敗：請確認 Flask 已啟動（{API_URL}）")
        return
    except requests.exceptions.Timeout:
        print(f"[{worker_id}] 連線逾時：後端在 5 秒內未回應")
        return
    except requests.exceptions.RequestException as error:
        print(f"[{worker_id}] HTTP 請求失敗：{error}")
        return

    print(f"[{worker_id}] HTTP {response.status_code}")
    print(
        "distances: "
        f"a1={distances['distance_a1']:.2f}, "
        f"a2={distances['distance_a2']:.2f}, "
        f"a3={distances['distance_a3']:.2f}, "
        f"a4={distances['distance_a4']:.2f}"
    )

    if response.status_code != 200:
        print(f"後端錯誤：{response.text}")
        return

    try:
        response_data = response.json()
    except requests.exceptions.JSONDecodeError:
        print(f"JSON 解析失敗，原始回應：{response.text}")
        return

    calculated_position = response_data.get("calculated_position")
    if not isinstance(calculated_position, dict):
        print(f"後端回應缺少 calculated_position：{response.text}")
        return

    try:
        print(
            "calculated_position: "
            f"x={float(calculated_position['x']):.2f}, "
            f"y={float(calculated_position['y']):.2f}, "
            f"z={float(calculated_position['z']):.2f}"
        )
    except (KeyError, TypeError, ValueError):
        print(f"calculated_position 格式錯誤：{response.text}")


def main():
    print(f"UWB simulator started. API: {API_URL}")
    try:
        while True:
            for worker_id, position in WORKERS.items():
                move_worker(position)
                send_uwb_data(worker_id, position)
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nUWB simulator stopped.")


if __name__ == "__main__":
    main()
