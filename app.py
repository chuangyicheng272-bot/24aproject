import sqlite3
from collections import deque
from datetime import datetime
from math import isfinite, sqrt
from pathlib import Path
from threading import Lock
from time import monotonic

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "safety_monitor.db"

UWB_ANCHORS = {
    "distance_a1": {"id": "Anchor1", "x": 0.0, "y": 0.0, "z": 500.0},
    "distance_a2": {"id": "Anchor2", "x": 3000.0, "y": 0.0, "z": 30.0},
    "distance_a3": {"id": "Anchor3", "x": 0.0, "y": 3000.0, "z": 30.0},
    "distance_a4": {"id": "Anchor4", "x": 3000.0, "y": 3000.0, "z": 870.0},
}
# Single-point distance calibration (30-sample UWB mean minus tape distance).
ANCHOR_DISTANCE_OFFSETS_MM = {
    "Anchor1": 374.3,
    "Anchor2": 493.3,
    "Anchor3": 640.0,
    "Anchor4": 1125.7,
}
REGISTERED_BELT_IDS = {"BELT-001"}
MIN_DISTANCE_MM = 0.0
MAX_DISTANCE_MM = 6000.0

range_buffer = {}
range_buffer_lock = Lock()
RANGE_BUFFER_TTL_SECONDS = 3.0
HARDWARE_MODE = "hardware"
# 不做跨筆移動平均，避免人員移動時定位落後於實際位置。
HARDWARE_POSITION_WINDOW = 1
DEVICE_OFFLINE_SECONDS = 10
HISTORY_DEFAULT_LIMIT = 20
HISTORY_MAX_LIMIT = 200
GEOFENCE_WARNING_SECONDS = 30
GEOFENCE_CRITICAL_SECONDS = 60
position_history = {}
position_history_lock = Lock()

SEED_BELTS = [
    {
        "belt_id": "BELT-001", "device_name": "智慧安全腰帶 1",
        "x": 540.0, "y": 720.0, "z": 1000.0,
    },
]
SEED_DANGER_ZONES = [
    {
        "id": "edge-a", "name": "樓層邊緣 A 區",
        "x1": 2040, "y1": 240, "z1": 500,
        "x2": 2820, "y2": 1140, "z2": 1500, "risk": "high",
    },
    {
        "id": "opening-b", "name": "洞口施工 B 區",
        "x1": 1050, "y1": 1440, "z1": 500,
        "x2": 1740, "y2": 2160, "z2": 1500, "risk": "high",
    },
    {
        "id": "rebar-c", "name": "鋼筋堆放 C 區",
        "x1": 240, "y1": 540, "z1": 500,
        "x2": 900, "y2": 1260, "z2": 1500, "risk": "medium",
    },
]


def now_text():
    return datetime.now().isoformat(timespec="seconds")


