"""模擬單一 UWB Anchor；每輪以一個 HTTP request 回報所有偵測到的腰帶。"""

import argparse
import math
import random
import time

import requests

# safety_belt_tag_simulator.py 提供的 Tag 狀態 API。
TAG_URL = "http://127.0.0.1:5001/api/tag/state"
FLASK_URL = "http://127.0.0.1:5000/api/uwb/range"
DISTANCE_ERROR_LIMIT_MM = 150.0

ANCHORS = {
    "Anchor1": {"x": 0.0, "y": 0.0, "z": 1500.0, "level": "HIGH"},
    "Anchor2": {"x": 3000.0, "y": 0.0, "z": 500.0, "level": "LOW"},
    "Anchor3": {"x": 0.0, "y": 3000.0, "z": 500.0, "level": "LOW"},
    "Anchor4": {"x": 3000.0, "y": 3000.0, "z": 1500.0, "level": "HIGH"},
}


def run(anchor_id):
    anchor = ANCHORS[anchor_id]
    last_sequence_id = None

    while True:
        try:
            tag_response = requests.get(TAG_URL, timeout=5)
            tag_response.raise_for_status()
            tag_state = tag_response.json()
            sequence_id = tag_state.get("sequence_id")
            timestamp = tag_state.get("timestamp")
            current_tags = tag_state.get("tags", [])

            if (
                not isinstance(sequence_id, int)
                or sequence_id == last_sequence_id
                or not current_tags
            ):
                time.sleep(0.5)
                continue

            detected_belts = {}
            for tag in current_tags:
                true_range_mm = math.sqrt(
                    (tag["x"] - anchor["x"]) ** 2
                    + (tag["y"] - anchor["y"]) ** 2
                    + (tag["z"] - anchor["z"]) ** 2
                )
                measured_range_mm = random.triangular(
                    max(0.0, true_range_mm - DISTANCE_ERROR_LIMIT_MM),
                    true_range_mm + DISTANCE_ERROR_LIMIT_MM,
                    true_range_mm,
                )
                detected_belts[tag["belt_id"]] = {
                    "distance_mm": round(measured_range_mm, 2)
                }

            payload = {
                "sequence_id": sequence_id,
                "anchor_id": anchor_id,
                "timestamp": timestamp,
                "detected_belts": detected_belts,
            }
            response = requests.post(FLASK_URL, json=payload, timeout=5)
            body = response.json()
            print(
                f"[{anchor_id} | {anchor['level']}] sequence={sequence_id} "
                f"belts={len(detected_belts)} HTTP={response.status_code} "
                f"status={body.get('status', 'error')}"
            )
            if response.status_code in (200, 202):
                last_sequence_id = sequence_id
        except requests.exceptions.ConnectionError:
            print("連線失敗：請確認 safety_belt_tag_simulator.py 與 app.py 都已啟動。")
        except (requests.exceptions.Timeout, requests.exceptions.HTTPError):
            print("HTTP 請求逾時或失敗。")
        except (KeyError, TypeError, ValueError) as error:
            print(f"Tag 資料格式錯誤：{error}")
        time.sleep(0.5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", required=True, choices=ANCHORS)
    args = parser.parse_args()
    try:
        run(args.anchor)
    except KeyboardInterrupt:
        print(f"\n{args.anchor} stopped.")
