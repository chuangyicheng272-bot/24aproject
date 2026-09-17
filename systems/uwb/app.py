import sqlite3
from collections import deque
from datetime import datetime
from math import isfinite, sqrt
from pathlib import Path
from threading import Lock

import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "safety_monitor.db"

UWB_ANCHORS = {
    "distance_a1": {"id": "Anchor1", "x": 0.0, "y": 0.0, "z": 1500.0},
    "distance_a2": {"id": "Anchor2", "x": 3000.0, "y": 0.0, "z": 500.0},
    "distance_a3": {"id": "Anchor3", "x": 0.0, "y": 3000.0, "z": 500.0},
    "distance_a4": {"id": "Anchor4", "x": 3000.0, "y": 3000.0, "z": 1500.0},
}
REGISTERED_BELT_IDS = {"BELT-001", "BELT-002", "BELT-003"}
MIN_DISTANCE_MM = 0.0
MAX_DISTANCE_MM = 4500.0

range_buffer = {}
range_buffer_lock = Lock()
MODE_FIXED = "fixed"
MODE_MOVING = "moving"
FIXED_MODE_WINDOW = 10
MOVING_MODE_WINDOW = 3
position_history = {}
position_history_lock = Lock()

SIMULATION_ENABLED = True
TAG_STATE_URL = "http://127.0.0.1:5001/api/tag/state"

SEED_BELTS = [
    {
        "belt_id": "BELT-001", "device_name": "智慧安全腰帶 1",
        "x": 540.0, "y": 720.0, "z": 1000.0,
    },
    {
        "belt_id": "BELT-002", "device_name": "智慧安全腰帶 2",
        "x": 1410.0, "y": 1830.0, "z": 1000.0,
    },
    {
        "belt_id": "BELT-003", "device_name": "智慧安全腰帶 3",
        "x": 2220.0, "y": 660.0, "z": 1000.0,
    },
]
SEED_DANGER_ZONES = [
    {
        "id": "edge-a", "name": "樓層邊緣 A 區",
        "x1": 2040, "y1": 240, "x2": 2820, "y2": 1140, "risk": "high",
    },
    {
        "id": "opening-b", "name": "洞口施工 B 區",
        "x1": 1050, "y1": 1440, "x2": 1740, "y2": 2160, "risk": "high",
    },
    {
        "id": "rebar-c", "name": "鋼筋堆放 C 區",
        "x1": 240, "y1": 540, "x2": 900, "y2": 1260, "risk": "medium",
    },
]


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row):
    data = dict(row)
    for key in ("charging", "online"):
        if key in data:
            data[key] = bool(data[key])
    return data


