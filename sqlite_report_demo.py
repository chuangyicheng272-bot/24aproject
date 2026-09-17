"""SafeGuard SQLite 報告展示工具。

查看資料庫：
    python sqlite_report_demo.py

新增一筆測試資料並立即查回：
    python sqlite_report_demo.py --insert
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


DATABASE_PATH = Path(__file__).with_name("safeguard.db")
TABLES = (
    "users",
    "people",
    "monitoring_devices",
    "areas",
    "base_stations",
    "communication_events",
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="展示 SafeGuard SQLite 資料處理過程")
    parser.add_argument("--insert", action="store_true", help="新增一筆報告測試資料")
    args = parser.parse_args()

    print("[步驟 1/4] 連接 SQLite 資料庫")
    print(f"  檔案：{DATABASE_PATH}")
    print(f"  SQLite 版本：{sqlite3.sqlite_version}")

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        print("\n[步驟 2/4] 查詢資料表筆數")
        for table_name in TABLES:
            count = connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            print(f"  {table_name:<22} {count:>4} 筆")

        if args.insert:
            print("\n[步驟 3/4] 執行 INSERT 並 COMMIT")
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            payload = json.dumps(
                {
                    "purpose": "SQLite 報告展示",
                    "steps": ["連接資料庫", "INSERT", "COMMIT", "SELECT"],
                },
                ensure_ascii=False,
            )
            sql = """
                INSERT INTO communication_events
                  (source,device_id,event_type,payload,received_at)
                VALUES (?,?,?,?,?)
            """
            cursor = connection.execute(
                sql,
                (
                    "report_demo",
                    "REPORT-SQLITE-001",
                    "sqlite_insert_demo",
                    payload,
                    timestamp,
                ),
            )
            connection.commit()
            print(f"  新增成功，資料列 ID：{cursor.lastrowid}")

            print("\n[步驟 4/4] 用 SELECT 查回剛才新增的資料")
            row = connection.execute(
                """
                SELECT id,source,device_id,event_type,payload,received_at
                FROM communication_events WHERE id=?
                """,
                (cursor.lastrowid,),
            ).fetchone()
            print(json.dumps(dict(row), ensure_ascii=False, indent=2))
        else:
            print("\n[步驟 3/4] 唯讀模式，未執行 INSERT")
            print("  如要新增測試資料：python sqlite_report_demo.py --insert")
            print("\n[步驟 4/4] 查詢最近一筆通訊事件")
            row = connection.execute(
                """
                SELECT id,source,device_id,event_type,payload,received_at
                FROM communication_events ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            print(json.dumps(dict(row), ensure_ascii=False, indent=2) if row else "  尚無資料")
    finally:
        connection.close()
        print("\n完成：SQLite 連線已關閉。")


if __name__ == "__main__":
    main()
