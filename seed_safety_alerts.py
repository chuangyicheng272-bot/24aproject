"""建立或更新 SafeGuard 即時危險警報示範資料。"""

import json
from datetime import datetime, timedelta

from app import (
    app,
    build_safety_line_message,
    get_db,
    init_db,
    record_safety_alert,
    save_line_alert_delivery,
)


SAMPLES = [
    {
        "source_system": "YOLO",
        "device_id": "CAM-01",
        "location": "倉庫 A 區",
        "alert_type": "fall_detection",
        "message": "偵測到人員跌倒",
        "detail": "人員 W-001・辨識信心度 96%",
        "severity": "emergency",
    },
    {
        "source_system": "UWB",
        "device_id": "TAG-007",
        "location": "A 棟 1 樓禁入區",
        "alert_type": "geofence_intrusion",
        "message": "人員進入危險電子圍籬",
        "detail": "座標 X 12.5 / Y 8.2 / Z 1.4・電量 81%",
        "severity": "emergency",
    },
    {
        "source_system": "YOLO",
        "device_id": "CAM-02",
        "location": "工地入口",
        "alert_type": "ppe_violation",
        "message": "偵測到人員未配戴安全帽",
        "detail": "人員 W-003・辨識信心度 93%",
        "severity": "serious",
    },
    {
        "source_system": "YOLO",
        "device_id": "CAM-03",
        "location": "卸料區",
        "alert_type": "vehicle_proximity",
        "message": "人員與移動機具距離過近",
        "detail": "人員 W-008・與堆高機距離 0.8 公尺",
        "severity": "serious",
    },
    {
        "source_system": "UWB",
        "device_id": "TAG-011",
        "location": "高處作業區",
        "alert_type": "safe_zone_exit",
        "message": "人員離開安全活動範圍",
        "detail": "最後座標 X 26.1 / Y 14.7 / Z 8.3・電量 74%",
        "severity": "attention",
    },
    {
        "source_system": "UWB",
        "device_id": "TAG-014",
        "location": "B 棟 2 樓",
        "alert_type": "immobility",
        "message": "人員長時間未移動",
        "detail": "已持續 5 分鐘未偵測到位移・電量 67%",
        "severity": "serious",
    },
]


def seed_samples():
    # 示範資料不應真的推送 LINE；使用者可在介面確認後自行按重新傳送。
    app.config.update(LINE_CHANNEL_ACCESS_TOKEN="", LINE_TARGET_USER_ID="")
    init_db()
    now = datetime.now().astimezone()
    sample_ids = []
    for index, sample in enumerate(SAMPLES):
        occurred_at = (now - timedelta(minutes=index * 2)).isoformat(timespec="seconds")
        existing = get_db().execute(
            """
            SELECT id FROM safety_alerts
            WHERE device_id=? AND alert_type=? AND metadata LIKE '%"demo": true%'
            ORDER BY id DESC LIMIT 1
            """,
            (sample["device_id"], sample["alert_type"]),
        ).fetchone()
        if existing:
            alert_id = existing["id"]
            get_db().execute(
                """
                UPDATE safety_alerts
                SET source_system=?,location=?,message=?,detail=?,severity=?,
                    status='open',occurrences=1,metadata=?,occurred_at=?,resolved_at='',
                    resolved_by='',resolution_note='',acknowledged_at='',
                    acknowledged_by='',acknowledged_user_id=''
                WHERE id=?
                """,
                (
                    sample["source_system"], sample["location"], sample["message"],
                    sample["detail"], sample["severity"],
                    json.dumps({"demo": True}, ensure_ascii=False), occurred_at,
                    alert_id,
                ),
            )
            get_db().commit()
            alert = get_db().execute(
                """
                SELECT id,source_system,device_id,location,alert_type,message,detail,
                       severity,status,occurred_at
                FROM safety_alerts WHERE id=?
                """,
                (alert_id,),
            ).fetchone()
            save_line_alert_delivery(
                alert_id,
                "",
                build_safety_line_message(alert),
                "not_configured",
                failure_reason="示範資料尚未傳送 LINE",
            )
        else:
            alert_id = record_safety_alert(
                sample["source_system"], sample["device_id"], sample["location"],
                sample["alert_type"], sample["message"], sample["detail"],
                sample["severity"], metadata={"demo": True}, occurred_at=occurred_at,
            )
        sample_ids.append(alert_id)
    return sample_ids


if __name__ == "__main__":
    with app.app_context():
        created_ids = seed_samples()
    print("Safety alert demo IDs:", ", ".join(map(str, created_ids)))