def table_exists(conn, table_name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone() is not None


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS danger_zones (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                x1 REAL NOT NULL,
                y1 REAL NOT NULL,
                x2 REAL NOT NULL,
                y2 REAL NOT NULL,
                risk TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS belts (
                belt_id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                z REAL NOT NULL,
                battery INTEGER NOT NULL DEFAULT 100,
                charging INTEGER NOT NULL DEFAULT 0,
                online INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS uwb_logs_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                belt_id TEXT NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                z REAL NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS uwb_distance_logs_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                belt_id TEXT NOT NULL,
                distance_a1 REAL NOT NULL,
                distance_a2 REAL NOT NULL,
                distance_a3 REAL NOT NULL,
                distance_a4 REAL NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS uwb_position_error_logs_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                belt_id TEXT NOT NULL,
                sequence_id INTEGER NOT NULL,
                simulation_mode TEXT NOT NULL,
                raw_x_mm REAL NOT NULL,
                raw_y_mm REAL NOT NULL,
                raw_z_mm REAL NOT NULL,
                average_x_mm REAL NOT NULL,
                average_y_mm REAL NOT NULL,
                average_z_mm REAL NOT NULL,
                true_x_mm REAL,
                true_y_mm REAL,
                true_z_mm REAL,
                error_x_mm REAL,
                error_y_mm REAL,
                error_z_mm REAL,
                error_distance_mm REAL,
                tracking_error_x_mm REAL,
                tracking_error_y_mm REAL,
                tracking_error_z_mm REAL,
                tracking_error_distance_mm REAL,
                mean_deviation_mm REAL NOT NULL,
                max_deviation_mm REAL NOT NULL,
                sample_count INTEGER NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_uwb_position_error_v2_belt_sequence
            ON uwb_position_error_logs_v2 (belt_id, sequence_id);
            CREATE TABLE IF NOT EXISTS belt_status_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                belt_id TEXT NOT NULL,
                battery INTEGER NOT NULL,
                charging INTEGER NOT NULL,
                online INTEGER NOT NULL,
                device_timestamp INTEGER NOT NULL,
                received_at TEXT NOT NULL
            );
            """
        )

        version = conn.execute(
            "SELECT value FROM app_metadata WHERE key='belt_schema_version'"
        ).fetchone()
        if version is None:
            old_rows = []
            # 舊主表僅供一次性裝置狀態遷移，正式流程不再讀寫。
            if table_exists(conn, "workers"):
                old_rows = conn.execute(
                    """
                    SELECT x, y, z, battery, charging, online, updated_at
                    FROM workers ORDER BY rowid LIMIT 3
                    """
                ).fetchall()
            for index, seed in enumerate(SEED_BELTS):
                old = old_rows[index] if index < len(old_rows) else None
                values = {
                    **seed,
                    "x": old["x"] if old else seed["x"],
                    "y": old["y"] if old else seed["y"],
                    "z": old["z"] if old else seed["z"],
                    "battery": old["battery"] if old else 100,
                    "charging": old["charging"] if old else 0,
                    "online": old["online"] if old else 1,
                    "updated_at": old["updated_at"] if old else now_text(),
                }
                conn.execute(
                    """
                    INSERT OR IGNORE INTO belts
                    (belt_id, device_name, x, y, z, battery, charging, online, updated_at)
                    VALUES (:belt_id, :device_name, :x, :y, :z, :battery,
                            :charging, :online, :updated_at)
                    """,
                    values,
                )
            conn.execute(
                "INSERT INTO app_metadata(key,value) VALUES('belt_schema_version','1')"
            )

        if conn.execute("SELECT COUNT(*) FROM belts").fetchone()[0] == 0:
            conn.executemany(
                """
                INSERT INTO belts
                (belt_id, device_name, x, y, z, battery, charging, online, updated_at)
                VALUES (:belt_id, :device_name, :x, :y, :z, 100, 0, 1, :updated_at)
                """,
                [{**item, "updated_at": now_text()} for item in SEED_BELTS],
            )
        if conn.execute("SELECT COUNT(*) FROM danger_zones").fetchone()[0] == 0:
            conn.executemany(
                """
                INSERT INTO danger_zones(id,name,x1,y1,x2,y2,risk)
                VALUES (:id,:name,:x1,:y1,:x2,:y2,:risk)
                """,
                SEED_DANGER_ZONES,
            )


def get_belts(conn):
    return [
        row_to_dict(row)
        for row in conn.execute("SELECT * FROM belts ORDER BY belt_id").fetchall()
    ]


def get_belt(conn, belt_id):
    row = conn.execute(
        "SELECT * FROM belts WHERE belt_id=?", (belt_id,)
    ).fetchone()
    return row_to_dict(row) if row else None


def get_danger_zones(conn):
    return [
        dict(row)
        for row in conn.execute("SELECT * FROM danger_zones ORDER BY id").fetchall()
    ]


def find_zone(x, y, zones):
    for zone in zones:
        if zone["x1"] <= x <= zone["x2"] and zone["y1"] <= y <= zone["y2"]:
            return zone
    return None


def evaluate_belt(belt, zones):
    zone = find_zone(belt["x"], belt["y"], zones)
    if zone:
        return {
            "belt_id": belt["belt_id"],
            "zone": zone,
            "zone_risk": zone["risk"],
            "level": "注意",
            "action": "監控後台標示腰帶進入危險區域",
            "message": f"{belt['belt_id']} 進入{zone['name']}",
            "time": datetime.now().strftime("%H:%M:%S"),
        }
    return {
        "belt_id": belt["belt_id"],
        "zone": None,
        "zone_risk": None,
        "level": "正常",
        "action": "無需通報",
        "message": f"{belt['belt_id']} 目前未進入危險區域",
        "time": datetime.now().strftime("%H:%M:%S"),
    }


def solve_linear_3x3(matrix, vector):
    augmented = [row[:] + [value] for row, value in zip(matrix, vector)]
    for pivot_index in range(3):
        pivot_row = max(
            range(pivot_index, 3),
            key=lambda row_index: abs(augmented[row_index][pivot_index]),
        )
        if abs(augmented[pivot_row][pivot_index]) < 1e-9:
            raise ValueError("anchor layout cannot calculate a 3D position")
        augmented[pivot_index], augmented[pivot_row] = (
            augmented[pivot_row], augmented[pivot_index]
        )
        pivot = augmented[pivot_index][pivot_index]
        augmented[pivot_index] = [
            value / pivot for value in augmented[pivot_index]
        ]
        for row_index in range(3):
            if row_index == pivot_index:
                continue
            factor = augmented[row_index][pivot_index]
            augmented[row_index] = [
                current - factor * pivot_value
                for current, pivot_value in zip(
                    augmented[row_index], augmented[pivot_index]
                )
            ]
    return augmented[0][3], augmented[1][3], augmented[2][3]


def calculate_position_3d(distances):
    anchor_items = list(UWB_ANCHORS.items())
    reference_key, reference = anchor_items[0]
    x1, y1, z1 = reference["x"], reference["y"], reference["z"]
    d1 = distances[reference_key]
    matrix, vector = [], []
    for distance_key, anchor in anchor_items[1:]:
        xi, yi, zi = anchor["x"], anchor["y"], anchor["z"]
        di = distances[distance_key]
        matrix.append([2 * (xi - x1), 2 * (yi - y1), 2 * (zi - z1)])
        vector.append(
            d1**2 - di**2 + xi**2 - x1**2
            + yi**2 - y1**2 + zi**2 - z1**2
        )
    x, y, z = solve_linear_3x3(matrix, vector)
    return (
        max(0, min(3000, x)),
        max(0, min(3000, y)),
        max(500, min(1500, z)),
    )


def average_position(belt_id, simulation_mode, raw_x, raw_y, raw_z):
    window_size = (
        FIXED_MODE_WINDOW if simulation_mode == MODE_FIXED else MOVING_MODE_WINDOW
    )
    history_key = (belt_id, simulation_mode)
    with position_history_lock:
        history = position_history.get(history_key)
        if history is None:
            history = deque(maxlen=window_size)
            position_history[history_key] = history
        history.append((raw_x, raw_y, raw_z))
        samples = list(history)
    averages = tuple(
        sum(item[axis] for item in samples) / len(samples) for axis in range(3)
    )
    deviations = [
        sqrt(sum((item[axis] - averages[axis]) ** 2 for axis in range(3)))
        for item in samples
    ]
    return averages, {
        "mean_deviation_mm": sum(deviations) / len(deviations),
        "max_deviation_mm": max(deviations),
        "sample_count": len(samples),
    }


def get_simulation_info(belt_id, sequence_id):
    if not SIMULATION_ENABLED:
        return None
    try:
        response = requests.get(
            TAG_STATE_URL, params={"sequence_id": sequence_id}, timeout=1
        )
        response.raise_for_status()
        state = response.json()
        mode = state.get("simulation_mode")
        if state.get("sequence_id") != sequence_id or mode not in (
            MODE_FIXED, MODE_MOVING
        ):
            return None
        for tag in state.get("tags", []):
            if tag.get("belt_id") == belt_id and tag.get("sequence_id") == sequence_id:
                return {
                    "simulation_mode": mode,
                    "true_position_mm": {
                        axis: float(tag[axis]) for axis in ("x", "y", "z")
                    },
                }
    except (requests.RequestException, TypeError, ValueError, KeyError):
        return None
    return None


def calculate_difference(position, true_position):
    if true_position is None:
        return None
    difference = {
        axis: position[axis] - true_position[axis] for axis in ("x", "y", "z")
    }
    difference["distance"] = sqrt(
        sum(difference[axis] ** 2 for axis in ("x", "y", "z"))
    )
    return difference


def insert_distance_log(conn, belt_id, distances):
    conn.execute(
        """
        INSERT INTO uwb_distance_logs_v2
        (belt_id,distance_a1,distance_a2,distance_a3,distance_a4,received_at)
        VALUES (?,?,?,?,?,?)
        """,
        (
            belt_id, distances["distance_a1"], distances["distance_a2"],
            distances["distance_a3"], distances["distance_a4"], now_text(),
        ),
    )


def update_belt_position(conn, belt_id, x, y, z):
    received_at = now_text()
    conn.execute(
        "UPDATE belts SET x=?,y=?,z=?,updated_at=? WHERE belt_id=?",
        (x, y, z, received_at, belt_id),
    )
    conn.execute(
        "INSERT INTO uwb_logs_v2(belt_id,x,y,z,received_at) VALUES(?,?,?,?,?)",
        (belt_id, x, y, z, received_at),
    )


def insert_position_error_log(
    conn, belt_id, sequence_id, raw_position, simulation_mode, position,
    true_position, position_error, tracking_difference, spread,
):
    true_position = true_position or {}
    position_error = position_error or {}
    tracking_difference = tracking_difference or {}
    conn.execute(
        """
        INSERT OR IGNORE INTO uwb_position_error_logs_v2 (
            belt_id,sequence_id,simulation_mode,
            raw_x_mm,raw_y_mm,raw_z_mm,
            average_x_mm,average_y_mm,average_z_mm,
            true_x_mm,true_y_mm,true_z_mm,
            error_x_mm,error_y_mm,error_z_mm,error_distance_mm,
            tracking_error_x_mm,tracking_error_y_mm,
            tracking_error_z_mm,tracking_error_distance_mm,
            mean_deviation_mm,max_deviation_mm,sample_count,received_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            belt_id, sequence_id, simulation_mode,
            raw_position["x"], raw_position["y"], raw_position["z"],
            position["x"], position["y"], position["z"],
            true_position.get("x"), true_position.get("y"), true_position.get("z"),
            position_error.get("x"), position_error.get("y"),
            position_error.get("z"), position_error.get("distance"),
            tracking_difference.get("x"), tracking_difference.get("y"),
            tracking_difference.get("z"), tracking_difference.get("distance"),
            spread["mean_deviation_mm"], spread["max_deviation_mm"],
            spread["sample_count"], now_text(),
        ),
    )


def read_dashboard_data():
    with get_db() as conn:
        belts = get_belts(conn)
        zones = get_danger_zones(conn)
        assessments = [evaluate_belt(belt, zones) for belt in belts]
        positioning = {}
        rows = conn.execute(
            """
            SELECT log.* FROM uwb_position_error_logs_v2 AS log
            JOIN (
                SELECT belt_id, MAX(id) AS latest_id
                FROM uwb_position_error_logs_v2 GROUP BY belt_id
            ) AS latest ON latest.latest_id=log.id
            """
        ).fetchall()
        for row in rows:
            item = dict(row)
            positioning[item["belt_id"]] = {
                "simulation_mode": item["simulation_mode"],
                "raw_position_mm": {
                    "x": item["raw_x_mm"], "y": item["raw_y_mm"],
                    "z": item["raw_z_mm"],
                },
                "position_mm": {
                    "x": item["average_x_mm"], "y": item["average_y_mm"],
                    "z": item["average_z_mm"],
                },
                "error_distance_mm": item["error_distance_mm"],
                "tracking_difference_mm": item["tracking_error_distance_mm"],
                "mean_deviation_mm": item["mean_deviation_mm"],
                "max_deviation_mm": item["max_deviation_mm"],
                "sample_count": item["sample_count"],
            }
        return {
            "belts": belts,
            "danger_zones": zones,
            "assessments": assessments,
            "positioning": positioning,
            "updated_at": now_text(),
        }


def process_single_anchor_range(data):
    sequence_id = data.get("sequence_id")
    timestamp = data.get("timestamp")
    anchor_id = str(data.get("anchor_id", "")).strip()
    detected_belts = data.get("detected_belts")
    anchor_to_key = {
        anchor["id"]: key for key, anchor in UWB_ANCHORS.items()
    }
    if not isinstance(sequence_id, int) or isinstance(sequence_id, bool):
        return {"status": "error", "error": "sequence_id must be an integer"}, 400
    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        return {"status": "error", "error": "timestamp must be an integer"}, 400
    if anchor_id not in anchor_to_key:
        return {"status": "error", "error": "invalid anchor_id"}, 400
    if not isinstance(detected_belts, dict) or not detected_belts:
        return {"status": "error", "error": "detected_belts must be a non-empty object"}, 400

    validated, results = {}, {}
    for belt_id, measurement in detected_belts.items():
        if belt_id not in REGISTERED_BELT_IDS:
            results[belt_id] = {"status": "error", "error": "belt_id not registered"}
            continue
        if not isinstance(measurement, dict):
            return {"status": "error", "error": "belt measurement must be an object"}, 400
        try:
            distance_mm = float(measurement.get("distance_mm"))
        except (TypeError, ValueError):
            return {"status": "error", "error": "distance_mm must be a number"}, 400
        if not isfinite(distance_mm) or not MIN_DISTANCE_MM <= distance_mm <= MAX_DISTANCE_MM:
            return {"status": "error", "error": "distance_mm must be between 0 and 4500 mm"}, 400
        validated[belt_id] = distance_mm

    completed = []
    with range_buffer_lock:
        for belt_id, distance_mm in validated.items():
            buffer_key = (belt_id, sequence_id)
            entry = range_buffer.setdefault(
                buffer_key, {"timestamp": timestamp, "ranges": {}}
            )
            entry["ranges"][anchor_id] = distance_mm
            missing = [
                item for item in anchor_to_key if item not in entry["ranges"]
            ]
            if missing:
                results[belt_id] = {
                    "status": "waiting",
                    "received_anchors": len(entry["ranges"]),
                    "missing_anchors": missing,
                }
            else:
                completed.append((belt_id, entry))
                del range_buffer[buffer_key]

    for belt_id, entry in completed:
        ranges = dict(entry["ranges"])
        distances = {
            key: ranges[item] for item, key in anchor_to_key.items()
        }
        try:
            raw_x, raw_y, raw_z = calculate_position_3d(distances)
            raw_position = {"x": raw_x, "y": raw_y, "z": raw_z}
            simulation_info = get_simulation_info(belt_id, sequence_id)
            simulation_mode = (
                simulation_info["simulation_mode"] if simulation_info else MODE_FIXED
            )
            true_position = (
                simulation_info["true_position_mm"] if simulation_info else None
            )
            averages, spread = average_position(
                belt_id, simulation_mode, raw_x, raw_y, raw_z
            )
            position = {"x": averages[0], "y": averages[1], "z": averages[2]}
            if simulation_mode == MODE_FIXED:
                position_error = calculate_difference(position, true_position)
                tracking_difference = None
            else:
                position_error = None
                # 移動模式差距包含測距誤差與平滑延遲，不是純定位誤差。
                tracking_difference = calculate_difference(position, true_position)
            with get_db() as conn:
                belt = get_belt(conn, belt_id)
                if belt is None:
                    raise ValueError("belt not found")
                insert_distance_log(conn, belt_id, distances)
                update_belt_position(
                    conn, belt_id, position["x"], position["y"], position["z"]
                )
                insert_position_error_log(
                    conn, belt_id, sequence_id, raw_position, simulation_mode,
                    position, true_position, position_error,
                    tracking_difference, spread,
                )
                belt = get_belt(conn, belt_id)
                assessment = evaluate_belt(belt, get_danger_zones(conn))
            results[belt_id] = {
                "status": "calculated",
                "belt_id": belt_id,
                "sequence_id": sequence_id,
                "simulation_mode": simulation_mode,
                "distances_mm": ranges,
                "raw_position_mm": raw_position,
                "position_mm": position,
                "true_position_mm": true_position,
                "position_error_mm": position_error,
                "tracking_difference_mm": tracking_difference,
                "position_spread_mm": spread,
                "assessment": assessment,
            }
        except ValueError as error:
            results[belt_id] = {"status": "error", "error": str(error)}

    calculated = any(item["status"] == "calculated" for item in results.values())
    return {
        "status": "processed",
        "sequence_id": sequence_id,
        "anchor_id": anchor_id,
        "timestamp": timestamp,
        "results": results,
    }, 200 if calculated else 202


def validate_belt_status(data):
    belt_id = data.get("belt_id")
    if not isinstance(belt_id, str) or not belt_id.strip():
        return None, "belt_id is required"
    belt_id = belt_id.strip()
    if belt_id not in REGISTERED_BELT_IDS:
        return None, "belt_id not registered"
    timestamp = data.get("timestamp")
    battery = data.get("battery")
    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        return None, "timestamp must be an integer"
    if not isinstance(battery, int) or isinstance(battery, bool) or not 0 <= battery <= 100:
        return None, "battery must be an integer between 0 and 100"
    if not isinstance(data.get("charging"), bool):
        return None, "charging must be a boolean"
    if not isinstance(data.get("online"), bool):
        return None, "online must be a boolean"
    return {
        "belt_id": belt_id,
        "timestamp": timestamp,
        "battery": battery,
        "charging": data["charging"],
        "online": data["online"],
    }, None


@app.get("/")
def dashboard():
    return render_template_string(PAGE)


@app.get("/api/status")
def status():
    return jsonify(read_dashboard_data())


@app.post("/api/uwb/range")
def receive_uwb_range():
    response_data, status_code = process_single_anchor_range(
        request.get_json(force=True)
    )
    return jsonify(response_data), status_code


@app.post("/api/belt/status")
def receive_belt_status():
    values, error = validate_belt_status(request.get_json(force=True))
    if error:
        return jsonify({"status": "error", "error": error}), 400
    received_at = now_text()
    with get_db() as conn:
        if get_belt(conn, values["belt_id"]) is None:
            return jsonify({"status": "error", "error": "belt not found"}), 404
        conn.execute(
            """
            UPDATE belts SET battery=?,charging=?,online=?,updated_at=?
            WHERE belt_id=?
            """,
            (
                values["battery"], int(values["charging"]), int(values["online"]),
                received_at, values["belt_id"],
            ),
        )
        conn.execute(
            """
            INSERT INTO belt_status_logs
            (belt_id,battery,charging,online,device_timestamp,received_at)
            VALUES(?,?,?,?,?,?)
            """,
            (
                values["belt_id"], values["battery"], int(values["charging"]),
                int(values["online"]), values["timestamp"], received_at,
            ),
        )
        belt = get_belt(conn, values["belt_id"])
        assessment = evaluate_belt(belt, get_danger_zones(conn))
    return jsonify({"status": "updated", "belt": belt, "assessment": assessment})


@app.patch("/api/belt/<belt_id>")
def update_belt(belt_id):
    if belt_id not in REGISTERED_BELT_IDS:
        return jsonify({"status": "error", "error": "belt_id not registered"}), 404
    data = request.get_json(force=True)
    allowed = {"x", "y", "z", "battery", "charging", "online"}
    if any(key not in allowed for key in data):
        return jsonify({"status": "error", "error": "unsupported field"}), 400
    with get_db() as conn:
        belt = get_belt(conn, belt_id)
        if belt is None:
            return jsonify({"status": "error", "error": "belt not found"}), 404
        x = max(0.0, min(3000.0, float(data.get("x", belt["x"]))))
        y = max(0.0, min(3000.0, float(data.get("y", belt["y"]))))
        z = max(500.0, min(1500.0, float(data.get("z", belt["z"]))))
        battery = data.get("battery", belt["battery"])
        charging = data.get("charging", belt["charging"])
        online = data.get("online", belt["online"])
        if not isinstance(battery, int) or isinstance(battery, bool) or not 0 <= battery <= 100:
            return jsonify({"status": "error", "error": "invalid battery"}), 400
        if not isinstance(charging, bool) or not isinstance(online, bool):
            return jsonify({"status": "error", "error": "invalid boolean status"}), 400
        conn.execute(
            """
            UPDATE belts SET x=?,y=?,z=?,battery=?,charging=?,online=?,updated_at=?
            WHERE belt_id=?
            """,
            (x, y, z, battery, int(charging), int(online), now_text(), belt_id),
        )
        belt = get_belt(conn, belt_id)
        assessment = evaluate_belt(belt, get_danger_zones(conn))
    return jsonify({"status": "updated", "belt": belt, "assessment": assessment})


PAGE = """
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>電子圍欄與智慧安全腰帶 UWB 監控</title>
  <style>
    :root { --ink:#172033; --muted:#657086; --line:#d9e0ea; --accent:#1f8a70;
      --warn:#c77a00; --danger:#c73e3a; }
    * { box-sizing:border-box; }
    body { margin:0; background:#eef3f8; color:var(--ink);
      font-family:"Microsoft JhengHei",Arial,sans-serif; }
    header { padding:18px 28px; color:#fff; background:#152238; display:flex;
      justify-content:space-between; align-items:center; }
    h1,h2 { margin:0; } .subtitle,small { color:var(--muted); }
    header .subtitle { color:#c9d4e5; margin-top:5px; }
    main { padding:18px; display:grid; grid-template-columns:minmax(420px,1fr)
      minmax(620px,1.5fr); gap:18px; }
    section { background:#fff; border:1px solid var(--line); border-radius:12px;
      overflow:hidden; box-shadow:0 8px 24px #17304a12; }
    .section-head { padding:14px 16px; border-bottom:1px solid var(--line); }
    .map { position:relative; height:560px; margin:16px; border:2px solid #8090a5;
      background:linear-gradient(#dce4ec 1px,transparent 1px),
      linear-gradient(90deg,#dce4ec 1px,transparent 1px); background-size:10% 10%; }
    .zone { position:absolute; background:#c73e3a33; border:2px dashed var(--danger);
      color:#8b1e1b; padding:5px; font-size:12px; }
    .zone.medium { background:#e5a11b33; border-color:var(--warn); }
    .belt-dot { position:absolute; width:34px; height:34px; border-radius:50%;
      transform:translate(-50%,-50%); display:grid; place-items:center; color:white;
      background:var(--accent); font-weight:bold; border:3px solid white;
      box-shadow:0 2px 8px #0005; }
    .belt-dot.notice { background:var(--warn); }
    .belt-dot small { position:absolute; top:34px; color:var(--ink); white-space:nowrap; }
    .side { display:grid; gap:18px; align-content:start; }
    table { border-collapse:collapse; width:100%; font-size:13px; }
    th,td { padding:10px; border-bottom:1px solid var(--line); text-align:left;
      vertical-align:top; }
    th { background:#f5f7fa; } .pill { display:inline-block; padding:4px 8px;
      border-radius:999px; background:#e8f5ee; color:#146752; border:0; }
    .pill.warn { background:#fff1d6; color:#925600; }
    button.pill { cursor:pointer; font:inherit; }
    .alerts { padding:12px; display:grid; gap:8px; }
    .alert { padding:10px; border-left:4px solid var(--warn); background:#fff7e7; }
    @media(max-width:1100px){main{grid-template-columns:1fr}.map{height:420px}}
  </style>
</head>
<body>
  <header>
    <div><h1>電子圍欄與智慧安全腰帶 UWB 監控</h1>
      <div class="subtitle">腰帶定位、裝置狀態與危險區域監控</div></div>
    <div id="clock">--</div>
  </header>
  <main>
    <section><div class="section-head"><h2>工地平面定位</h2></div>
      <div class="map" id="map"></div></section>
    <div class="side">
      <section><div class="section-head">
        <h2>智慧安全腰帶狀態</h2>
      </div>
        <table><thead><tr>
          <th>腰帶編號</th><th>目前定位座標 X/Y/Z</th><th>電量</th>
          <th>充電狀態</th><th>連線狀態</th><th>所在區域</th><th>風險</th>
        </tr></thead><tbody id="beltRows"></tbody></table>
      </section>
      <section><div class="section-head"><h2>即時警示</h2></div>
        <div class="alerts" id="alerts"></div></section>
    </div>
  </main>
  <script>
    const map = document.getElementById("map");
    const beltRows = document.getElementById("beltRows");
    const alerts = document.getElementById("alerts");
    const clock = document.getElementById("clock");
    let latestBelts = [];

    function assessmentFor(data, beltId) {
      return data.assessments.find(item => item.belt_id === beltId);
    }
    function drawMap(data) {
      map.innerHTML = "";
      data.danger_zones.forEach(zone => {
        const node = document.createElement("div");
        node.className = `zone ${zone.risk === "medium" ? "medium" : ""}`;
        node.style.left = `${zone.x1 / 3000 * 100}%`;
        node.style.top = `${zone.y1 / 3000 * 100}%`;
        node.style.width = `${(zone.x2-zone.x1) / 3000 * 100}%`;
        node.style.height = `${(zone.y2-zone.y1) / 3000 * 100}%`;
        node.textContent = zone.name; map.appendChild(node);
      });
      data.belts.forEach(belt => {
        const assessment = assessmentFor(data, belt.belt_id);
        const node = document.createElement("div");
        node.className = `belt-dot ${assessment.level === "注意" ? "notice" : ""}`;
        node.style.left = `${belt.x / 3000 * 100}%`;
        node.style.top = `${belt.y / 3000 * 100}%`;
        node.innerHTML = `${belt.belt_id.slice(-1)}<small>${belt.belt_id}</small>`;
        map.appendChild(node);
      });
    }
    function drawRows(data) {
      beltRows.innerHTML = data.belts.map(belt => {
        const assessment = assessmentFor(data, belt.belt_id);
        return `<tr>
          <td><strong>${belt.belt_id}</strong><br><small>${belt.device_name}</small></td>
          <td>X ${belt.x.toFixed(1)} mm<br>Y ${belt.y.toFixed(1)} mm<br>
            Z ${belt.z.toFixed(1)} mm</td>
          <td>${belt.battery}%</td>
          <td><button class="pill ${belt.charging ? "" : "warn"}"
            data-belt-id="${belt.belt_id}">${belt.charging ? "是" : "否"}</button></td>
          <td>${belt.online ? "線上" : "離線"}</td>
          <td>${assessment.zone ? assessment.zone.name : "安全區域"}</td>
          <td><span class="pill ${assessment.level === "注意" ? "warn" : ""}">
            ${assessment.level}</span></td></tr>`;
      }).join("");
    }
    function drawAlerts(data) {
      const visible = data.assessments.filter(item => item.level !== "正常");
      alerts.innerHTML = visible.length ? visible.map(item =>
        `<div class="alert"><strong>${item.time}｜${item.belt_id}</strong><br>
        ${item.message}<br><small>${item.action}</small></div>`).join("")
        : `<div class="alert">目前沒有腰帶進入危險區域。</div>`;
    }
    async function refresh() {
      const response = await fetch("/api/status");
      const data = await response.json();
      latestBelts = data.belts;
      clock.textContent = `更新時間 ${new Date(data.updated_at).toLocaleTimeString("zh-TW")}`;
      drawMap(data); drawRows(data); drawAlerts(data);
    }
    async function toggleCharging(beltId) {
      const belt = latestBelts.find(item => item.belt_id === beltId);
      if (!belt) return;
      await fetch("/api/belt/status", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({belt_id:belt.belt_id,
          timestamp:Math.floor(Date.now()/1000), battery:belt.battery,
          charging:!belt.charging, online:belt.online})
      });
      refresh();
    }
    beltRows.addEventListener("click", event => {
      const button = event.target.closest("button[data-belt-id]");
      if (button) toggleCharging(button.dataset.beltId);
    });
    refresh(); setInterval(refresh,1800);
  </script>
</body></html>
"""


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