class ClosingConnection(sqlite3.Connection):
    """讓既有 with get_db() 區塊在提交後確實關閉 SQLite 連線。"""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def get_db():
    conn = sqlite3.connect(DB_PATH, factory=ClosingConnection)
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
                z1 REAL NOT NULL,
                x2 REAL NOT NULL,
                y2 REAL NOT NULL,
                z2 REAL NOT NULL,
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
                online INTEGER NOT NULL DEFAULT 0,
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
            CREATE TABLE IF NOT EXISTS geofence_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                belt_id TEXT NOT NULL,
                sequence_id INTEGER NOT NULL,
                event_type TEXT NOT NULL CHECK(event_type IN ('ENTER', 'EXIT')),
                zone_name TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                z REAL NOT NULL,
                created_at TEXT NOT NULL,
                exited_at TEXT,
                duration_seconds INTEGER,
                status TEXT NOT NULL DEFAULT 'UNHANDLED',
                acknowledged_at TEXT,
                related_enter_id INTEGER
            );
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_geofence_event_unique
            ON geofence_events (belt_id, sequence_id, event_type, zone_name);
            """
        )

        # 沿用既有定位紀錄表，補上本次歷史軌跡需要的欄位。
        history_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(uwb_logs_v2)")
        }
        history_migrations = {
            "sequence_id": "INTEGER",
            "timestamp": "INTEGER",
            "risk_level": "TEXT",
            "zone_name": "TEXT",
            "created_at": "TEXT",
        }
        for column, column_type in history_migrations.items():
            if column not in history_columns:
                conn.execute(
                    f"ALTER TABLE uwb_logs_v2 ADD COLUMN {column} {column_type}"
                )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_uwb_logs_v2_belt_sequence
            ON uwb_logs_v2 (belt_id, sequence_id)
            WHERE sequence_id IS NOT NULL
            """
        )

        event_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(geofence_events)")
        }
        event_migrations = {
            "exited_at": "TEXT",
            "duration_seconds": "INTEGER",
            "status": "TEXT NOT NULL DEFAULT 'UNHANDLED'",
            "acknowledged_at": "TEXT",
            "related_enter_id": "INTEGER",
        }
        for column, column_type in event_migrations.items():
            if column not in event_columns:
                conn.execute(
                    f"ALTER TABLE geofence_events ADD COLUMN {column} {column_type}"
                )

        event_version = conn.execute(
            "SELECT value FROM app_metadata WHERE key='geofence_event_management_version'"
        ).fetchone()
        if event_version is None:
            # 依時間回補既有 ENTER／EXIT 配對，保留原始事件內容。
            open_events = {}
            old_events = conn.execute(
                "SELECT id,belt_id,event_type,zone_name,created_at "
                "FROM geofence_events ORDER BY id"
            ).fetchall()
            for event in old_events:
                key = (event["belt_id"], event["zone_name"])
                if event["event_type"] == "ENTER":
                    open_events[key] = event
                    continue
                conn.execute(
                    "UPDATE geofence_events SET status='RESOLVED' WHERE id=?",
                    (event["id"],),
                )
                entered = open_events.pop(key, None)
                if entered is None:
                    continue
                duration = max(
                    0,
                    int(
                        (
                            datetime.fromisoformat(event["created_at"])
                            - datetime.fromisoformat(entered["created_at"])
                        ).total_seconds()
                    ),
                )
                conn.execute(
                    """
                    UPDATE geofence_events
                    SET exited_at=?,duration_seconds=?,status='RESOLVED'
                    WHERE id=?
                    """,
                    (event["created_at"], duration, entered["id"]),
                )
                conn.execute(
                    """
                    UPDATE geofence_events
                    SET duration_seconds=?,related_enter_id=?
                    WHERE id=?
                    """,
                    (duration, entered["id"], event["id"]),
                )
            conn.execute(
                "INSERT INTO app_metadata(key,value) "
                "VALUES('geofence_event_management_version','1')"
            )

        danger_zone_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(danger_zones)")
        }
        if "z1" not in danger_zone_columns:
            conn.execute(
                "ALTER TABLE danger_zones ADD COLUMN z1 REAL NOT NULL DEFAULT 500"
            )
        if "z2" not in danger_zone_columns:
            conn.execute(
                "ALTER TABLE danger_zones ADD COLUMN z2 REAL NOT NULL DEFAULT 1500"
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
                VALUES (:belt_id, :device_name, :x, :y, :z, 100, 0, 0, :updated_at)
                """,
                [{**item, "updated_at": now_text()} for item in SEED_BELTS],
            )

        physical_mode_version = conn.execute(
            "SELECT value FROM app_metadata WHERE key='physical_mode_version'"
        ).fetchone()
        if physical_mode_version is None:
            placeholders = ",".join("?" for _ in REGISTERED_BELT_IDS)
            registered_ids = tuple(sorted(REGISTERED_BELT_IDS))
            for table in (
                "belt_status_logs",
                "uwb_logs_v2",
                "uwb_distance_logs_v2",
                "uwb_position_error_logs_v2",
                "belts",
            ):
                conn.execute(
                    f"DELETE FROM {table} WHERE belt_id NOT IN ({placeholders})",
                    registered_ids,
                )
            conn.execute(
                "INSERT INTO app_metadata(key,value) VALUES('physical_mode_version','1')"
            )
        if conn.execute("SELECT COUNT(*) FROM danger_zones").fetchone()[0] == 0:
            conn.executemany(
                """
                INSERT INTO danger_zones(id,name,x1,y1,z1,x2,y2,z2,risk)
                VALUES (:id,:name,:x1,:y1,:z1,:x2,:y2,:z2,:risk)
                """,
                SEED_DANGER_ZONES,
            )


def get_belts(conn):
    belts = [
        row_to_dict(row)
        for row in conn.execute("SELECT * FROM belts ORDER BY belt_id").fetchall()
    ]
    now = datetime.now()
    for belt in belts:
        try:
            updated_at = datetime.fromisoformat(belt["updated_at"])
            belt["online"] = (
                now - updated_at
            ).total_seconds() <= DEVICE_OFFLINE_SECONDS
        except (TypeError, ValueError):
            belt["online"] = False
    return belts


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


def find_zone(x, y, z, zones):
    for zone in zones:
        if (
            zone["x1"] <= x <= zone["x2"]
            and zone["y1"] <= y <= zone["y2"]
            and zone["z1"] <= z <= zone["z2"]
        ):
            return zone
    return None


def evaluate_belt(belt, zones):
    zone = find_zone(belt["x"], belt["y"], belt["z"], zones)
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
        z,
    )


def average_position(belt_id, raw_x, raw_y, raw_z):
    history_key = (belt_id, HARDWARE_MODE)
    with position_history_lock:
        history = position_history.get(history_key)
        if history is None:
            history = deque(maxlen=HARDWARE_POSITION_WINDOW)
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


def save_completed_position(
    conn, belt_id, sequence_id, device_timestamp, position, zones
):
    """儲存一次完整四站定位，並依前後區域差異建立進出事件。"""
    received_at = now_text()
    previous_row = conn.execute(
        """
        SELECT zone_name FROM uwb_logs_v2
        WHERE belt_id=? AND sequence_id IS NOT NULL
        ORDER BY id DESC LIMIT 1
        """,
        (belt_id,),
    ).fetchone()
    previous_zone_name = previous_row["zone_name"] if previous_row else None

    current_zone = find_zone(position["x"], position["y"], position["z"], zones)
    current_zone_name = current_zone["name"] if current_zone else None
    risk_level = current_zone["risk"] if current_zone else "safe"

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO uwb_logs_v2
        (belt_id,sequence_id,timestamp,x,y,z,risk_level,zone_name,received_at,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            belt_id, sequence_id, device_timestamp,
            position["x"], position["y"], position["z"],
            risk_level, current_zone_name, received_at, received_at,
        ),
    )
    if cursor.rowcount == 0:
        return False

    conn.execute(
        "UPDATE belts SET x=?,y=?,z=?,online=1,updated_at=? WHERE belt_id=?",
        (position["x"], position["y"], position["z"], received_at, belt_id),
    )

    events = []
    # 第一筆完整定位只建立狀態基準，之後才比較真正的定位狀態變化。
    if previous_row is not None:
        if previous_zone_name and previous_zone_name != current_zone_name:
            events.append(("EXIT", previous_zone_name))
        if current_zone_name and current_zone_name != previous_zone_name:
            events.append(("ENTER", current_zone_name))
    for event_type, zone_name in events:
        if event_type == "ENTER":
            conn.execute(
                """
                INSERT OR IGNORE INTO geofence_events
                (belt_id,sequence_id,event_type,zone_name,timestamp,x,y,z,
                 created_at,status)
                VALUES(?,?,?,?,?,?,?,?,?,'UNHANDLED')
                """,
                (
                    belt_id, sequence_id, event_type, zone_name, device_timestamp,
                    position["x"], position["y"], position["z"], received_at,
                ),
            )
            continue

        entered = conn.execute(
            """
            SELECT id,created_at FROM geofence_events
            WHERE belt_id=? AND zone_name=? AND event_type='ENTER'
              AND exited_at IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (belt_id, zone_name),
        ).fetchone()
        related_enter_id = entered["id"] if entered else None
        duration = None
        if entered:
            duration = max(
                0,
                int(
                    (
                        datetime.fromisoformat(received_at)
                        - datetime.fromisoformat(entered["created_at"])
                    ).total_seconds()
                ),
            )
            conn.execute(
                """
                UPDATE geofence_events
                SET exited_at=?,duration_seconds=?,status='RESOLVED'
                WHERE id=?
                """,
                (received_at, duration, related_enter_id),
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO geofence_events
            (belt_id,sequence_id,event_type,zone_name,timestamp,x,y,z,created_at,
             duration_seconds,status,related_enter_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,'RESOLVED',?)
            """,
            (
                belt_id, sequence_id, event_type, zone_name, device_timestamp,
                position["x"], position["y"], position["z"], received_at,
                duration, related_enter_id,
            ),
        )
    return True


def get_position_history(
    conn, belt_id, limit=HISTORY_DEFAULT_LIMIT, start_at=None, end_at=None
):
    conditions = ["belt_id=?", "sequence_id IS NOT NULL"]
    parameters = [belt_id]
    if start_at:
        conditions.append("COALESCE(created_at, received_at) >= ?")
        parameters.append(start_at)
    if end_at:
        conditions.append("COALESCE(created_at, received_at) <= ?")
        parameters.append(end_at)
    parameters.append(limit)
    rows = conn.execute(
        f"""
        SELECT belt_id,sequence_id,timestamp,x,y,z,risk_level,zone_name,
               COALESCE(created_at, received_at) AS created_at
        FROM uwb_logs_v2
        WHERE {' AND '.join(conditions)}
        ORDER BY id DESC LIMIT ?
        """,
        parameters,
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


def get_geofence_events(
    conn, limit=HISTORY_DEFAULT_LIMIT, belt_id=None, start_at=None, end_at=None
):
    conditions = []
    parameters = []
    if belt_id:
        conditions.append("belt_id=?")
        parameters.append(belt_id)
    if start_at:
        conditions.append("created_at >= ?")
        parameters.append(start_at)
    if end_at:
        conditions.append("created_at <= ?")
        parameters.append(end_at)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    parameters.append(limit)
    events = [
        dict(row) for row in conn.execute(
            f"""
            SELECT id,belt_id,sequence_id,event_type,zone_name,timestamp,x,y,z,
                   created_at,exited_at,duration_seconds,status,acknowledged_at,
                   related_enter_id
            FROM geofence_events {where_clause} ORDER BY id DESC LIMIT ?
            """,
            parameters,
        ).fetchall()
    ]
    current_time = datetime.now()
    for event in events:
        duration = event["duration_seconds"]
        if event["event_type"] == "ENTER" and event["exited_at"] is None:
            duration = max(
                0,
                int(
                    (
                        current_time - datetime.fromisoformat(event["created_at"])
                    ).total_seconds()
                ),
            )
        event["duration_seconds"] = duration
        if event["event_type"] != "ENTER":
            event["alert_level"] = "normal"
        elif duration is not None and duration > GEOFENCE_CRITICAL_SECONDS:
            event["alert_level"] = "critical"
        elif duration is not None and duration > GEOFENCE_WARNING_SECONDS:
            event["alert_level"] = "warning"
        else:
            event["alert_level"] = "notice"
    return events


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
        histories = {
            belt["belt_id"]: get_position_history(
                conn, belt["belt_id"], HISTORY_DEFAULT_LIMIT
            )
            for belt in belts
        }
        return {
            "belts": belts,
            "danger_zones": zones,
            "assessments": assessments,
            "positioning": positioning,
            "histories": histories,
            "geofence_events": get_geofence_events(conn, HISTORY_DEFAULT_LIMIT),
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
            return {
                "status": "error",
                "error": f"distance_mm must be between 0 and {MAX_DISTANCE_MM:.0f} mm",
            }, 400
        validated[belt_id] = distance_mm

    completed = []
    with range_buffer_lock:
        received_at_monotonic = monotonic()
        stale_keys = [
            key for key, item in range_buffer.items()
            if received_at_monotonic - item["created_at_monotonic"]
            > RANGE_BUFFER_TTL_SECONDS
        ]
        for stale_key in stale_keys:
            del range_buffer[stale_key]

        for belt_id, distance_mm in validated.items():
            buffer_key = (belt_id, sequence_id)
            entry = range_buffer.setdefault(
                buffer_key,
                {
                    "timestamp": timestamp,
                    "created_at_monotonic": received_at_monotonic,
                    "ranges": {},
                },
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
        raw_ranges = dict(entry["ranges"])
        ranges = {
            anchor_id: max(
                0.0,
                distance_mm - ANCHOR_DISTANCE_OFFSETS_MM.get(anchor_id, 0.0),
            )
            for anchor_id, distance_mm in raw_ranges.items()
        }
        distances = {
            key: ranges[item] for item, key in anchor_to_key.items()
        }
        try:
            raw_x, raw_y, raw_z = calculate_position_3d(distances)
            raw_position = {"x": raw_x, "y": raw_y, "z": raw_z}
            simulation_mode = HARDWARE_MODE
            true_position = None
            averages, spread = average_position(belt_id, raw_x, raw_y, raw_z)
            position = {"x": averages[0], "y": averages[1], "z": averages[2]}
            position_error = None
            tracking_difference = None
            with get_db() as conn:
                belt = get_belt(conn, belt_id)
                if belt is None:
                    raise ValueError("belt not found")
                zones = get_danger_zones(conn)
                insert_distance_log(conn, belt_id, distances)
                history_created = save_completed_position(
                    conn, belt_id, sequence_id, entry["timestamp"], position, zones
                )
                insert_position_error_log(
                    conn, belt_id, sequence_id, raw_position, simulation_mode,
                    position, true_position, position_error,
                    tracking_difference, spread,
                )
                belt = get_belt(conn, belt_id)
                assessment = evaluate_belt(belt, zones)
            results[belt_id] = {
                "status": "calculated",
                "belt_id": belt_id,
                "sequence_id": sequence_id,
                "simulation_mode": simulation_mode,
                "raw_distances_mm": raw_ranges,
                "distances_mm": ranges,
                "raw_position_mm": raw_position,
                "position_mm": position,
                "true_position_mm": true_position,
                "position_error_mm": position_error,
                "tracking_difference_mm": tracking_difference,
                "position_spread_mm": spread,
                "assessment": assessment,
                "history_created": history_created,
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


def requested_limit(default=HISTORY_DEFAULT_LIMIT):
    try:
        value = int(request.args.get("limit", default))
    except (TypeError, ValueError):
        return default
    return max(1, min(HISTORY_MAX_LIMIT, value))


def requested_time_range():
    values = {}
    for parameter in ("start", "end"):
        raw_value = request.args.get(parameter, "").strip()
        if not raw_value:
            values[parameter] = None
            continue
        try:
            values[parameter] = datetime.fromisoformat(raw_value).isoformat(
                timespec="seconds"
            )
        except ValueError:
            return None, f"{parameter} must be an ISO date-time"
    if values["start"] and values["end"] and values["start"] > values["end"]:
        return None, "start must not be later than end"
    return values, None


@app.get("/api/history/<belt_id>")
def position_history_api(belt_id):
    if belt_id not in REGISTERED_BELT_IDS:
        return jsonify({"status": "error", "error": "belt_id not registered"}), 404
    time_range, error = requested_time_range()
    if error:
        return jsonify({"status": "error", "error": error}), 400
    with get_db() as conn:
        if get_belt(conn, belt_id) is None:
            return jsonify({"status": "error", "error": "belt not found"}), 404
        records = get_position_history(
            conn, belt_id, requested_limit(HISTORY_MAX_LIMIT),
            time_range["start"], time_range["end"],
        )
    return jsonify({"belt_id": belt_id, "count": len(records), "records": records})


@app.get("/api/geofence-events")
def geofence_events_api():
    belt_id = request.args.get("belt_id", "").strip() or None
    if belt_id and belt_id not in REGISTERED_BELT_IDS:
        return jsonify({"status": "error", "error": "belt_id not registered"}), 404
    time_range, error = requested_time_range()
    if error:
        return jsonify({"status": "error", "error": error}), 400
    with get_db() as conn:
        events = get_geofence_events(
            conn, requested_limit(HISTORY_MAX_LIMIT), belt_id,
            time_range["start"], time_range["end"],
        )
    return jsonify({"count": len(events), "events": events})


@app.patch("/api/geofence-events/<int:event_id>")
def acknowledge_geofence_event(event_id):
    data = request.get_json(force=True)
    if data.get("status") != "ACKNOWLEDGED" or set(data) != {"status"}:
        return jsonify({
            "status": "error", "error": "status must be ACKNOWLEDGED"
        }), 400
    with get_db() as conn:
        event = conn.execute(
            "SELECT * FROM geofence_events WHERE id=?", (event_id,)
        ).fetchone()
        if event is None:
            return jsonify({"status": "error", "error": "event not found"}), 404
        if event["event_type"] != "ENTER":
            return jsonify({
                "status": "error", "error": "only ENTER events can be acknowledged"
            }), 400
        if event["status"] == "RESOLVED":
            return jsonify({
                "status": "error", "error": "event is already resolved"
            }), 409
        acknowledged_at = now_text()
        conn.execute(
            """
            UPDATE geofence_events
            SET status='ACKNOWLEDGED',acknowledged_at=? WHERE id=?
            """,
            (acknowledged_at, event_id),
        )
        updated = dict(conn.execute(
            """
            SELECT id,belt_id,sequence_id,event_type,zone_name,timestamp,x,y,z,
                   created_at,exited_at,duration_seconds,status,acknowledged_at,
                   related_enter_id
            FROM geofence_events WHERE id=?
            """,
            (event_id,),
        ).fetchone())
        if updated["duration_seconds"] is None and updated["exited_at"] is None:
            updated["duration_seconds"] = max(
                0,
                int(
                    (
                        datetime.now() - datetime.fromisoformat(updated["created_at"])
                    ).total_seconds()
                ),
            )
        duration = updated["duration_seconds"] or 0
        updated["alert_level"] = (
            "critical" if duration > GEOFENCE_CRITICAL_SECONDS
            else "warning" if duration > GEOFENCE_WARNING_SECONDS
            else "notice"
        )
    return jsonify({"status": "updated", "event": updated})


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
      color:#8b1e1b; padding:5px; font-size:12px; z-index:1; }
    .zone.medium { background:#e5a11b33; border-color:var(--warn); }
    .belt-dot { position:absolute; width:34px; height:34px; border-radius:50%;
      transform:translate(-50%,-50%); display:grid; place-items:center; color:white;
      background:var(--accent); font-weight:bold; border:3px solid white;
      box-shadow:0 2px 8px #0005; z-index:3; }
    .belt-dot.notice { background:var(--warn); }
    .belt-dot small { position:absolute; top:34px; color:var(--ink); white-space:nowrap; }
    .side { display:grid; gap:18px; align-content:start; }
    table { border-collapse:collapse; width:100%; font-size:13px; }
    th,td { padding:10px; border-bottom:1px solid var(--line); text-align:left;
      vertical-align:top; }
    th { background:#f5f7fa; } .pill { display:inline-block; padding:4px 8px;
      border-radius:999px; background:#e8f5ee; color:#146752; border:0; }
    .pill.warn { background:#fff1d6; color:#925600; }
    .pill.danger { background:#fde2e1; color:#a52724; }
    .pill.info { background:#e5eef9; color:#285f94; }
    button.pill { cursor:pointer; font:inherit; }
    .alerts { padding:12px; display:grid; gap:8px; }
    .alert { padding:10px; border-left:4px solid var(--warn); background:#fff7e7; }
    .trail-layer { position:absolute; inset:0; width:100%; height:100%;
      pointer-events:none; z-index:2; overflow:visible; }
    .events-table { max-height:310px; overflow:auto; }
    .playback-query,.playback-controls { padding:12px 16px; display:flex;
      flex-wrap:wrap; gap:10px; align-items:end; border-bottom:1px solid var(--line); }
    .playback-controls { align-items:center; background:#f7f9fc; }
    .field { display:grid; gap:4px; font-size:12px; color:var(--muted); }
    select,input,button.command { min-height:36px; border:1px solid #aeb9c8;
      background:#fff; color:var(--ink); padding:6px 9px; font:inherit; border-radius:6px; }
    button.command { cursor:pointer; font-weight:600; }
    button.command.primary { background:var(--accent); border-color:var(--accent);
      color:#fff; }
    button.command:disabled { cursor:not-allowed; opacity:.45; }
    .playback-progress { flex:1 1 180px; min-width:140px; }
    .playback-status { padding:10px 16px; min-height:42px; color:var(--muted);
      border-bottom:1px solid var(--line); font-size:13px; }
    .event-marker { position:absolute; transform:translate(-50%,-50%); z-index:4;
      width:18px; height:18px; border-radius:50%; background:var(--danger);
      border:3px solid #fff; box-shadow:0 0 0 3px #c73e3a55; }
    .event-marker span { position:absolute; left:14px; top:-12px; padding:4px 6px;
      background:#fff; border:1px solid var(--danger); color:#8b1e1b;
      white-space:nowrap; font-size:12px; }
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
      <div class="playback-query">
        <label class="field">腰帶<select id="playbackBelt"></select></label>
        <label class="field">查詢範圍<select id="playbackRange">
          <option value="5">最近 5 分鐘</option>
          <option value="30">最近 30 分鐘</option>
          <option value="60">最近 1 小時</option>
          <option value="all" selected>最近 200 筆</option>
          <option value="custom">自訂時間</option>
        </select></label>
        <label class="field">開始時間<input id="playbackStart" type="datetime-local" disabled></label>
        <label class="field">結束時間<input id="playbackEnd" type="datetime-local" disabled></label>
        <button class="command primary" id="queryPlayback">查詢軌跡</button>
      </div>
      <div class="playback-controls">
        <button class="command" id="playPlayback" disabled>播放</button>
        <button class="command" id="pausePlayback" disabled>暫停</button>
        <button class="command" id="restartPlayback" disabled>重播</button>
        <label class="field">速度<select id="playbackSpeed">
          <option value="0.5">0.5 倍</option><option value="1" selected>1 倍</option>
          <option value="2">2 倍</option><option value="4">4 倍</option>
        </select></label>
        <input class="playback-progress" id="playbackProgress" type="range"
          min="0" max="0" value="0" disabled aria-label="回放進度">
        <button class="command" id="liveMode" disabled>返回即時</button>
      </div>
      <div class="playback-status" id="playbackStatus">目前顯示即時定位</div>
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
      <section><div class="section-head"><h2>電子圍欄事件紀錄</h2></div>
        <div class="events-table"><table><thead><tr>
          <th>時間</th><th>腰帶</th><th>事件</th><th>區域</th><th>停留</th>
          <th>警示</th><th>狀態</th><th>處理</th>
        </tr></thead><tbody id="eventRows"></tbody></table></div>
      </section>
      <section><div class="section-head"><h2>XYZ 危險區域</h2></div>
        <table><thead><tr>
          <th>區域</th><th>X 範圍</th><th>Y 範圍</th><th>Z 範圍</th><th>風險</th>
        </tr></thead><tbody id="zoneRows"></tbody></table>
      </section>
    </div>
  </main>
  <script>
    const map = document.getElementById("map");
    const beltRows = document.getElementById("beltRows");
    const alerts = document.getElementById("alerts");
    const eventRows = document.getElementById("eventRows");
    const zoneRows = document.getElementById("zoneRows");
    const clock = document.getElementById("clock");
    const playbackBelt = document.getElementById("playbackBelt");
    const playbackRange = document.getElementById("playbackRange");
    const playbackStart = document.getElementById("playbackStart");
    const playbackEnd = document.getElementById("playbackEnd");
    const playbackProgress = document.getElementById("playbackProgress");
    const playbackStatus = document.getElementById("playbackStatus");
    const playPlayback = document.getElementById("playPlayback");
    const pausePlayback = document.getElementById("pausePlayback");
    const restartPlayback = document.getElementById("restartPlayback");
    const liveMode = document.getElementById("liveMode");
    let latestBelts = [];
    let latestDashboardData = null;
    let playbackRecords = [];
    let playbackEvents = [];
    let playbackIndex = 0;
    let playbackTimer = null;
    let playbackActive = false;

    function assessmentFor(data, beltId) {
      return data.assessments.find(item => item.belt_id === beltId);
    }
    function zoneForPoint(data, point) {
      return data.danger_zones.find(zone => zone.x1 <= point.x && point.x <= zone.x2
        && zone.y1 <= point.y && point.y <= zone.y2
        && zone.z1 <= point.z && point.z <= zone.z2);
    }
    function drawMap(data, histories=data.histories, positions={}, activeEvent=null) {
      map.innerHTML = "";
      data.danger_zones.forEach(zone => {
        const node = document.createElement("div");
        node.className = `zone ${zone.risk === "medium" ? "medium" : ""}`;
        node.style.left = `${zone.x1 / 3000 * 100}%`;
        node.style.top = `${zone.y1 / 3000 * 100}%`;
        node.style.width = `${(zone.x2-zone.x1) / 3000 * 100}%`;
        node.style.height = `${(zone.y2-zone.y1) / 3000 * 100}%`;
        node.textContent = zone.name;
        map.appendChild(node);
      });
      data.belts.forEach(belt => {
        const position = positions[belt.belt_id] || belt;
        const zone = zoneForPoint(data, position);
        const node = document.createElement("div");
        node.className = `belt-dot ${zone ? "notice" : ""}`;
        node.style.left = `${position.x / 3000 * 100}%`;
        node.style.top = `${position.y / 3000 * 100}%`;
        node.innerHTML = `${belt.belt_id.slice(-1)}<small>${belt.belt_id}</small>`;
        map.appendChild(node);
      });
      if (activeEvent) {
        const marker = document.createElement("div");
        marker.className = "event-marker";
        marker.style.left = `${activeEvent.x / 3000 * 100}%`;
        marker.style.top = `${activeEvent.y / 3000 * 100}%`;
        marker.innerHTML = `<span>${activeEvent.event_type}｜${activeEvent.zone_name}</span>`;
        map.appendChild(marker);
      }
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
      const overtime = data.geofence_events.filter(item =>
        item.event_type === "ENTER" && !item.exited_at
        && item.alert_level === "critical");
      const locationAlerts = visible.map(item =>
        `<div class="alert"><strong>${item.time}｜${item.belt_id}</strong><br>
        ${item.message}<br><small>${item.action}</small></div>`);
      const overtimeAlerts = overtime.map(item =>
        `<div class="alert"><strong>${item.belt_id}｜危險區停留超時</strong><br>
        已在${item.zone_name}停留 ${formatDuration(item.duration_seconds)}<br>
        <small>請立即確認人員安全狀況</small></div>`);
      const allAlerts = [...overtimeAlerts, ...locationAlerts];
      alerts.innerHTML = allAlerts.length ? allAlerts.join("")
        : `<div class="alert">目前沒有腰帶進入危險區域。</div>`;
    }
    function drawZoneRows(data) {
      zoneRows.innerHTML = data.danger_zones.map(zone => `<tr>
        <td><strong>${zone.name}</strong></td>
        <td>${zone.x1.toFixed(0)}–${zone.x2.toFixed(0)} mm</td>
        <td>${zone.y1.toFixed(0)}–${zone.y2.toFixed(0)} mm</td>
        <td>${zone.z1.toFixed(0)}–${zone.z2.toFixed(0)} mm</td>
        <td><span class="pill ${zone.risk === "high" ? "warn" : ""}">
          ${zone.risk}</span></td></tr>`).join("");
    }
    function drawEventRows(data) {
      eventRows.innerHTML = data.geofence_events.length
        ? data.geofence_events.map(event => `<tr>
          <td>${new Date(event.created_at).toLocaleTimeString("zh-TW")}</td>
          <td><strong>${event.belt_id}</strong></td>
          <td><span class="pill ${event.event_type === "ENTER" ? "warn" : ""}">
            ${event.event_type === "ENTER" ? "進入" : "離開"}</span></td>
          <td>${event.zone_name}</td>
          <td>${formatDuration(event.duration_seconds)}</td>
          <td><span class="pill ${alertClass(event.alert_level)}">
            ${alertLabel(event.alert_level)}</span></td>
          <td><span class="pill ${event.status === "ACKNOWLEDGED" ? "info" : ""}">
            ${statusLabel(event.status)}</span></td>
          <td>${event.event_type === "ENTER" && event.status === "UNHANDLED"
            ? `<button class="command" data-event-id="${event.id}">確認</button>` : "—"}</td>
        </tr>`).join("")
        : `<tr><td colspan="8">目前沒有電子圍欄進出紀錄。</td></tr>`;
    }
    function formatDuration(seconds) {
      if (seconds === null || seconds === undefined) return "—";
      const minutes = Math.floor(seconds / 60);
      const remaining = seconds % 60;
      return minutes ? `${minutes} 分 ${remaining} 秒` : `${remaining} 秒`;
    }
    function alertLabel(level) {
      return {normal:"正常", notice:"注意", warning:"警告", critical:"嚴重"}[level] || "—";
    }
    function alertClass(level) {
      return level === "critical" ? "danger" : level === "warning" ? "warn" : "";
    }
    function statusLabel(status) {
      return {UNHANDLED:"未處理", ACKNOWLEDGED:"已確認", RESOLVED:"已解除"}[status] || status;
    }
    async function acknowledgeEvent(eventId) {
      const response = await fetch(`/api/geofence-events/${eventId}`, {
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({status:"ACKNOWLEDGED"}),
      });
      if (!response.ok) {
        const data = await response.json();
        playbackStatus.textContent = data.error || "事件確認失敗";
      }
      await refresh();
    }
    function localDateTimeValue(date) {
      const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
      return local.toISOString().slice(0, 16);
    }
    function updateTimeInputs() {
      const custom = playbackRange.value === "custom";
      playbackStart.disabled = !custom;
      playbackEnd.disabled = !custom;
      if (custom && !playbackEnd.value) {
        const end = new Date();
        playbackEnd.value = localDateTimeValue(end);
        playbackStart.value = localDateTimeValue(new Date(end.getTime() - 30 * 60000));
      }
    }
    function pauseHistoryPlayback() {
      if (playbackTimer) clearInterval(playbackTimer);
      playbackTimer = null;
    }
    function playbackQueryParameters() {
      const parameters = new URLSearchParams({limit:"200"});
      if (playbackRange.value === "custom") {
        if (playbackStart.value) parameters.set("start", playbackStart.value);
        if (playbackEnd.value) parameters.set("end", playbackEnd.value);
      } else if (playbackRange.value !== "all") {
        const end = new Date();
        const start = new Date(end.getTime() - Number(playbackRange.value) * 60000);
        parameters.set("start", localDateTimeValue(start));
        parameters.set("end", localDateTimeValue(end));
      }
      return parameters;
    }
    function renderPlayback(index) {
      if (!latestDashboardData || !playbackRecords.length) return;
      playbackIndex = Math.max(0, Math.min(playbackRecords.length - 1, index));
      const point = playbackRecords[playbackIndex];
      const visibleEvents = playbackEvents.filter(event =>
        new Date(event.created_at) <= new Date(point.created_at));
      const currentEvent = playbackEvents.find(event =>
        event.sequence_id === point.sequence_id) || null;
      const histories = {[playbackBelt.value]: playbackRecords.slice(0, playbackIndex + 1)};
      const positions = {[playbackBelt.value]: point};
      drawMap(latestDashboardData, histories, positions, currentEvent);
      drawEventRows({geofence_events:[...visibleEvents].reverse()});
      playbackProgress.value = playbackIndex;
      const eventText = currentEvent
        ? `｜${currentEvent.event_type === "ENTER" ? "進入" : "離開"} ${currentEvent.zone_name}` : "";
      playbackStatus.textContent = `${playbackIndex + 1} / ${playbackRecords.length}｜`
        + `${new Date(point.created_at).toLocaleString("zh-TW")}｜`
        + `X ${point.x.toFixed(1)}、Y ${point.y.toFixed(1)}、Z ${point.z.toFixed(1)} mm`
        + eventText;
    }
    async function queryHistoryPlayback() {
      pauseHistoryPlayback();
      const beltId = playbackBelt.value;
      const parameters = playbackQueryParameters();
      const eventParameters = new URLSearchParams(parameters);
      eventParameters.set("belt_id", beltId);
      playbackStatus.textContent = "正在查詢歷史資料…";
      try {
        const [historyResponse, eventResponse] = await Promise.all([
          fetch(`/api/history/${encodeURIComponent(beltId)}?${parameters}`),
          fetch(`/api/geofence-events?${eventParameters}`),
        ]);
        const historyData = await historyResponse.json();
        const eventData = await eventResponse.json();
        if (!historyResponse.ok) throw new Error(historyData.error || "歷史資料查詢失敗");
        if (!eventResponse.ok) throw new Error(eventData.error || "事件查詢失敗");
        playbackRecords = historyData.records;
        playbackEvents = eventData.events.sort((a, b) =>
          new Date(a.created_at) - new Date(b.created_at));
        playbackActive = playbackRecords.length > 0;
        playbackProgress.max = Math.max(0, playbackRecords.length - 1);
        playbackProgress.disabled = !playbackActive;
        playPlayback.disabled = !playbackActive;
        pausePlayback.disabled = !playbackActive;
        restartPlayback.disabled = !playbackActive;
        liveMode.disabled = !playbackActive;
        if (!playbackActive) {
          playbackStatus.textContent = "此查詢範圍沒有定位歷史資料";
          return;
        }
        renderPlayback(0);
      } catch (error) {
        playbackActive = false;
        playbackStatus.textContent = error.message;
      }
    }
    function startHistoryPlayback() {
      if (!playbackActive || playbackTimer) return;
      if (playbackIndex >= playbackRecords.length - 1) renderPlayback(0);
      const speed = Number(document.getElementById("playbackSpeed").value);
      playbackTimer = setInterval(() => {
        if (playbackIndex >= playbackRecords.length - 1) {
          pauseHistoryPlayback();
          return;
        }
        renderPlayback(playbackIndex + 1);
      }, 800 / speed);
    }
    function returnToLiveMode() {
      pauseHistoryPlayback();
      playbackActive = false;
      playbackRecords = [];
      playbackEvents = [];
      playbackProgress.value = 0;
      playbackProgress.disabled = true;
      playPlayback.disabled = true;
      pausePlayback.disabled = true;
      restartPlayback.disabled = true;
      liveMode.disabled = true;
      playbackStatus.textContent = "目前顯示即時定位";
      if (latestDashboardData) {
        drawMap(latestDashboardData);
        drawEventRows(latestDashboardData);
      }
    }
    async function refresh() {
      const response = await fetch("/api/status");
      const data = await response.json();
      latestDashboardData = data;
      latestBelts = data.belts;
      const selectedBelt = playbackBelt.value;
      playbackBelt.innerHTML = data.belts.map(belt =>
        `<option value="${belt.belt_id}">${belt.belt_id}</option>`).join("");
      if (data.belts.some(belt => belt.belt_id === selectedBelt)) {
        playbackBelt.value = selectedBelt;
      }
      clock.textContent = `更新時間 ${new Date(data.updated_at).toLocaleTimeString("zh-TW")}`;
      if (!playbackActive) drawMap(data);
      drawRows(data); drawAlerts(data);
      if (!playbackActive) drawEventRows(data);
      drawZoneRows(data);
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
    eventRows.addEventListener("click", event => {
      const button = event.target.closest("button[data-event-id]");
      if (button) acknowledgeEvent(Number(button.dataset.eventId));
    });
    playbackRange.addEventListener("change", updateTimeInputs);
    document.getElementById("queryPlayback").addEventListener("click", queryHistoryPlayback);
    playPlayback.addEventListener("click", startHistoryPlayback);
    pausePlayback.addEventListener("click", pauseHistoryPlayback);
    restartPlayback.addEventListener("click", () => { pauseHistoryPlayback(); renderPlayback(0); });
    liveMode.addEventListener("click", returnToLiveMode);
    playbackProgress.addEventListener("input", () => {
      pauseHistoryPlayback(); renderPlayback(Number(playbackProgress.value));
    });
    updateTimeInputs();
    refresh(); setInterval(refresh,1800);
  </script>
</body></html>
"""


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
