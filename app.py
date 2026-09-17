import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import smtplib
import ssl
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, quote
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps

from flask import Flask, Response, g, has_request_context, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config.update(
    SECRET_KEY="change-this-secret-key",
    DATABASE=os.path.join(app.root_path, "safeguard.db"),
    UPLOAD_FOLDER=os.path.join(app.root_path, "uploads"),
    MAX_CONTENT_LENGTH=200 * 1024 * 1024,
    IOT_API_KEY=os.getenv("IOT_API_KEY", ""),
    CORS_ORIGIN=os.getenv("CORS_ORIGIN", "*"),
    MQTT_ENABLED=os.getenv("MQTT_ENABLED", "false").lower() in {"1", "true", "yes"},
    MQTT_HOST=os.getenv("MQTT_HOST", "127.0.0.1"),
    MQTT_PORT=int(os.getenv("MQTT_PORT", "1883")),
    MQTT_TOPIC=os.getenv("MQTT_TOPIC", "safeguard/uwb"),
    MQTT_USERNAME=os.getenv("MQTT_USERNAME", ""),
    MQTT_PASSWORD=os.getenv("MQTT_PASSWORD", ""),
    LINE_CHANNEL_SECRET=os.getenv("LINE_CHANNEL_SECRET", "").strip(),
    LINE_CHANNEL_ACCESS_TOKEN=os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip(),
    LINE_TARGET_USER_ID=os.getenv("LINE_TARGET_USER_ID", "").strip(),
    LINE_ALERT_COOLDOWN_SECONDS=max(0, int(os.getenv("LINE_ALERT_COOLDOWN_SECONDS", "60"))),
    SAFETY_ALERT_COOLDOWN_SECONDS=max(0, int(os.getenv("SAFETY_ALERT_COOLDOWN_SECONDS", "60"))),
    PUBLIC_BASE_URL=os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/"),
    SMTP_HOST=os.getenv("SMTP_HOST", "smtp.gmail.com"),
    SMTP_PORT=int(os.getenv("SMTP_PORT", "587")),
    SMTP_USERNAME=os.getenv("SMTP_USERNAME", ""),
    SMTP_APP_PASSWORD=os.getenv("SMTP_APP_PASSWORD", ""),
    SMTP_FROM_EMAIL=os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_USERNAME", "")),
    PASSWORD_RESET_TTL_MINUTES=max(1, int(os.getenv("PASSWORD_RESET_TTL_MINUTES", "10"))),
    PASSWORD_RESET_COOLDOWN_SECONDS=max(0, int(os.getenv("PASSWORD_RESET_COOLDOWN_SECONDS", "60"))),
)

VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "m4v", "ogg"}
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MQTT_CLIENT = None
MQTT_STARTED = False
LINE_ALERT_LAST_SENT = {}
LINE_ALERT_LOCK = threading.Lock()

# SQLite 展示頁只允許讀取以下資料表與欄位，避免將 users.password
# 等敏感內容顯示在瀏覽器，也不接受使用者自行輸入 SQL。
DATABASE_REPORT_TABLES = {
    "users": {
        "label": "系統帳戶",
        "columns": ["id", "account", "name", "phone", "email", "role", "active", "created_at", "last_active"],
        "order_by": "id DESC",
    },
    "people": {
        "label": "UWB 人員／標籤",
        "columns": [
            "id", "name", "employee_name", "area", "x", "y", "z",
            "helmet", "vest", "battery", "risk", "device_status", "last_seen",
        ],
        "order_by": "rowid DESC",
    },
    "monitoring_devices": {
        "label": "監控設備",
        "columns": ["id", "location", "status", "last_seen", "stream_url", "created_at"],
        "order_by": "rowid DESC",
    },
    "areas": {
        "label": "設定區域",
        "columns": ["id", "name", "created_at"],
        "order_by": "id DESC",
    },
    "base_stations": {
        "label": "UWB 基站",
        "columns": [
            "id", "name", "area_id", "x", "y", "z",
            "status", "last_seen", "source", "created_at",
        ],
        "order_by": "rowid DESC",
    },
    "communication_events": {
        "label": "通訊事件",
        "columns": ["id", "source", "device_id", "event_type", "payload", "received_at"],
        "order_by": "id DESC",
    },
    "safety_alerts": {
        "label": "即時危險警報",
        "columns": [
            "id", "source_system", "device_id", "location", "alert_type",
            "message", "detail", "severity", "status", "occurrences",
            "occurred_at", "acknowledged_at", "acknowledged_by",
            "acknowledged_user_id", "resolved_at", "resolved_by", "resolution_note",
        ],
        "order_by": "id DESC",
    },
    "line_alert_deliveries": {
        "label": "LINE 警報寄送紀錄",
        "columns": [
            "id", "alert_id", "status", "attempts", "failure_reason",
            "created_at", "sent_at", "updated_at",
        ],
        "order_by": "id DESC",
    },
}



def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def rows(sql, values=()):
    return [dict(row) for row in get_db().execute(sql, values).fetchall()]


def sqlite_database_overview(limit=5):
    """提供報告展示所需的唯讀 SQLite 結構、筆數與最新資料。"""
    db = get_db()
    tables = []
    for table_name, settings in DATABASE_REPORT_TABLES.items():
        columns = settings["columns"]
        count = db.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        schema_rows = db.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        schema = [
            {
                "name": row["name"],
                "type": row["type"] or "TEXT",
                "primary_key": bool(row["pk"]),
                "not_null": bool(row["notnull"]),
            }
            for row in schema_rows
            if row["name"] in columns
        ]
        select_columns = ", ".join(f'"{column}"' for column in columns)
        recent = rows(
            f'SELECT {select_columns} FROM "{table_name}" '
            f'ORDER BY {settings["order_by"]} LIMIT ?',
            (limit,),
        )
        tables.append(
            {
                "name": table_name,
                "label": settings["label"],
                "count": count,
                "schema": schema,
                "columns": columns,
                "recent": recent,
            }
        )

    database_path = app.config["DATABASE"]
    return {
        "engine": f"SQLite {sqlite3.sqlite_version}",
        "filename": os.path.basename(database_path),
        "path": database_path,
        "size_bytes": os.path.getsize(database_path) if os.path.exists(database_path) else 0,
        "foreign_keys": bool(db.execute("PRAGMA foreign_keys").fetchone()[0]),
        "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0],
        "tables": tables,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,),
    ).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or not user["active"]:
            session.clear()
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user()["role"] != "管理員":
            if request.path.startswith("/api/"):
                return message("只有管理員可以管理帳戶", 403)
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


def message(text, status=400):
    return jsonify(ok=False, message=text), status


PASSWORD_RESET_RESPONSE = "若帳號與電子郵件相符，密碼重設連結已寄出。"


def password_reset_token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_reset_token_row(token):
    if not token:
        return None
    token_row = get_db().execute(
        """
        SELECT password_reset_tokens.id, password_reset_tokens.user_id,
               password_reset_tokens.expires_at, password_reset_tokens.used_at,
               users.account, users.active
        FROM password_reset_tokens
        JOIN users ON users.id=password_reset_tokens.user_id
        WHERE password_reset_tokens.token_hash=?
        """,
        (password_reset_token_hash(token),),
    ).fetchone()
    if not token_row or token_row["used_at"] or not token_row["active"]:
        return None
    try:
        expires_at = datetime.fromisoformat(token_row["expires_at"])
    except (TypeError, ValueError):
        return None
    if expires_at <= datetime.now().astimezone():
        return None
    return token_row


def send_smtp_email(recipient, subject, body):
    username = app.config["SMTP_USERNAME"]
    app_password = re.sub(r"\s+", "", str(app.config["SMTP_APP_PASSWORD"]))
    sender = app.config["SMTP_FROM_EMAIL"]
    if not username or not app_password or not sender:
        raise RuntimeError("尚未設定 SMTP 郵件環境變數")

    email = EmailMessage()
    email["Subject"] = subject
    email["From"] = sender
    email["To"] = recipient
    email.set_content(body)
    with smtplib.SMTP(
        app.config["SMTP_HOST"], app.config["SMTP_PORT"], timeout=15
    ) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(username, app_password)
        smtp.send_message(email)


def send_password_reset_email(recipient, reset_url):
    ttl = app.config["PASSWORD_RESET_TTL_MINUTES"]
    send_smtp_email(
        recipient,
        "SafeGuard 密碼重設連結",
        "您好：\n\n"
        "系統收到 SafeGuard 帳戶的密碼重設要求。\n"
        f"請在 {ttl} 分鐘內開啟以下連結並設定新密碼：\n\n"
        f"{reset_url}\n\n"
        "此連結只能使用一次。若不是您提出要求，請忽略本信並通知管理員。\n",
    )


def email_failure_reason(error):
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return "SMTP 驗證失敗"
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "收件地址遭郵件伺服器拒絕"
    if isinstance(error, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError)):
        return "無法連線到郵件伺服器"
    if isinstance(error, RuntimeError):
        return "SMTP 環境變數尚未設定"
    return "郵件寄送失敗"


def create_email_delivery(user_id, recipient, notification_type, subject, retry_of_id=None):
    cursor = get_db().execute(
        """
        INSERT INTO email_deliveries
          (user_id,recipient,notification_type,subject,status,retry_of_id,created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            user_id,
            recipient,
            notification_type,
            subject,
            "pending",
            retry_of_id,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        ),
    )
    get_db().commit()
    return cursor.lastrowid


def finish_email_delivery(delivery_id, status, reason=""):
    sent_at = datetime.now().astimezone().isoformat(timespec="seconds") if status == "sent" else ""
    get_db().execute(
        """
        UPDATE email_deliveries
        SET status=?,failure_reason=?,sent_at=? WHERE id=?
        """,
        (status, reason, sent_at, delivery_id),
    )
    get_db().commit()


def mask_email_address(address):
    local, separator, domain = str(address or "").partition("@")
    if not separator:
        return address or "尚未設定"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}***@{domain}"


def deliver_password_reset(user, retry_of_id=None):
    now = datetime.now().astimezone()
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=app.config["PASSWORD_RESET_TTL_MINUTES"])
    get_db().execute(
        "UPDATE password_reset_tokens SET used_at=? WHERE user_id=? AND used_at=''",
        (now.isoformat(timespec="seconds"), user["id"]),
    )
    token_cursor = get_db().execute(
        """
        INSERT INTO password_reset_tokens (user_id,token_hash,expires_at,created_at)
        VALUES (?,?,?,?)
        """,
        (
            user["id"],
            password_reset_token_hash(token),
            expires_at.isoformat(timespec="seconds"),
            now.isoformat(timespec="seconds"),
        ),
    )
    get_db().commit()

    reset_url = f'{app.config["PUBLIC_BASE_URL"]}{url_for("reset_password_page", token=token)}'
    delivery_id = create_email_delivery(
        user["id"], user["email"], "password_reset",
        "SafeGuard 密碼重設連結", retry_of_id,
    )
    try:
        send_password_reset_email(user["email"], reset_url)
        finish_email_delivery(delivery_id, "sent")
        record_communication_event(
            "email", "password_reset_sent",
            {"delivery": "sent", "delivery_id": delivery_id}, str(user["id"]),
        )
        return True, reset_url, delivery_id, ""
    except Exception as exc:
        reason = email_failure_reason(exc)
        get_db().execute(
            "UPDATE password_reset_tokens SET used_at=? WHERE id=?",
            (datetime.now().astimezone().isoformat(timespec="seconds"), token_cursor.lastrowid),
        )
        get_db().commit()
        finish_email_delivery(delivery_id, "failed", reason)
        app.logger.warning("密碼重設信寄送失敗：%s", exc)
        record_communication_event(
            "email", "password_reset_delivery_failed",
            {"delivery": "failed", "delivery_id": delivery_id, "reason": reason},
            str(user["id"]),
        )
        record_system_error("Gmail SMTP", "密碼重設信寄送失敗", reason)
        return False, reset_url, delivery_id, reason


def deliver_test_email(recipient, user_id=None, retry_of_id=None):
    subject = "SafeGuard Email 郵寄服務測試"
    delivery_id = create_email_delivery(
        user_id, recipient, "test_email", subject, retry_of_id
    )
    body = (
        "您好：\n\n"
        "這是一封由 SafeGuard Email 郵寄服務送出的測試信。\n"
        "收到此信代表 SMTP 帳號、應用程式密碼與網路連線皆可正常使用。\n\n"
        f"測試時間：{datetime.now().astimezone().isoformat(timespec='seconds')}\n"
    )
    try:
        send_smtp_email(recipient, subject, body)
        finish_email_delivery(delivery_id, "sent")
        record_communication_event(
            "email", "test_email_sent",
            {"delivery": "sent", "delivery_id": delivery_id}, str(user_id or ""),
        )
        return True, delivery_id, ""
    except Exception as exc:
        reason = email_failure_reason(exc)
        finish_email_delivery(delivery_id, "failed", reason)
        app.logger.warning("Email 測試信寄送失敗：%s", exc)
        record_communication_event(
            "email", "test_email_delivery_failed",
            {"delivery": "failed", "delivery_id": delivery_id, "reason": reason},
            str(user_id or ""),
        )
        record_system_error("Gmail SMTP", "Email 測試信寄送失敗", reason)
        return False, delivery_id, reason


def parse_bool(value, default=True):
    if value is None or value == "":
        return int(default)
    return int(str(value).strip().lower() in {"1", "true", "yes", "y", "是", "已戴", "已穿", "有"})


def existing_columns(table):
    return {row["name"] for row in get_db().execute(f"PRAGMA table_info({table})")}


def init_db():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL, password TEXT NOT NULL, phone TEXT DEFAULT '',
          role TEXT NOT NULL DEFAULT '一般使用者', email TEXT DEFAULT '', unit TEXT DEFAULT '',
          active INTEGER DEFAULT 1, created_at TEXT NOT NULL, last_active TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS people (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, employee_name TEXT NOT NULL DEFAULT '',
          area TEXT NOT NULL DEFAULT '',
          x REAL NOT NULL, y REAL NOT NULL,
          z REAL NOT NULL DEFAULT 0, helmet INTEGER NOT NULL DEFAULT 1, vest INTEGER NOT NULL DEFAULT 1,
          battery INTEGER NOT NULL DEFAULT 100, risk TEXT NOT NULL DEFAULT '低風險',
          device_status TEXT NOT NULL DEFAULT '等待資料', last_seen TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS communication_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, device_id TEXT DEFAULT '', event_type TEXT NOT NULL,
          payload TEXT NOT NULL, received_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          token_hash TEXT UNIQUE NOT NULL,
          expires_at TEXT NOT NULL,
          used_at TEXT DEFAULT '',
          created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS email_deliveries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          recipient TEXT NOT NULL,
          notification_type TEXT NOT NULL,
          subject TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          failure_reason TEXT DEFAULT '',
          retry_of_id INTEGER,
          created_at TEXT NOT NULL,
          sent_at TEXT DEFAULT '',
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
          FOREIGN KEY(retry_of_id) REFERENCES email_deliveries(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_email_deliveries_status
          ON email_deliveries(status, id DESC);
        CREATE TABLE IF NOT EXISTS system_errors (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          service TEXT NOT NULL,
          message TEXT NOT NULL,
          detail TEXT DEFAULT '',
          severity TEXT NOT NULL DEFAULT 'warning',
          status TEXT NOT NULL DEFAULT 'open',
          occurrences INTEGER NOT NULL DEFAULT 1,
          occurred_at TEXT NOT NULL,
          resolved_at TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_system_errors_status
          ON system_errors(status, id DESC);
        CREATE TABLE IF NOT EXISTS safety_alerts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_system TEXT NOT NULL,
          device_id TEXT DEFAULT '',
          location TEXT DEFAULT '',
          alert_type TEXT NOT NULL,
          message TEXT NOT NULL,
          detail TEXT DEFAULT '',
          severity TEXT NOT NULL DEFAULT 'attention',
          status TEXT NOT NULL DEFAULT 'open',
          occurrences INTEGER NOT NULL DEFAULT 1,
          metadata TEXT DEFAULT '{}',
          occurred_at TEXT NOT NULL,
          acknowledged_at TEXT DEFAULT '',
          acknowledged_by TEXT DEFAULT '',
          acknowledged_user_id TEXT DEFAULT '',
          resolved_at TEXT DEFAULT '',
          resolved_by TEXT DEFAULT '',
          resolution_note TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_safety_alerts_status
          ON safety_alerts(status, id DESC);
        CREATE INDEX IF NOT EXISTS idx_safety_alerts_source
          ON safety_alerts(source_system, id DESC);
        CREATE TABLE IF NOT EXISTS line_alert_deliveries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          alert_id INTEGER NOT NULL UNIQUE,
          recipient TEXT NOT NULL DEFAULT '',
          message TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          http_status INTEGER,
          failure_reason TEXT DEFAULT '',
          created_at TEXT NOT NULL,
          sent_at TEXT DEFAULT '',
          updated_at TEXT NOT NULL,
          FOREIGN KEY(alert_id) REFERENCES safety_alerts(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_line_alert_deliveries_status
          ON line_alert_deliveries(status, id DESC);
        CREATE TABLE IF NOT EXISTS monitoring_devices (
          id TEXT PRIMARY KEY, location TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT '等待連線',
          last_seen TEXT DEFAULT '', stream_url TEXT DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS areas (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS base_stations (
          id TEXT PRIMARY KEY, name TEXT NOT NULL,
          area_id INTEGER NOT NULL,
          x REAL NOT NULL DEFAULT 0, y REAL NOT NULL DEFAULT 0, z REAL NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT '等待資料',
          last_seen TEXT DEFAULT '',
          source TEXT NOT NULL DEFAULT 'manual',
          created_at TEXT NOT NULL,
          FOREIGN KEY(area_id) REFERENCES areas(id)
        );
    """)
    if "phone" not in existing_columns("users"):
        db.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
    if "email" not in existing_columns("users"):
        db.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
    if "z" not in existing_columns("people"):
        db.execute("ALTER TABLE people ADD COLUMN z REAL NOT NULL DEFAULT 0")
    if "employee_name" not in existing_columns("people"):
        db.execute("ALTER TABLE people ADD COLUMN employee_name TEXT NOT NULL DEFAULT ''")
    if "area" not in existing_columns("people"):
        db.execute("ALTER TABLE people ADD COLUMN area TEXT NOT NULL DEFAULT ''")
    if "device_status" not in existing_columns("people"):
        db.execute("ALTER TABLE people ADD COLUMN device_status TEXT NOT NULL DEFAULT '等待資料'")
    if "last_seen" not in existing_columns("people"):
        db.execute("ALTER TABLE people ADD COLUMN last_seen TEXT DEFAULT ''")
    if "stream_url" not in existing_columns("monitoring_devices"):
        db.execute("ALTER TABLE monitoring_devices ADD COLUMN stream_url TEXT DEFAULT ''")
    if "status" not in existing_columns("base_stations"):
        db.execute("ALTER TABLE base_stations ADD COLUMN status TEXT NOT NULL DEFAULT '等待資料'")
    if "last_seen" not in existing_columns("base_stations"):
        db.execute("ALTER TABLE base_stations ADD COLUMN last_seen TEXT DEFAULT ''")
    if "source" not in existing_columns("base_stations"):
        db.execute("ALTER TABLE base_stations ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
    if "resolved_by" not in existing_columns("safety_alerts"):
        db.execute("ALTER TABLE safety_alerts ADD COLUMN resolved_by TEXT DEFAULT ''")
    if "resolution_note" not in existing_columns("safety_alerts"):
        db.execute("ALTER TABLE safety_alerts ADD COLUMN resolution_note TEXT DEFAULT ''")
    if "acknowledged_at" not in existing_columns("safety_alerts"):
        db.execute("ALTER TABLE safety_alerts ADD COLUMN acknowledged_at TEXT DEFAULT ''")
    if "acknowledged_by" not in existing_columns("safety_alerts"):
        db.execute("ALTER TABLE safety_alerts ADD COLUMN acknowledged_by TEXT DEFAULT ''")
    if "acknowledged_user_id" not in existing_columns("safety_alerts"):
        db.execute("ALTER TABLE safety_alerts ADD COLUMN acknowledged_user_id TEXT DEFAULT ''")
    if not db.execute("SELECT 1 FROM email_deliveries LIMIT 1").fetchone():
        db.execute(
            """
            INSERT INTO email_deliveries
              (user_id,recipient,notification_type,subject,status,failure_reason,created_at,sent_at)
            SELECT users.id, COALESCE(users.email,''), 'password_reset',
                   'SafeGuard 密碼重設連結',
                   CASE WHEN communication_events.event_type='password_reset_sent'
                        THEN 'sent' ELSE 'failed' END,
                   CASE WHEN communication_events.event_type='password_reset_sent'
                        THEN '' ELSE 'SMTP 寄送失敗' END,
                   communication_events.received_at,
                   CASE WHEN communication_events.event_type='password_reset_sent'
                        THEN communication_events.received_at ELSE '' END
            FROM communication_events
            LEFT JOIN users ON CAST(communication_events.device_id AS INTEGER)=users.id
            WHERE communication_events.source='email'
              AND communication_events.event_type IN
                  ('password_reset_sent','password_reset_delivery_failed')
            ORDER BY communication_events.id
            """
        )
    if not db.execute("SELECT 1 FROM system_errors LIMIT 1").fetchone():
        db.execute(
            """
            INSERT INTO system_errors
              (service,message,detail,severity,status,occurrences,occurred_at,resolved_at)
            SELECT 'Gmail SMTP',
                   CASE WHEN notification_type='test_email'
                        THEN 'Email 測試信寄送失敗'
                        ELSE '密碼重設信寄送失敗' END,
                   COALESCE(failure_reason,'SMTP 寄送失敗'),
                   'warning','open',1,created_at,''
            FROM email_deliveries
            WHERE status='failed'
            ORDER BY id
            """
        )
    if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        today = datetime.now().strftime("%Y-%m-%d")
        db.executemany(
            "INSERT INTO users (account,name,password,phone,role,created_at,last_active) VALUES (?,?,?,?,?,?,?)",
            [
                ("admin", "系統管理員", generate_password_hash("admin123"), "0912345678", "管理員", today, "剛剛"),
                ("wang", "王小明", generate_password_hash("wang123"), "0922333444", "一般使用者", "2017-10-11", "07-28"),
            ],
        )
    db.execute(
        "UPDATE people SET employee_name='未綁定' WHERE employee_name IS NULL OR trim(employee_name)=''"
    )
    legacy_stations = db.execute(
        "SELECT id,name,area,x,y,z FROM people WHERE id LIKE 'B-%'"
    ).fetchall()
    for station in legacy_stations:
        area_name = str(station["area"] or "未分類區域").strip() or "未分類區域"
        db.execute(
            "INSERT OR IGNORE INTO areas (name,created_at) VALUES (?,?)",
            (area_name, datetime.now().astimezone().isoformat(timespec="seconds")),
        )
        area_id = db.execute(
            "SELECT id FROM areas WHERE name=?",
            (area_name,),
        ).fetchone()["id"]
        db.execute(
            """
            INSERT OR IGNORE INTO base_stations (id,name,area_id,x,y,z,created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                station["id"], station["name"], area_id,
                station["x"], station["y"], station["z"],
                datetime.now().astimezone().isoformat(timespec="seconds"),
            ),
        )
    if legacy_stations:
        db.execute("DELETE FROM people WHERE id LIKE 'B-%'")
    db.commit()


@app.after_request
def add_api_cors_headers(response):
    if request.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = app.config["CORS_ORIGIN"]
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, X-Line-Signature"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


def check_iot_api_key():
    configured = app.config["IOT_API_KEY"]
    if not configured:
        return None
    supplied = request.headers.get("X-API-Key", "")
    if not supplied or not hmac.compare_digest(supplied, configured):
        return message("IOT API Key 不正確", 401)
    return None


def auto_risk(helmet, vest):
    if not helmet and not vest:
        return "中高風險"
    if not helmet or not vest:
        return "注意"
    return "低風險"


def record_communication_event(source, event_type, payload, device_id=""):
    get_db().execute(
        "INSERT INTO communication_events (source,device_id,event_type,payload,received_at) VALUES (?,?,?,?,?)",
        (source, device_id, event_type, json.dumps(payload, ensure_ascii=False), datetime.now().astimezone().isoformat(timespec="seconds")),
    )
    get_db().commit()


def record_system_error(service, message_text, detail="", severity="warning"):
    """保存可供管理員追蹤的系統錯誤，五分鐘內相同錯誤合併計數。"""
    service = str(service or "系統").strip()[:80]
    message_text = str(message_text or "未知錯誤").strip()[:180]
    detail = str(detail or "").strip()[:500]
    severity = severity if severity in {"warning", "critical"} else "warning"
    now = datetime.now().astimezone()
    latest = get_db().execute(
        """
        SELECT id,occurred_at FROM system_errors
        WHERE service=? AND message=? AND status='open'
        ORDER BY id DESC LIMIT 1
        """,
        (service, message_text),
    ).fetchone()
    if latest:
        try:
            elapsed = (now - datetime.fromisoformat(latest["occurred_at"])).total_seconds()
        except (TypeError, ValueError):
            elapsed = 301
        if elapsed <= 300:
            get_db().execute(
                """
                UPDATE system_errors
                SET detail=?,severity=?,occurrences=occurrences+1,occurred_at=?
                WHERE id=?
                """,
                (detail, severity, now.isoformat(timespec="seconds"), latest["id"]),
            )
            get_db().commit()
            return latest["id"]
    cursor = get_db().execute(
        """
        INSERT INTO system_errors
          (service,message,detail,severity,status,occurrences,occurred_at,resolved_at)
        VALUES (?,?,?,?, 'open',1,?, '')
        """,
        (service, message_text, detail, severity, now.isoformat(timespec="seconds")),
    )
    get_db().commit()
    return cursor.lastrowid


def normalize_safety_severity(value, default="attention"):
    text = str(value or "").strip().lower()
    if text in {"emergency", "critical", "緊急", "危急"}:
        return "emergency"
    if text in {"serious", "high", "danger", "嚴重", "高風險", "中高風險"}:
        return "serious"
    if text in {"attention", "warning", "medium", "注意", "警告"}:
        return "attention"
    return default


def record_safety_alert(
    source_system,
    device_id,
    location,
    alert_type,
    message_text,
    detail="",
    severity="attention",
    metadata=None,
    occurred_at=None,
):
    """寫入 YOLO／UWB 危險事件，短時間內的相同未處理事件會合併。"""
    source_system = str(source_system or "其他").strip().upper()[:40]
    device_id = str(device_id or "").strip()[:80]
    location = str(location or "未設定位置").strip()[:120]
    alert_type = str(alert_type or "danger_event").strip()[:80]
    message_text = str(message_text or "偵測到危險事件").strip()[:220]
    detail = str(detail or "").strip()[:500]
    severity = normalize_safety_severity(severity)
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
    timestamp = str(
        occurred_at or datetime.now().astimezone().isoformat(timespec="seconds")
    )
    latest = get_db().execute(
        """
        SELECT id,occurred_at FROM safety_alerts
        WHERE source_system=? AND device_id=? AND alert_type=? AND status='open'
        ORDER BY id DESC LIMIT 1
        """,
        (source_system, device_id, alert_type),
    ).fetchone()
    if latest:
        try:
            elapsed = abs(
                (
                    datetime.fromisoformat(timestamp)
                    - datetime.fromisoformat(latest["occurred_at"])
                ).total_seconds()
            )
        except (TypeError, ValueError):
            elapsed = app.config["SAFETY_ALERT_COOLDOWN_SECONDS"] + 1
        if elapsed <= app.config["SAFETY_ALERT_COOLDOWN_SECONDS"]:
            get_db().execute(
                """
                UPDATE safety_alerts
                SET location=?,message=?,detail=?,severity=?,metadata=?,
                    occurrences=occurrences+1,occurred_at=?
                WHERE id=?
                """,
                (
                    location, message_text, detail, severity, metadata_json,
                    timestamp, latest["id"],
                ),
            )
            get_db().commit()
            return latest["id"]
    cursor = get_db().execute(
        """
        INSERT INTO safety_alerts
          (source_system,device_id,location,alert_type,message,detail,severity,
           status,occurrences,metadata,occurred_at,resolved_at)
        VALUES (?,?,?,?,?,?,?,'open',1,?,?,'')
        """,
        (
            source_system, device_id, location, alert_type, message_text,
            detail, severity, metadata_json, timestamp,
        ),
    )
    get_db().commit()
    alert_id = cursor.lastrowid
    if source_system in {"YOLO", "UWB"}:
        # LINE 失敗不得影響危險警報寫入；派送函式會自行保存錯誤狀態。
        try:
            dispatch_safety_alert_to_line(alert_id)
        except Exception as exc:
            app.logger.warning("危險警報 #%s 的 LINE 派送流程失敗：%s", alert_id, exc)
    return alert_id


def record_uwb_safety_alert(data, normalized):
    boundary_status = str(
        data.get("boundary_status") or data.get("geofence_status") or ""
    ).strip().lower()
    outside = (
        data.get("inside_safe_zone") is False
        or boundary_status in {"outside", "intrusion", "danger", "越界", "禁區"}
    )
    explicit_alert = parse_bool(
        data.get("danger", data.get("alert", False)), default=False
    )
    risk = normalized["risk"]
    risk_is_explicit = "risk" in data and str(data.get("risk") or "").strip() != ""
    if (not risk_is_explicit or risk == "低風險") and not outside and not explicit_alert:
        return None
    severity = normalize_safety_severity(
        data.get("severity") or data.get("danger_level") or risk,
        default="serious" if outside or risk == "中高風險" else "attention",
    )
    alert_type = str(
        data.get("alert_type")
        or data.get("event_type")
        or ("geofence_intrusion" if outside else "uwb_risk")
    )
    message_text = str(
        data.get("alert_message")
        or data.get("message")
        or (
            "人員進入危險電子圍籬"
            if outside
            else "UWB 偵測到人員高風險狀態"
            if risk == "中高風險"
            else "UWB 偵測到人員需要注意"
        )
    )
    detail = (
        f"人員／標籤 {normalized['device_id']}・"
        f"座標 X {normalized['x']:.1f} / Y {normalized['y']:.1f} / Z {normalized['z']:.1f}・"
        f"電量 {normalized['battery']}%"
    )
    return record_safety_alert(
        "UWB",
        normalized["device_id"],
        normalized.get("area") or "未設定區域",
        alert_type,
        message_text,
        detail,
        severity,
        metadata={"payload": data, "normalized": normalized},
        occurred_at=normalized["timestamp"],
    )


def record_camera_safety_alerts(camera_id, location, detections, timestamp, image_url=""):
    alert_ids = []
    ppe_labels = (("helmet", "安全帽"), ("vest", "反光背心"), ("mask", "口罩"))
    for detection in detections:
        if not isinstance(detection, dict):
            continue
        device_id = str(
            detection.get("device_id")
            or detection.get("person_id")
            or detection.get("track_id")
            or "未識別"
        ).strip()
        missing_items = [
            label
            for key, label in ppe_labels
            if key in detection and not parse_bool(detection.get(key), default=True)
        ]
        explicit_alert = (
            parse_bool(detection.get("danger", detection.get("unsafe", False)), default=False)
            or parse_bool(detection.get("alert", False), default=False)
            or bool(detection.get("alert_type") or detection.get("danger_type"))
        )
        if not missing_items and not explicit_alert:
            continue
        if missing_items:
            alert_type = "ppe_violation"
            message_text = f"偵測到人員未配戴{'、'.join(missing_items)}"
            severity = "serious" if "安全帽" in missing_items else "attention"
        else:
            alert_type = str(
                detection.get("alert_type")
                or detection.get("danger_type")
                or detection.get("event_type")
                or "yolo_danger"
            )
            message_text = str(
                detection.get("alert_message")
                or detection.get("message")
                or f"YOLO 偵測到危險事件：{alert_type}"
            )
            severity = normalize_safety_severity(
                detection.get("severity") or detection.get("risk"),
                default="serious",
            )
        confidence = detection.get("confidence")
        try:
            confidence_text = f"{float(confidence) * 100:.0f}%"
        except (TypeError, ValueError):
            confidence_text = "未提供"
        detail = f"人員／裝置 {device_id}・信心度 {confidence_text}"
        alert_ids.append(
            record_safety_alert(
                "YOLO",
                camera_id,
                location,
                alert_type,
                message_text,
                detail,
                severity,
                metadata={
                    "detection": detection,
                    "image_url": image_url,
                    "person_id": device_id,
                },
                occurred_at=timestamp,
            )
        )
    return alert_ids


def recent_communication_events(source, limit=20):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    result = rows(
        "SELECT id,source,device_id,event_type,payload,received_at FROM communication_events WHERE source=? ORDER BY id DESC LIMIT ?",
        (source, max(1, min(100, limit))),
    )
    for item in result:
        try:
            item["payload"] = json.loads(item["payload"])
        except (TypeError, json.JSONDecodeError):
            pass
    return result


def process_uwb_payload(data, source="HTTP"):
    if not isinstance(data, dict):
        raise ValueError("資料必須是 JSON 物件")
    device_id = str(data.get("device_id") or data.get("id") or "").strip().upper()
    if not device_id:
        raise ValueError("缺少 device_id")
    try:
        x = float(data.get("x"))
        y = float(data.get("y"))
        z = float(data.get("z", 0))
        battery = max(0, min(100, int(data.get("battery", 100))))
    except (TypeError, ValueError):
        raise ValueError("x、y、z 或 battery 格式不正確") from None
    helmet = parse_bool(data.get("helmet"), default=False)
    vest = parse_bool(data.get("vest"), default=False)
    risk = str(data.get("risk") or auto_risk(helmet, vest))
    if risk not in ("低風險", "注意", "中高風險"):
        risk = auto_risk(helmet, vest)
    incoming_name = str(data.get("name") or data.get("device_name") or "").strip()
    existing = get_db().execute(
        "SELECT id,name,employee_name,area FROM people WHERE id=?",
        (device_id,),
    ).fetchone()
    if not existing and incoming_name:
        manual = get_db().execute(
                "SELECT id,name,employee_name,area FROM people WHERE lower(name)=lower(?) AND id LIKE 'MANUAL-%' LIMIT 1",
            (incoming_name,),
        ).fetchone()
        if manual:
            get_db().execute(
                "UPDATE people SET id=? WHERE id=?",
                (device_id, manual["id"]),
            )
            existing = get_db().execute(
                "SELECT id,name,employee_name,area FROM people WHERE id=?",
                (device_id,),
            ).fetchone()
    name = incoming_name or (existing["name"] if existing else device_id)
    employee_name = existing["employee_name"] if existing else "未綁定"
    area = str(
        data.get("area")
        or data.get("location")
        or (existing["area"] if existing else "")
        or "未設定區域"
    ).strip()
    timestamp = str(data.get("timestamp") or datetime.now().astimezone().isoformat(timespec="seconds"))
    raw_status = str(data.get("status") or data.get("device_status") or "online").strip().lower()
    device_status = "離線" if raw_status in {"offline", "off", "0", "離線"} else "連線中"
    normalized = {
        "device_id": device_id, "name": name, "x": x, "y": y, "z": z,
        "helmet": bool(helmet), "vest": bool(vest), "battery": battery,
        "risk": risk, "device_status": device_status, "area": area,
        "timestamp": timestamp, "source": source,
    }
    get_db().execute(
        """
        INSERT INTO people
          (id,name,employee_name,area,x,y,z,helmet,vest,battery,risk,device_status,last_seen)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          name=excluded.name,area=excluded.area,x=excluded.x,y=excluded.y,z=excluded.z,helmet=excluded.helmet,
          vest=excluded.vest,battery=excluded.battery,risk=excluded.risk,
          device_status=excluded.device_status,last_seen=excluded.last_seen
        """,
        (
            device_id, name, employee_name, area, x, y, z, helmet, vest,
            battery, risk, device_status, timestamp,
        ),
    )
    get_db().commit()
    record_communication_event("uwb", "position_update", normalized, device_id)
    safety_alert_id = record_uwb_safety_alert(data, normalized)
    normalized["safety_alert_id"] = safety_alert_id
    return normalized


def verify_line_signature(raw_body, signature):
    secret = app.config["LINE_CHANNEL_SECRET"]
    if not secret:
        return False
    expected = base64.b64encode(hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()).decode("ascii")
    return bool(signature) and hmac.compare_digest(signature, expected)


def line_post(path, payload):
    token = str(app.config["LINE_CHANNEL_ACCESS_TOKEN"] or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise RuntimeError("尚未設定 LINE_CHANNEL_ACCESS_TOKEN")
    if len(token) < 50:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN 太短，請勿填入 Channel ID 或 Channel secret")
    req = urllib.request.Request(
        f"https://api.line.me/v2/bot/message/{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json",
            "User-Agent": "SafeGuard-Line-Alert/1.0",
        },
        method="POST",
    )
    # 避免 VS Code/Codex 終端機的本機 Proxy 環境變數攔截 LINE API。
    direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with direct_opener.open(req, timeout=10) as response:
        return response.status


def line_get_json(path):
    """讀取 LINE Messaging API 資料，主要用來取得警報接收者名稱。"""
    token = str(app.config["LINE_CHANNEL_ACCESS_TOKEN"] or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise RuntimeError("尚未設定 LINE_CHANNEL_ACCESS_TOKEN")
    req = urllib.request.Request(
        f"https://api.line.me/v2/bot/{path.lstrip('/')}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "SafeGuard-Line-Alert/1.0",
        },
        method="GET",
    )
    direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with direct_opener.open(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def send_line_alert(text, user_id=None, message_object=None):
    target = str(user_id or app.config["LINE_TARGET_USER_ID"] or "").strip()
    if not target:
        raise RuntimeError("尚未設定 LINE_TARGET_USER_ID")
    if not re.fullmatch(r"U[0-9a-f]{32}", target):
        raise RuntimeError("LINE_TARGET_USER_ID 格式錯誤，必須是 U 加上 32 個英數字元")
    line_message = message_object or {"type": "text", "text": str(text)[:5000]}
    return line_post("push", {"to": target, "messages": [line_message]})


def line_alert_configured():
    token = str(app.config["LINE_CHANNEL_ACCESS_TOKEN"] or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return bool(
        len(token) >= 50
        and re.fullmatch(r"U[0-9a-f]{32}", app.config["LINE_TARGET_USER_ID"])
    )


def line_acknowledgement_configured():
    return bool(line_alert_configured() and app.config["LINE_CHANNEL_SECRET"])


def build_safety_line_message(alert):
    """將資料庫中的危險警報轉成適合手機快速閱讀的 LINE 文字。"""
    severity_views = {
        "emergency": ("🚨", "緊急"),
        "serious": ("⚠️", "嚴重"),
        "attention": ("🔔", "注意"),
    }
    icon, severity_label = severity_views.get(
        alert["severity"], severity_views["attention"]
    )
    source_label = {
        "YOLO": "YOLO 影像辨識",
        "UWB": "UWB 電子圍籬",
    }.get(alert["source_system"], alert["source_system"])
    try:
        occurred_at = datetime.fromisoformat(alert["occurred_at"]).astimezone().strftime(
            "%Y/%m/%d %H:%M:%S"
        )
    except (TypeError, ValueError):
        occurred_at = str(alert["occurred_at"] or "未提供")
    alert_url = safety_alert_url(alert["id"])
    lines = [
        f"{icon} SafeGuard {severity_label}危險警報",
        "",
        f"事件：{alert['message']}",
        f"來源：{source_label}",
        f"設備：{alert['device_id'] or '未提供'}",
        f"位置：{alert['location'] or '未設定位置'}",
        f"時間：{occurred_at}",
        f"狀態：{'尚未處理' if alert['status'] == 'open' else '已處理'}",
    ]
    if alert["detail"]:
        lines.append(f"說明：{alert['detail']}")
    lines.extend(["", "請立即前往現場查看。", f"查看警報：{alert_url}"])
    return "\n".join(lines)[:5000]


def safety_alert_url(alert_id):
    base_url = app.config["PUBLIC_BASE_URL"]
    if has_request_context() and base_url in {
        "http://127.0.0.1:5000", "http://localhost:5000"
    }:
        base_url = request.host_url.rstrip("/")
    return f"{base_url}/system-status?alert={int(alert_id)}"


def build_safety_line_flex(alert):
    """建立含「已接收」與「前往查看」按鈕的 LINE Flex Message。"""
    severity_views = {
        "emergency": ("🚨", "緊急", "#D92D4B"),
        "serious": ("⚠️", "嚴重", "#D97706"),
        "attention": ("🔔", "注意", "#2563EB"),
    }
    icon, severity_label, severity_color = severity_views.get(
        alert["severity"], severity_views["attention"]
    )
    source_label = {
        "YOLO": "YOLO 影像辨識",
        "UWB": "UWB 電子圍籬",
    }.get(alert["source_system"], alert["source_system"])
    try:
        occurred_at = datetime.fromisoformat(alert["occurred_at"]).astimezone().strftime(
            "%Y/%m/%d %H:%M:%S"
        )
    except (TypeError, ValueError):
        occurred_at = str(alert["occurred_at"] or "未提供")

    facts = [
        ("事件", alert["message"]),
        ("來源", source_label),
        ("位置", alert["location"] or "未設定位置"),
        ("設備", alert["device_id"] or "未提供"),
        ("時間", occurred_at),
    ]
    fact_components = []
    for label, value in facts:
        fact_components.append(
            {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "text", "text": label, "color": "#6B7280",
                        "size": "sm", "flex": 2,
                    },
                    {
                        "type": "text", "text": str(value)[:300], "color": "#102A52",
                        "size": "sm", "flex": 5, "wrap": True,
                    },
                ],
            }
        )
    if alert["detail"]:
        fact_components.append(
            {
                "type": "text", "text": f"說明：{alert['detail']}"[:500],
                "size": "sm", "color": "#516784", "wrap": True,
                "margin": "md",
            }
        )

    return {
        "type": "flex",
        "altText": f"{icon} SafeGuard {severity_label}警報：{alert['message']}"[:400],
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": severity_color,
                "paddingAll": "18px",
                "contents": [
                    {
                        "type": "text", "text": f"{icon} SafeGuard {severity_label}危險警報",
                        "color": "#FFFFFF", "weight": "bold", "size": "lg",
                    }
                ],
            },
            "body": {
                "type": "box", "layout": "vertical", "spacing": "md",
                "contents": fact_components + [
                    {
                        "type": "text", "text": "請立即前往查看並確認人員安全。",
                        "weight": "bold", "size": "sm", "color": severity_color,
                        "wrap": True, "margin": "md",
                    }
                ],
            },
            "footer": {
                "type": "box", "layout": "horizontal", "spacing": "sm",
                "contents": [
                    {
                        "type": "button", "style": "primary", "color": severity_color,
                        "action": {
                            "type": "postback", "label": "已接收",
                            "data": f"action=ack_safety_alert&alert_id={alert['id']}",
                            "displayText": f"已接收 SafeGuard 警報 #{alert['id']}",
                        },
                    },
                    {
                        "type": "button", "style": "secondary",
                        "action": {
                            "type": "uri", "label": "前往查看",
                            "uri": safety_alert_url(alert["id"]),
                        },
                    },
                ],
            },
        },
    }


def save_line_alert_delivery(
    alert_id,
    recipient,
    message_text,
    status,
    *,
    attempts=0,
    http_status=None,
    failure_reason="",
    sent_at="",
):
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    get_db().execute(
        """
        INSERT INTO line_alert_deliveries
          (alert_id,recipient,message,status,attempts,http_status,failure_reason,
           created_at,sent_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(alert_id) DO UPDATE SET
          recipient=excluded.recipient,
          message=excluded.message,
          status=excluded.status,
          attempts=excluded.attempts,
          http_status=excluded.http_status,
          failure_reason=excluded.failure_reason,
          sent_at=excluded.sent_at,
          updated_at=excluded.updated_at
        """,
        (
            alert_id, recipient, message_text, status, attempts, http_status,
            str(failure_reason or "")[:500], now, sent_at, now,
        ),
    )
    get_db().commit()


def dispatch_safety_alert_to_line(alert_id, force=False):
    """派送一筆危險警報並保存結果；失敗只記錄，不中斷警報來源 API。"""
    alert = get_db().execute(
        """
        SELECT id,source_system,device_id,location,alert_type,message,detail,
               severity,status,occurred_at
        FROM safety_alerts WHERE id=?
        """,
        (alert_id,),
    ).fetchone()
    if not alert:
        raise ValueError("找不到危險警報")
    existing = get_db().execute(
        "SELECT status,attempts FROM line_alert_deliveries WHERE alert_id=?",
        (alert_id,),
    ).fetchone()
    if existing and existing["status"] == "sent" and not force:
        return {"status": "sent", "attempts": existing["attempts"], "skipped": True}

    recipient = app.config["LINE_TARGET_USER_ID"]
    message_text = build_safety_line_message(alert)
    message_object = build_safety_line_flex(alert)
    attempts = int(existing["attempts"] or 0) if existing else 0
    if not line_alert_configured():
        save_line_alert_delivery(
            alert_id,
            recipient,
            message_text,
            "not_configured",
            attempts=attempts,
            failure_reason="尚未設定 Channel Access Token 或 LINE 通知對象",
        )
        return {"status": "not_configured", "attempts": attempts}

    attempts += 1
    save_line_alert_delivery(
        alert_id, recipient, message_text, "sending", attempts=attempts
    )
    try:
        status_code = send_line_alert(
            message_text, recipient, message_object=message_object
        )
        sent_at = datetime.now().astimezone().isoformat(timespec="seconds")
        save_line_alert_delivery(
            alert_id,
            recipient,
            message_text,
            "sent",
            attempts=attempts,
            http_status=status_code,
            sent_at=sent_at,
        )
        record_communication_event(
            "line",
            "safety_alert_sent",
            {"alert_id": alert_id, "status": status_code},
            str(alert["device_id"] or ""),
        )
        return {"status": "sent", "attempts": attempts, "http_status": status_code}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        failure_reason = f"LINE API {exc.code}: {detail}"
        http_status = exc.code
    except urllib.error.URLError as exc:
        failure_reason = f"無法連線 LINE API：{exc.reason}"
        http_status = None
    except Exception as exc:
        failure_reason = str(exc)
        http_status = None
    save_line_alert_delivery(
        alert_id,
        recipient,
        message_text,
        "failed",
        attempts=attempts,
        http_status=http_status,
        failure_reason=failure_reason,
    )
    record_communication_event(
        "line",
        "safety_alert_failed",
        {"alert_id": alert_id, "reason": failure_reason},
        str(alert["device_id"] or ""),
    )
    app.logger.warning("危險警報 #%s LINE 發送失敗：%s", alert_id, failure_reason)
    return {"status": "failed", "attempts": attempts, "failure_reason": failure_reason}


def send_ppe_alert(camera_id, location, device_id, missing_items, confidence=None):
    """將 YOLO PPE 違規結果轉成 SafeGuard LINE 即時警報。"""
    try:
        confidence_text = f"{float(confidence) * 100:.1f}%"
    except (TypeError, ValueError):
        confidence_text = "未提供"
    message_text = (
        "🚨【SafeGuard 職安違規即時通報】\n"
        f"📍 位置：{location or '未設定位置'}\n"
        f"📷 攝影機：{camera_id}\n"
        f"👤 人員／裝置：{device_id or '未識別'}\n"
        f"⚠️ 違規事項：未依規定配戴【{'、'.join(missing_items)}】\n"
        f"🎯 辨識信心度：{confidence_text}\n"
        f"🕒 時間：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "請現場主管立即前往確認並要求改善。"
    )
    status = send_line_alert(message_text)
    return status, message_text


def acquire_line_alert_slot(key):
    """同一攝影機、裝置及違規組合在冷卻時間內只發送一次。"""
    now = time.monotonic()
    cooldown = app.config["LINE_ALERT_COOLDOWN_SECONDS"]
    with LINE_ALERT_LOCK:
        last_sent = LINE_ALERT_LAST_SENT.get(key)
        if last_sent is not None and now - last_sent < cooldown:
            return False
        LINE_ALERT_LAST_SENT[key] = now
    return True


def release_line_alert_slot(key):
    with LINE_ALERT_LOCK:
        LINE_ALERT_LAST_SENT.pop(key, None)


def process_camera_ppe_alerts(camera_id, location, detections):
    result = {"configured": False, "sent": 0, "cooldown_skipped": 0, "errors": []}
    if not (
        app.config["LINE_CHANNEL_ACCESS_TOKEN"]
        and app.config["LINE_TARGET_USER_ID"]
    ):
        return result
    result["configured"] = True
    if not isinstance(detections, list):
        return result
    ppe_labels = (("helmet", "安全帽"), ("vest", "反光背心"), ("mask", "口罩"))
    for detection in detections:
        if not isinstance(detection, dict):
            continue
        missing_items = [
            label
            for key, label in ppe_labels
            if key in detection and not parse_bool(detection.get(key), default=True)
        ]
        if not missing_items:
            continue
        device_id = str(
            detection.get("device_id")
            or detection.get("person_id")
            or detection.get("track_id")
            or "未識別"
        ).strip()
        alert_key = (camera_id.upper(), device_id, tuple(missing_items))
        if not acquire_line_alert_slot(alert_key):
            result["cooldown_skipped"] += 1
            continue
        try:
            status, alert_text = send_ppe_alert(
                camera_id,
                location,
                device_id,
                missing_items,
                detection.get("confidence"),
            )
            result["sent"] += 1
            record_communication_event(
                "line",
                "ppe_alert",
                {
                    "camera_id": camera_id,
                    "location": location,
                    "device_id": device_id,
                    "missing_items": missing_items,
                    "confidence": detection.get("confidence"),
                    "line_status": status,
                    "message": alert_text,
                },
                device_id,
            )
        except Exception as exc:
            release_line_alert_slot(alert_key)
            result["errors"].append(str(exc))
            app.logger.warning("LINE PPE 警報發送失敗：%s", exc)
            record_system_error("LINE Bot", "LINE PPE 警報發送失敗", str(exc))
    return result


def start_mqtt_client():
    global MQTT_CLIENT, MQTT_STARTED
    if MQTT_STARTED or not app.config["MQTT_ENABLED"]:
        return
    MQTT_STARTED = True
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        app.logger.warning("MQTT_ENABLED=true，但尚未安裝 paho-mqtt")
        with app.app_context():
            init_db()
            record_system_error("MQTT", "MQTT 用戶端無法啟動", "尚未安裝 paho-mqtt")
        return

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if int(reason_code) == 0:
            client.subscribe(app.config["MQTT_TOPIC"])
            app.logger.info("MQTT 已連線並訂閱 %s", app.config["MQTT_TOPIC"])
        else:
            app.logger.error("MQTT 連線失敗：%s", reason_code)
            with app.app_context():
                init_db()
                record_system_error("MQTT", "MQTT Broker 連線失敗", f"reason_code={reason_code}")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            with app.app_context():
                init_db()
                process_uwb_payload(payload, source="MQTT")
        except Exception as exc:
            app.logger.exception("MQTT 訊息處理失敗：%s", exc)
            with app.app_context():
                init_db()
                record_system_error("MQTT", "MQTT 訊息處理失敗", str(exc))

    MQTT_CLIENT = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="safeguard-server")
    if app.config["MQTT_USERNAME"]:
        MQTT_CLIENT.username_pw_set(app.config["MQTT_USERNAME"], app.config["MQTT_PASSWORD"])
    MQTT_CLIENT.on_connect = on_connect
    MQTT_CLIENT.on_message = on_message
    MQTT_CLIENT.connect_async(app.config["MQTT_HOST"], app.config["MQTT_PORT"], 60)
    MQTT_CLIENT.loop_start()


@app.before_request
def prepare_database():
    init_db()


@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE account=? AND active=1", (account,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user_role"] = user["role"]
            get_db().execute("UPDATE users SET last_active=? WHERE id=?", ("剛剛", user["id"]))
            get_db().commit()
            return redirect(url_for("dashboard"))
        error = "帳號或密碼不正確，或帳號已被停用。"
    return render_template("login.html", error=error)


@app.post("/api/auth/request-password-reset")
def request_password_reset():
    data = request.get_json(silent=True) or {}
    account = str(data.get("account", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    if not account or not email:
        return message("請填寫帳號與電子郵件")
    if not EMAIL_PATTERN.fullmatch(email):
        return message("請輸入有效的電子郵件，例如 c113118118@nkust.edu.tw")

    user = get_db().execute(
        "SELECT id,email FROM users WHERE account=? AND lower(email)=? AND active=1",
        (account, email),
    ).fetchone()
    if not user:
        return jsonify(ok=True, message=PASSWORD_RESET_RESPONSE)

    latest = get_db().execute(
        "SELECT created_at FROM password_reset_tokens WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (user["id"],),
    ).fetchone()
    if latest:
        try:
            elapsed = (datetime.now().astimezone() - datetime.fromisoformat(latest["created_at"])).total_seconds()
            if elapsed < app.config["PASSWORD_RESET_COOLDOWN_SECONDS"]:
                return jsonify(ok=True, message=PASSWORD_RESET_RESPONSE)
        except (TypeError, ValueError):
            pass

    _, reset_url, _, _ = deliver_password_reset(user)

    response = {"ok": True, "message": PASSWORD_RESET_RESPONSE}
    if app.config.get("TESTING"):
        response["reset_url"] = reset_url
    return jsonify(response)


@app.get("/reset-password")
def reset_password_page():
    token = request.args.get("token", "")
    return render_template(
        "reset_password.html",
        reset_token=token,
        token_valid=bool(password_reset_token_row(token)),
    )


@app.post("/api/auth/confirm-password-reset")
def confirm_password_reset():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token", ""))
    password = str(data.get("password", ""))
    confirm_password = str(data.get("confirm_password", ""))
    if len(password) < 12:
        return message("新密碼至少需要 12 個字元")
    if password != confirm_password:
        return message("兩次輸入的密碼不一致")

    token_row = password_reset_token_row(token)
    if not token_row:
        return message("重設連結無效、已使用或已逾期", 400)

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    used = get_db().execute(
        "UPDATE password_reset_tokens SET used_at=? WHERE id=? AND used_at=''",
        (now, token_row["id"]),
    )
    if used.rowcount != 1:
        get_db().rollback()
        return message("重設連結無效、已使用或已逾期", 400)
    get_db().execute(
        "UPDATE users SET password=? WHERE id=?",
        (generate_password_hash(password), token_row["user_id"]),
    )
    get_db().execute(
        "UPDATE password_reset_tokens SET used_at=? WHERE user_id=? AND used_at=''",
        (now, token_row["user_id"]),
    )
    get_db().commit()
    record_communication_event(
        "email", "password_reset_completed", {"result": "success"}, str(token_row["user_id"])
    )
    session.clear()
    return jsonify(ok=True, message="密碼已更新，請使用新密碼登入。")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        is_admin=current_user()["role"] == "管理員",
    )


@app.get("/system-status")
@admin_required
def system_status():
    return render_template("system_status.html")


@app.get("/api/safety-alerts")
@admin_required
def api_safety_alerts():
    try:
        limit = max(1, min(200, int(request.args.get("limit", 50))))
    except (TypeError, ValueError):
        limit = 50
    conditions = []
    values = []
    status = str(request.args.get("status", "all")).strip().lower()
    source = str(request.args.get("source", "all")).strip().upper()
    query = str(request.args.get("q", "")).strip()[:100]
    try:
        days = max(0, min(3650, int(request.args.get("days", 0))))
    except (TypeError, ValueError):
        days = 0
    if status in {"open", "resolved"}:
        conditions.append("a.status=?")
        values.append(status)
    if source in {"YOLO", "UWB"}:
        conditions.append("a.source_system=?")
        values.append(source)
    if query:
        search_value = f"%{query}%"
        conditions.append(
            "(a.message LIKE ? OR a.detail LIKE ? OR a.device_id LIKE ? OR a.location LIKE ? "
            "OR a.resolved_by LIKE ? OR a.resolution_note LIKE ?)"
        )
        values.extend([search_value] * 6)
    if days:
        cutoff = (datetime.now().astimezone() - timedelta(days=days)).isoformat(
            timespec="seconds"
        )
        conditions.append(
            "CASE WHEN a.status='resolved' AND a.resolved_at<>'' "
            "THEN a.resolved_at ELSE a.occurred_at END >= ?"
        )
        values.append(cutoff)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order_sql = (
        "a.resolved_at DESC,a.id DESC"
        if status == "resolved"
        else "CASE a.severity WHEN 'emergency' THEN 1 WHEN 'serious' THEN 2 ELSE 3 END, "
             "a.occurred_at DESC,a.id DESC"
    )
    alerts = rows(
        f"""
        SELECT a.id,a.source_system,a.device_id,a.location,a.alert_type,a.message,
               a.detail,a.severity,a.status,a.occurrences,a.metadata,a.occurred_at,
               a.acknowledged_at,a.acknowledged_by,a.acknowledged_user_id,
               a.resolved_at,a.resolved_by,a.resolution_note,
               COALESCE(d.status,'not_sent') AS line_status,
               COALESCE(d.attempts,0) AS line_attempts,
               COALESCE(d.failure_reason,'') AS line_failure_reason,
               COALESCE(d.sent_at,'') AS line_sent_at
        FROM safety_alerts AS a
        LEFT JOIN line_alert_deliveries AS d ON d.alert_id=a.id
        {where_sql}
        ORDER BY {order_sql}
        LIMIT ?
        """,
        (*values, limit),
    )
    for alert in alerts:
        try:
            alert["metadata"] = json.loads(alert["metadata"] or "{}")
        except (TypeError, json.JSONDecodeError):
            alert["metadata"] = {}
    open_count = get_db().execute(
        "SELECT COUNT(*) FROM safety_alerts WHERE status='open'"
    ).fetchone()[0]
    resolved_count = get_db().execute(
        "SELECT COUNT(*) FROM safety_alerts WHERE status='resolved'"
    ).fetchone()[0]
    return jsonify(
        ok=True,
        alerts=alerts,
        open_count=open_count,
        resolved_count=resolved_count,
        line_configured=line_alert_configured(),
        line_ack_configured=line_acknowledgement_configured(),
    )


@app.post("/api/safety-alerts/<int:alert_id>/resolve")
@admin_required
def resolve_safety_alert(alert_id):
    data = request.get_json(silent=True) or {}
    resolution_note = str(data.get("resolution_note") or "已完成現場確認與事件處理").strip()[:500]
    resolved_by = str(current_user()["name"] or current_user()["account"]).strip()[:80]
    resolved_at = datetime.now().astimezone().isoformat(timespec="seconds")
    cursor = get_db().execute(
        """
        UPDATE safety_alerts
        SET status='resolved',resolved_at=?,resolved_by=?,resolution_note=?
        WHERE id=? AND status='open'
        """,
        (resolved_at, resolved_by, resolution_note, alert_id),
    )
    get_db().commit()
    if cursor.rowcount != 1:
        return message("找不到此未處理警報", 404)
    return jsonify(ok=True, message="危險警報已標記為已處理")


@app.post("/api/safety-alerts/<int:alert_id>/reopen")
@admin_required
def reopen_safety_alert(alert_id):
    cursor = get_db().execute(
        """
        UPDATE safety_alerts
        SET status='open',resolved_at='',resolved_by='',resolution_note=''
        WHERE id=? AND status='resolved'
        """,
        (alert_id,),
    )
    get_db().commit()
    if cursor.rowcount != 1:
        return message("找不到此已完成事件", 404)
    return jsonify(ok=True, message="事件已還原為未處理警報")


@app.post("/api/safety-alerts/<int:alert_id>/line/retry")
@admin_required
def retry_safety_alert_line(alert_id):
    try:
        result = dispatch_safety_alert_to_line(alert_id, force=True)
    except ValueError as exc:
        return message(str(exc), 404)
    if result["status"] == "sent":
        return jsonify(ok=True, message="LINE 危險警報已重新傳送", delivery=result)
    if result["status"] == "not_configured":
        return jsonify(
            ok=False, message="尚未完成 LINE Messaging API 設定", delivery=result
        ), 503
    return jsonify(
        ok=False,
        message=result.get("failure_reason") or "LINE 危險警報傳送失敗",
        delivery=result,
    ), 502


@app.post("/api/safety-alerts/line-test")
@admin_required
def test_safety_alert_line():
    timestamp = datetime.now().astimezone()
    alert_id = record_safety_alert(
        "YOLO",
        f"LINE-TEST-{timestamp.strftime('%H%M%S')}",
        "SafeGuard 系統測試",
        "line_connection_test",
        "LINE 即時危險警報連線測試",
        "這是管理員手動建立的測試警報，無須前往現場。",
        "attention",
        metadata={"test": True},
        occurred_at=timestamp.isoformat(timespec="seconds"),
    )
    delivery = get_db().execute(
        """
        SELECT status,attempts,http_status,failure_reason,sent_at
        FROM line_alert_deliveries WHERE alert_id=?
        """,
        (alert_id,),
    ).fetchone()
    delivery_data = dict(delivery) if delivery else {"status": "not_sent"}
    if delivery_data["status"] == "sent":
        return jsonify(
            ok=True,
            message="LINE 測試警報已送出",
            alert_id=alert_id,
            delivery=delivery_data,
        )
    if delivery_data["status"] == "not_configured":
        return jsonify(
            ok=False,
            message="測試警報已建立，但尚未完成 LINE Messaging API 設定",
            alert_id=alert_id,
            delivery=delivery_data,
        ), 503
    return jsonify(
        ok=False,
        message=delivery_data.get("failure_reason") or "LINE 測試警報傳送失敗",
        alert_id=alert_id,
        delivery=delivery_data,
    ), 502


@app.get("/api/system/status")
@admin_required
def api_system_status():
    try:
        sqlite_result = get_db().execute("PRAGMA quick_check").fetchone()[0]
        sqlite_ok = str(sqlite_result).lower() == "ok"
        sqlite_detail = "資料庫完整性檢查通過" if sqlite_ok else str(sqlite_result)
    except sqlite3.Error as exc:
        sqlite_ok = False
        sqlite_detail = str(exc)

    latest_email = get_db().execute(
        "SELECT status,created_at,sent_at,failure_reason FROM email_deliveries ORDER BY id DESC LIMIT 1"
    ).fetchone()
    smtp_configured = bool(
        app.config["SMTP_USERNAME"]
        and app.config["SMTP_APP_PASSWORD"]
        and app.config["SMTP_FROM_EMAIL"]
    )
    if not smtp_configured:
        email_state, email_label = "not_configured", "未設定"
    elif latest_email and latest_email["status"] == "failed":
        email_state, email_label = "warning", "最近寄送失敗"
    else:
        email_state, email_label = "ok", "服務正常"

    latest_uwb = get_db().execute(
        """
        SELECT received_at,payload FROM communication_events
        WHERE source='uwb' ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    stations = rows(
        """
        SELECT id,name,status,last_seen FROM base_stations
        ORDER BY id LIMIT 20
        """
    )
    cameras = rows(
        """
        SELECT id,location,status,last_seen,stream_url FROM monitoring_devices
        ORDER BY id LIMIT 50
        """
    )
    online_values = {"online", "正常", "連線中"}
    station_online = sum(
        1 for station in stations if str(station["status"]).strip().lower() in online_values
    )
    camera_online = sum(
        1 for camera in cameras if str(camera["status"]).strip().lower() in online_values
    )
    errors = rows(
        """
        SELECT id,service,message,detail,severity,status,occurrences,occurred_at,resolved_at
        FROM system_errors ORDER BY id DESC LIMIT 20
        """
    )
    open_error_count = get_db().execute(
        "SELECT COUNT(*) FROM system_errors WHERE status='open'"
    ).fetchone()[0]
    latest_email_time = "尚無紀錄"
    if latest_email:
        latest_email_time = latest_email["sent_at"] or latest_email["created_at"]
    return jsonify(
        ok=True,
        checked_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        services={
            "sqlite": {
                "state": "ok" if sqlite_ok else "warning",
                "label": "正常" if sqlite_ok else "異常",
                "detail": sqlite_detail,
                "database": os.path.basename(app.config["DATABASE"]),
            },
            "email": {
                "state": email_state,
                "label": email_label,
                "detail": (latest_email["failure_reason"] if latest_email and latest_email["status"] == "failed" else "SMTP TLS 郵寄服務"),
                "last_check": latest_email_time,
            },
            "line": {
                "state": "ok" if line_alert_configured() else "not_configured",
                "label": "服務正常" if line_alert_configured() else "未設定",
                "detail": "LINE 即時通知已啟用" if line_alert_configured() else "缺少 Token 或 U 開頭的完整 User ID",
            },
            "uwb": {
                "state": "ok" if latest_uwb else "not_configured",
                "label": "持續接收資料" if latest_uwb else "等待資料",
                "detail": "UWB REST API / MQTT 共用接收服務",
                "last_received": latest_uwb["received_at"] if latest_uwb else "尚未收到資料",
            },
            "stations": {
                "state": "ok" if stations and station_online == len(stations) else ("warning" if stations else "not_configured"),
                "label": f"{station_online} / {len(stations)} 連線中",
                "detail": "固定四個基站連線狀態",
                "items": stations,
            },
            "cameras": {
                "state": "ok" if cameras and camera_online == len(cameras) else ("warning" if cameras else "not_configured"),
                "label": f"{camera_online} / {len(cameras)} 攝影機在線",
                "detail": "YOLO 影像辨識串流狀態",
                "items": cameras,
            },
        },
        errors=errors,
        open_error_count=open_error_count,
    )


@app.post("/api/system/errors/<int:error_id>/resolve")
@admin_required
def resolve_system_error(error_id):
    resolved_at = datetime.now().astimezone().isoformat(timespec="seconds")
    cursor = get_db().execute(
        """
        UPDATE system_errors SET status='resolved',resolved_at=?
        WHERE id=? AND status='open'
        """,
        (resolved_at, error_id),
    )
    get_db().commit()
    if cursor.rowcount != 1:
        return message("找不到未處理的錯誤紀錄", 404)
    return jsonify(ok=True, message="錯誤已標記為處理完成")


@app.route("/site-map")
@login_required
def site_map():
    return render_template("site_map.html")


@app.route("/people")
@login_required
def people():
    return render_template("people.html")


@app.route("/monitoring-devices")
@login_required
def monitoring_devices():
    return render_template("monitoring_devices.html")


@app.route("/yolo")
@login_required
def yolo():
    return render_template("yolo.html")


@app.route("/base-stations")
@login_required
def base_stations():
    return render_template("base_stations.html")


@app.route("/users")
@admin_required
def users():
    return render_template("users.html")


@app.get("/email-service")
@admin_required
def email_service():
    return render_template("email_service.html")


@app.get("/api/email/status")
@admin_required
def api_email_status():
    configured = bool(
        app.config["SMTP_USERNAME"]
        and app.config["SMTP_APP_PASSWORD"]
        and app.config["SMTP_FROM_EMAIL"]
    )
    latest = get_db().execute(
        """
        SELECT status,created_at,sent_at FROM email_deliveries
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if not configured:
        state, label = "not_configured", "尚未設定"
    elif latest and latest["status"] == "failed":
        state, label = "warning", "需要檢查"
    else:
        state, label = "ok", "服務正常"
    return jsonify(
        ok=True,
        configured=configured,
        state=state,
        label=label,
        sender=app.config["SMTP_FROM_EMAIL"] or "尚未設定",
        host=app.config["SMTP_HOST"],
        port=app.config["SMTP_PORT"],
        encryption="TLS",
        last_check=(latest["sent_at"] or latest["created_at"]) if latest else "尚無紀錄",
    )


@app.get("/api/email/deliveries")
@admin_required
def api_email_deliveries():
    status = request.args.get("status", "all").strip().lower()
    if status not in {"all", "sent", "failed"}:
        return message("寄送狀態篩選條件不正確")
    try:
        limit = max(1, min(100, int(request.args.get("limit", 50))))
    except (TypeError, ValueError):
        limit = 50
    sql = """
        SELECT id,user_id,recipient,notification_type,subject,status,
               failure_reason,retry_of_id,created_at,sent_at
        FROM email_deliveries
    """
    values = []
    if status != "all":
        sql += " WHERE status=?"
        values.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    values.append(limit)
    deliveries = rows(sql, values)
    for delivery in deliveries:
        delivery["recipient_masked"] = mask_email_address(delivery.pop("recipient", ""))
    return jsonify(ok=True, deliveries=deliveries)


@app.post("/api/email/test")
@admin_required
def api_email_test():
    data = request.get_json(silent=True) or {}
    recipient = str(
        data.get("recipient")
        or current_user()["email"]
        or app.config["SMTP_FROM_EMAIL"]
        or ""
    ).strip().lower()
    if not EMAIL_PATTERN.fullmatch(recipient):
        return message("請先替管理員設定電子郵件，或完成 SMTP_FROM_EMAIL 設定")
    sent, delivery_id, reason = deliver_test_email(recipient, current_user()["id"])
    if not sent:
        return jsonify(ok=False, message=reason, delivery_id=delivery_id), 502
    return jsonify(ok=True, message=f"測試信已寄送至 {mask_email_address(recipient)}", delivery_id=delivery_id)


@app.post("/api/email/deliveries/<int:delivery_id>/retry")
@admin_required
def retry_email_delivery(delivery_id):
    delivery = get_db().execute(
        """
        SELECT email_deliveries.*,users.email AS current_email,users.active AS user_active
        FROM email_deliveries
        LEFT JOIN users ON users.id=email_deliveries.user_id
        WHERE email_deliveries.id=?
        """,
        (delivery_id,),
    ).fetchone()
    if not delivery:
        return message("找不到此寄送紀錄", 404)
    if delivery["status"] != "failed":
        return message("只有寄送失敗的通知可以重新傳送", 409)

    if delivery["notification_type"] == "password_reset":
        if not delivery["user_id"] or not delivery["user_active"]:
            return message("帳戶不存在或已停用，無法重新傳送", 409)
        user = get_db().execute(
            "SELECT id,email FROM users WHERE id=? AND active=1",
            (delivery["user_id"],),
        ).fetchone()
        if not user or not EMAIL_PATTERN.fullmatch(str(user["email"] or "")):
            return message("帳戶尚未設定有效的電子郵件", 409)
        sent, _, new_delivery_id, reason = deliver_password_reset(user, delivery_id)
    elif delivery["notification_type"] == "test_email":
        recipient = delivery["recipient"]
        sent, new_delivery_id, reason = deliver_test_email(
            recipient, delivery["user_id"], delivery_id
        )
    else:
        return message("此通知類型目前不支援重新傳送", 409)

    if not sent:
        return jsonify(ok=False, message=reason, delivery_id=new_delivery_id), 502
    return jsonify(ok=True, message="通知已重新傳送", delivery_id=new_delivery_id)


@app.get("/database")
@admin_required
def database_report():
    return render_template("database.html")


@app.get("/api/database/overview")
@admin_required
def api_database_overview():
    return jsonify(ok=True, database=sqlite_database_overview())


@app.post("/api/database/report-sample")
@admin_required
def create_database_report_sample():
    """建立一筆可在報告中展示 INSERT -> COMMIT -> SELECT 的測試事件。"""
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "purpose": "SQLite 報告展示",
        "process": ["Flask 接收資料", "SQLite INSERT", "COMMIT 儲存", "SELECT 顯示"],
        "created_by": session.get("user_name", "系統管理員"),
    }
    cursor = get_db().execute(
        """
        INSERT INTO communication_events
          (source,device_id,event_type,payload,received_at)
        VALUES (?,?,?,?,?)
        """,
        (
            "report_demo",
            "REPORT-SQLITE-001",
            "sqlite_insert_demo",
            json.dumps(payload, ensure_ascii=False),
            timestamp,
        ),
    )
    get_db().commit()
    row = get_db().execute(
        """
        SELECT id,source,device_id,event_type,payload,received_at
        FROM communication_events WHERE id=?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return jsonify(
        ok=True,
        message="測試資料已寫入 safeguard.db",
        sql=(
            "INSERT INTO communication_events "
            "(source, device_id, event_type, payload, received_at) VALUES (?, ?, ?, ?, ?)"
        ),
        data=dict(row),
    ), 201


@app.get("/api/summary")
@login_required
def api_summary():
    db = get_db()
    return jsonify(
        people=db.execute("SELECT COUNT(*) FROM people").fetchone()[0],
        risks=db.execute(
            "SELECT COUNT(*) FROM people WHERE device_status!='等待資料' AND risk!='低風險'"
        ).fetchone()[0],
        ppe_alerts=db.execute(
            "SELECT COUNT(*) FROM people WHERE device_status!='等待資料' AND (helmet=0 OR vest=0)"
        ).fetchone()[0],
        cameras=db.execute("SELECT COUNT(*) FROM monitoring_devices").fetchone()[0],
        cameras_online=db.execute(
            "SELECT COUNT(*) FROM monitoring_devices WHERE status='正常'"
        ).fetchone()[0],
    )


@app.get("/api/monitoring-devices")
@login_required
def api_monitoring_devices():
    return jsonify(rows("SELECT * FROM monitoring_devices ORDER BY id"))


@app.post("/api/monitoring-devices")
@login_required
def create_monitoring_device():
    data = request.get_json(force=True)
    device_id = str(data.get("id") or data.get("device_id") or "").strip().upper()
    location = str(data.get("location", "")).strip()
    stream_url = str(data.get("stream_url", "")).strip()
    if not device_id or not location:
        return message("請填寫裝置編號與位置")
    if not re.fullmatch(r"[A-Z0-9_-]{2,50}", device_id):
        return message("裝置編號只能使用英文字母、數字、連字號或底線")
    if stream_url and not re.match(r"^https?://", stream_url, re.IGNORECASE):
        return message("串流網址必須以 http:// 或 https:// 開頭")
    try:
        get_db().execute(
            """
            INSERT INTO monitoring_devices (id,location,status,last_seen,stream_url,created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                device_id, location, "等待連線", "", stream_url,
                datetime.now().astimezone().isoformat(timespec="seconds"),
            ),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return message("此監控設備編號已存在", 409)
    return jsonify(ok=True, id=device_id)


@app.put("/api/monitoring-devices/<device_id>")
@login_required
def update_monitoring_device(device_id):
    data = request.get_json(force=True)
    location = str(data.get("location", "")).strip()
    stream_url = str(data.get("stream_url", "")).strip()
    if not location:
        return message("請填寫位置")
    if stream_url and not re.match(r"^https?://", stream_url, re.IGNORECASE):
        return message("串流網址必須以 http:// 或 https:// 開頭")
    cursor = get_db().execute(
        "UPDATE monitoring_devices SET location=?,stream_url=? WHERE id=?",
        (location, stream_url, device_id.upper()),
    )
    get_db().commit()
    if not cursor.rowcount:
        return message("找不到監控設備", 404)
    return jsonify(ok=True)


@app.delete("/api/monitoring-devices/<device_id>")
@login_required
def delete_monitoring_device(device_id):
    cursor = get_db().execute(
        "DELETE FROM monitoring_devices WHERE id=?",
        (device_id.upper(),),
    )
    get_db().commit()
    if not cursor.rowcount:
        return message("找不到監控設備", 404)
    return jsonify(ok=True)


@app.get("/api/areas")
@login_required
def api_areas():
    result = rows("SELECT id,name,created_at FROM areas ORDER BY id")
    for area in result:
        area["stations"] = rows(
            """
            SELECT id,name,area_id,x,y,z,status,last_seen,source,created_at
            FROM base_stations WHERE area_id=? ORDER BY id
            """,
            (area["id"],),
        )
        area["external_station_count"] = sum(
            1 for station in area["stations"] if station["source"] == "external"
        )
        area["last_import"] = max(
            (station["last_seen"] for station in area["stations"] if station["last_seen"]),
            default="",
        )
        area["people_count"] = get_db().execute(
            "SELECT COUNT(*) FROM people WHERE area=?",
            (area["name"],),
        ).fetchone()[0]
        area["alert_count"] = get_db().execute(
            "SELECT COUNT(*) FROM people WHERE area=? AND risk!='低風險'",
            (area["name"],),
        ).fetchone()[0]
    return jsonify(result)


@app.post("/api/areas")
@login_required
def create_area():
    data = request.get_json(force=True)
    name = str(data.get("name", "")).strip()
    if not name:
        return message("請填寫區域名稱")
    if len(name) > 100:
        return message("區域名稱不可超過 100 個字")
    try:
        cursor = get_db().execute(
            "INSERT INTO areas (name,created_at) VALUES (?,?)",
            (name, datetime.now().astimezone().isoformat(timespec="seconds")),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return message("此區域名稱已存在", 409)
    return jsonify(ok=True, id=cursor.lastrowid)


@app.delete("/api/areas/<int:area_id>")
@login_required
def delete_area(area_id):
    area = get_db().execute(
        "SELECT name FROM areas WHERE id=?",
        (area_id,),
    ).fetchone()
    if not area:
        return message("找不到區域", 404)

    station_count = get_db().execute(
        "SELECT COUNT(*) AS count FROM base_stations WHERE area_id=?",
        (area_id,),
    ).fetchone()["count"]
    get_db().execute("DELETE FROM base_stations WHERE area_id=?", (area_id,))
    get_db().execute("DELETE FROM areas WHERE id=?", (area_id,))
    get_db().commit()
    return jsonify(ok=True, deleted_stations=station_count)


@app.post("/api/base-stations")
@login_required
def create_base_station():
    data = request.get_json(force=True)
    name = str(data.get("name", "")).strip()
    try:
        area_id = int(data.get("area_id"))
        x = float(data.get("x", 0))
        y = float(data.get("y", 0))
        z = float(data.get("z", 0))
    except (TypeError, ValueError):
        return message("區域或座標格式不正確")
    if not name:
        return message("請填寫基站名稱")
    if not get_db().execute("SELECT 1 FROM areas WHERE id=?", (area_id,)).fetchone():
        return message("找不到所屬區域", 404)
    station_count = get_db().execute(
        "SELECT COUNT(*) FROM base_stations WHERE area_id=?",
        (area_id,),
    ).fetchone()[0]
    if station_count >= 4:
        return message("每個區域固定最多 4 個 UWB 基站", 409)
    station_id = "B-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
    get_db().execute(
        """
        INSERT INTO base_stations (id,name,area_id,x,y,z,created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            station_id, name, area_id, x, y, z,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        ),
    )
    get_db().commit()
    return jsonify(ok=True, id=station_id)


@app.delete("/api/base-stations/<station_id>")
@login_required
def delete_base_station(station_id):
    cursor = get_db().execute(
        "DELETE FROM base_stations WHERE id=?",
        (station_id,),
    )
    get_db().commit()
    if not cursor.rowcount:
        return message("找不到基站", 404)
    return jsonify(ok=True)


@app.get("/api/people")
@login_required
def api_people():
    return jsonify(rows("SELECT * FROM people ORDER BY id"))


@app.post("/api/people")
@login_required
def create_person():
    data = request.get_json(force=True)
    employee_name = str(data.get("employee_name", "")).strip()
    device_name = str(data.get("device_name") or data.get("name") or "").strip()
    legacy_id = str(data.get("id", "")).strip().upper()
    if legacy_id and device_name and not employee_name:
        try:
            get_db().execute(
                """
                INSERT INTO people
                  (id,name,employee_name,area,x,y,z,helmet,vest,battery,risk,device_status,last_seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    legacy_id, device_name, "未綁定", str(data.get("area", "")).strip(),
                    float(data.get("x", 0)), float(data.get("y", 0)), float(data.get("z", 0)),
                    parse_bool(data.get("helmet"), default=True),
                    parse_bool(data.get("vest"), default=True),
                    max(0, min(100, int(data.get("battery", 100)))),
                    str(data.get("risk", "低風險")), "等待資料", "",
                ),
            )
            get_db().commit()
        except (TypeError, ValueError):
            return message("座標或電量格式不正確")
        except sqlite3.IntegrityError:
            return message("此裝置編號已存在", 409)
        return jsonify(ok=True, id=legacy_id)
    if not employee_name or not device_name:
        return message("請填寫員工姓名與裝置名稱")
    existing = get_db().execute(
        "SELECT id,employee_name FROM people WHERE lower(name)=lower(?) LIMIT 1",
        (device_name,),
    ).fetchone()
    if existing:
        if existing["employee_name"] in {"", "未綁定"}:
            get_db().execute(
                "UPDATE people SET employee_name=? WHERE id=?",
                (employee_name, existing["id"]),
            )
            get_db().commit()
            return jsonify(ok=True, id=existing["id"])
        return message("此裝置名稱已綁定其他員工", 409)
    person_id = "MANUAL-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
    try:
        get_db().execute(
            """
            INSERT INTO people
              (id,name,employee_name,x,y,z,helmet,vest,battery,risk,device_status,last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id, device_name, employee_name, 0, 0, 0,
                0, 0, 0, "低風險", "等待資料", "",
            ),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return message("此裝置編號已存在", 409)
    return jsonify(ok=True)


@app.put("/api/people/<person_id>")
@login_required
def update_person(person_id):
    data = request.get_json(force=True)
    allowed = {
        "employee_name", "name", "area", "helmet", "vest",
        "x", "y", "z", "battery", "risk", "device_status",
    }
    changes = {key: data[key] for key in allowed if key in data}
    if not changes:
        return message("沒有可更新的資料")
    if "risk" in changes and changes["risk"] not in ("低風險", "注意", "中高風險"):
        return message("風險值不正確")
    if "employee_name" in changes and not str(changes["employee_name"]).strip():
        return message("員工姓名不可空白")
    if "name" in changes and not str(changes["name"]).strip():
        return message("裝置名稱不可空白")
    if "helmet" in changes:
        changes["helmet"] = parse_bool(changes["helmet"])
    if "vest" in changes:
        changes["vest"] = parse_bool(changes["vest"])
    sql = ", ".join(f"{key}=?" for key in changes)
    cursor = get_db().execute(f"UPDATE people SET {sql} WHERE id=?", (*changes.values(), person_id))
    get_db().commit()
    if not cursor.rowcount:
        return message("找不到人員", 404)
    return jsonify(ok=True)


@app.delete("/api/people/<person_id>")
@login_required
def delete_person(person_id):
    cursor = get_db().execute("DELETE FROM people WHERE id=?", (person_id,))
    get_db().commit()
    if not cursor.rowcount:
        return message("找不到人員資料", 404)
    return jsonify(ok=True)


@app.post("/api/people/import")
@login_required
def import_people():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return message("請選擇 CSV 檔案")
    raw = uploaded.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp950")
        except UnicodeDecodeError:
            return message("CSV 編碼請使用 UTF-8 或繁體中文 Big5")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return message("CSV 缺少欄位名稱")
    aliases = {
        "id": ("裝置編號", "id", "ID", "device_id"),
        "employee_name": ("員工姓名", "人員", "姓名", "employee_name"),
        "name": ("裝置名稱", "name", "device_name"),
        "x": ("x", "X", "座標X"), "y": ("y", "Y", "座標Y"), "z": ("z", "Z", "座標Z"), "helmet": ("安全帽", "helmet"),
        "vest": ("背心", "vest"), "battery": ("電量", "battery"), "risk": ("風險", "risk"),
    }
    headers = {header.strip(): header for header in reader.fieldnames if header}
    def get_value(row, field, default=""):
        for alias in aliases[field]:
            if alias in headers:
                return row.get(headers[alias], default)
        return default
    if not any(alias in headers for alias in aliases["id"]) or not any(alias in headers for alias in aliases["name"]):
        return message("CSV 必須包含「裝置編號」與「裝置名稱」欄位")
    imported, skipped = 0, []
    for line, row in enumerate(reader, start=2):
        person_id = str(get_value(row, "id")).strip().upper()
        name = str(get_value(row, "name")).strip()
        employee_name = str(get_value(row, "employee_name", "")).strip()
        if not person_id or not name:
            skipped.append(line)
            continue
        try:
            x = float(get_value(row, "x", 0) or 0)
            y = float(get_value(row, "y", 0) or 0)
            z = float(get_value(row, "z", 0) or 0)
            battery = max(0, min(100, int(get_value(row, "battery", 100) or 100)))
            risk = str(get_value(row, "risk", "低風險") or "低風險").strip()
            if risk not in ("低風險", "注意", "中高風險"):
                risk = "低風險"
            get_db().execute("""
                INSERT INTO people
                  (id,name,employee_name,x,y,z,helmet,vest,battery,risk,device_status,last_seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  employee_name=CASE
                    WHEN excluded.employee_name='' THEN people.employee_name
                    ELSE excluded.employee_name
                  END,
                  x=excluded.x,y=excluded.y,z=excluded.z,
                  helmet=excluded.helmet,vest=excluded.vest,
                  battery=excluded.battery,risk=excluded.risk,
                  device_status=excluded.device_status,last_seen=excluded.last_seen
            """, (
                person_id, name, employee_name, x, y, z,
                parse_bool(get_value(row, "helmet", 1)),
                parse_bool(get_value(row, "vest", 1)),
                battery, risk, "連線中",
                datetime.now().astimezone().isoformat(timespec="seconds"),
            ))
            imported += 1
        except (TypeError, ValueError):
            skipped.append(line)
    get_db().commit()
    return jsonify(ok=True, imported=imported, skipped=skipped)


@app.get("/api/users")
@admin_required
def api_users():
    query = request.args.get("q", "").strip()
    sql, values = "SELECT id,account,name,phone,email,role,active,created_at,last_active FROM users", []
    if query:
        sql += " WHERE account LIKE ? OR name LIKE ? OR phone LIKE ? OR email LIKE ?"
        values = [f"%{query}%"] * 4
    return jsonify(rows(sql + " ORDER BY id DESC", values))


@app.post("/api/users")
@admin_required
def create_user():
    data = request.get_json(force=True)
    for field, label in (("account", "帳號"), ("name", "姓名"), ("phone", "電話"), ("email", "電子郵件"), ("password", "密碼")):
        if not str(data.get(field, "")).strip():
            return message(f"請填寫{label}")
    email = str(data["email"]).strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        return message("請輸入有效的電子郵件，例如 c113118118@nkust.edu.tw")
    if get_db().execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone():
        return message("此電子郵件已綁定其他帳戶", 409)
    role = str(data.get("role", "一般使用者")).strip()
    if role not in {"管理員", "一般使用者"}:
        return message("帳戶角色不正確")
    try:
        get_db().execute(
            "INSERT INTO users (account,name,password,phone,email,role,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                data["account"].strip(),
                data["name"].strip(),
                generate_password_hash(data["password"]),
                data["phone"].strip(),
                email,
                role,
                datetime.now().strftime("%Y-%m-%d"),
            ),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return message("此帳號已存在", 409)
    return jsonify(ok=True)


@app.put("/api/users/<int:user_id>")
@admin_required
def edit_user(user_id):
    data = request.get_json(force=True)
    target = get_db().execute(
        "SELECT id,role,active FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not target:
        return message("找不到此帳戶", 404)

    fields = {key: data[key] for key in ("name", "phone", "email", "active", "role") if key in data}
    if "email" in fields:
        fields["email"] = str(fields["email"]).strip().lower()
        if not EMAIL_PATTERN.fullmatch(fields["email"]):
            return message("請輸入有效的電子郵件，例如 c113118118@nkust.edu.tw")
        duplicate = get_db().execute(
            "SELECT 1 FROM users WHERE lower(email)=? AND id!=?",
            (fields["email"], user_id),
        ).fetchone()
        if duplicate:
            return message("此電子郵件已綁定其他帳戶", 409)
    if "role" in fields and fields["role"] not in {"管理員", "一般使用者"}:
        return message("帳戶角色不正確")
    if user_id == session["user_id"] and (
        fields.get("active") == 0 or fields.get("role") == "一般使用者"
    ):
        return message("不能停用自己或移除自己的管理員權限")
    removing_active_admin = (
        target["role"] == "管理員"
        and target["active"]
        and (fields.get("active") == 0 or fields.get("role") == "一般使用者")
    )
    if removing_active_admin:
        active_admins = get_db().execute(
            "SELECT COUNT(*) FROM users WHERE role='管理員' AND active=1"
        ).fetchone()[0]
        if active_admins <= 1:
            return message("系統至少需要保留一個啟用中的管理員")
    manual_password_reset = bool(data.get("password"))
    if manual_password_reset:
        if len(str(data["password"])) < 6:
            return message("管理員設定的密碼至少需要 6 個字元")
        fields["password"] = generate_password_hash(data["password"])
    if not fields:
        return message("沒有資料可更新")
    sql = ", ".join(f"{key}=?" for key in fields)
    get_db().execute(f"UPDATE users SET {sql} WHERE id=?", (*fields.values(), user_id))
    if manual_password_reset:
        get_db().execute(
            "UPDATE password_reset_tokens SET used_at=? WHERE user_id=? AND used_at=''",
            (datetime.now().astimezone().isoformat(timespec="seconds"), user_id),
        )
    get_db().commit()
    if manual_password_reset:
        record_communication_event(
            "admin", "password_reset_completed", {"method": "manual"}, str(user_id)
        )
    return jsonify(ok=True)


@app.delete("/api/users/<int:user_id>")
@admin_required
def delete_user(user_id):
    if user_id == session["user_id"]:
        return message("不能刪除目前登入的帳號")
    target = get_db().execute(
        "SELECT role,active FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not target:
        return message("找不到此帳戶", 404)
    if target["role"] == "管理員" and target["active"]:
        active_admins = get_db().execute(
            "SELECT COUNT(*) FROM users WHERE role='管理員' AND active=1"
        ).fetchone()[0]
        if active_admins <= 1:
            return message("系統至少需要保留一個啟用中的管理員")
    get_db().execute("DELETE FROM users WHERE id=?", (user_id,))
    get_db().commit()
    return jsonify(ok=True)


@app.post("/api/videos")
@login_required
def upload_video():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return message("請選擇影片檔案")
    filename = secure_filename(uploaded.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in VIDEO_EXTENSIONS:
        return message("僅支援 MP4、WebM、MOV、M4V、OGG 影片")
    base, ext = os.path.splitext(filename)
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{base[:80]}{ext.lower()}"
    uploaded.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return jsonify(ok=True, filename=filename)


@app.get("/api/videos")
@login_required
def list_videos():
    videos = []
    for filename in sorted(os.listdir(app.config["UPLOAD_FOLDER"]), reverse=True):
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension in VIDEO_EXTENSIONS:
            videos.append({"filename": filename, "url": url_for("uploaded_video", filename=filename)})
    return jsonify(videos)


@app.get("/uploads/<path:filename>")
@login_required
def uploaded_video(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, conditional=True)


@app.route("/api/iot/uwb", methods=["GET", "POST", "OPTIONS"])
def api_iot_uwb():
    """UWB 感測端：HTTP POST JSON；也可由 MQTT 共用相同資料格式。"""
    if request.method == "OPTIONS":
        return ("", 204)
    if request.method == "GET":
        return jsonify(
            ok=True,
            endpoint="/api/iot/uwb",
            protocol={"transport": ["HTTP POST", "MQTT"], "format": "JSON", "mqtt_topic": app.config["MQTT_TOPIC"]},
            sample={
                "device_id": "W-001", "name": "Helmet Tag W-001",
                "x": 12.5, "y": 8.2, "z": 1.4,
                "helmet": True, "vest": True, "battery": 88,
                "risk": "低風險", "status": "online",
                "timestamp": "2026-07-19T10:00:00+08:00",
            },
            recent=recent_communication_events("uwb", request.args.get("limit", 20)),
        )
    denied = check_iot_api_key()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if data is None:
        return message("Content-Type 必須是 application/json，且內容需為有效 JSON")
    try:
        normalized = process_uwb_payload(data, source="HTTP")
    except ValueError as exc:
        return message(str(exc))
    return jsonify(ok=True, message="UWB 資料接收成功", data=normalized), 201


@app.route("/api/iot/safety-alerts", methods=["GET", "POST", "OPTIONS"])
def api_iot_safety_alerts():
    """讓未來的 YOLO、UWB 或其他職安服務直接送入即時危險警報。"""
    if request.method == "OPTIONS":
        return ("", 204)
    if request.method == "GET":
        return jsonify(
            ok=True,
            endpoint="/api/iot/safety-alerts",
            method="POST",
            sample={
                "source_system": "YOLO",
                "device_id": "CAM-01",
                "location": "工地入口",
                "alert_type": "ppe_violation",
                "message": "偵測到人員未配戴安全帽",
                "detail": "人員 W-001・信心度 97%",
                "severity": "serious",
                "timestamp": "2026-08-09T14:28:32+08:00",
                "metadata": {"person_id": "W-001"},
            },
        )
    denied = check_iot_api_key()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return message("Content-Type 必須是 application/json，且內容需為 JSON 物件")
    source_system = str(data.get("source_system") or data.get("source") or "").strip()
    message_text = str(data.get("message") or data.get("alert_message") or "").strip()
    if not source_system or not message_text:
        return message("請提供 source_system 與 message")
    alert_id = record_safety_alert(
        source_system,
        data.get("device_id", ""),
        data.get("location") or data.get("area") or "未設定位置",
        data.get("alert_type") or data.get("event_type") or "danger_event",
        message_text,
        data.get("detail", ""),
        data.get("severity", "attention"),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else data,
        occurred_at=data.get("timestamp"),
    )
    alert = dict(
        get_db().execute(
            """
            SELECT id,source_system,device_id,location,alert_type,message,detail,
                   severity,status,occurrences,occurred_at,resolved_at
            FROM safety_alerts WHERE id=?
            """,
            (alert_id,),
        ).fetchone()
    )
    record_communication_event(
        "safety_alert", "danger_event", data, str(data.get("device_id", ""))
    )
    return jsonify(ok=True, message="危險警報已建立", data=alert), 201


@app.route("/api/iot/base-stations", methods=["GET", "POST", "OPTIONS"])
def api_iot_base_stations():
    """外部 UWB 系統：每個既有區域一次匯入固定四個基站及座標。"""
    if request.method == "OPTIONS":
        return ("", 204)
    if request.method == "GET":
        return jsonify(
            ok=True,
            endpoint="/api/iot/base-stations",
            protocol={"transport": ["HTTP POST"], "format": "JSON", "stations_per_area": 4},
            sample={
                "area": "A 棟 1 樓",
                "timestamp": "2026-07-26T10:00:00+08:00",
                "stations": [
                    {"id": "B-01", "name": "基站 B-01", "x": 0, "y": 0, "z": 2.5, "status": "online"},
                    {"id": "B-02", "name": "基站 B-02", "x": 20, "y": 0, "z": 2.5, "status": "online"},
                    {"id": "B-03", "name": "基站 B-03", "x": 20, "y": 15, "z": 2.5, "status": "online"},
                    {"id": "B-04", "name": "基站 B-04", "x": 0, "y": 15, "z": 2.5, "status": "online"},
                ],
            },
            recent=recent_communication_events(
                "uwb_base_stations",
                request.args.get("limit", 20),
            ),
        )

    denied = check_iot_api_key()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return message("Content-Type 必須是 application/json，且內容需為 JSON 物件")
    area_id = data.get("area_id")
    area_name = str(data.get("area") or data.get("area_name") or "").strip()
    if area_id not in (None, ""):
        try:
            area = get_db().execute(
                "SELECT id,name FROM areas WHERE id=?",
                (int(area_id),),
            ).fetchone()
        except (TypeError, ValueError):
            return message("area_id 格式不正確")
    else:
        area = get_db().execute(
            "SELECT id,name FROM areas WHERE name=?",
            (area_name,),
        ).fetchone()
    if not area:
        return message("找不到設定區域，請先建立區域", 404)

    stations = data.get("stations")
    if not isinstance(stations, list) or len(stations) != 4:
        return message("每個區域必須一次提供正好 4 個 UWB 基站")
    normalized_stations = []
    station_ids = set()
    timestamp = str(
        data.get("timestamp")
        or datetime.now().astimezone().isoformat(timespec="seconds")
    )
    for index, station in enumerate(stations, start=1):
        if not isinstance(station, dict):
            return message(f"第 {index} 個基站資料格式不正確")
        station_id = str(station.get("id") or station.get("station_id") or "").strip().upper()
        if not station_id or station_id in station_ids:
            return message("4 個基站必須提供不重複的 id")
        try:
            x = float(station.get("x"))
            y = float(station.get("y"))
            z = float(station.get("z", 0))
        except (TypeError, ValueError):
            return message(f"基站 {station_id} 的 x、y、z 格式不正確")
        raw_status = str(station.get("status", "online")).strip().lower()
        status = "離線" if raw_status in {"offline", "off", "0", "離線"} else "正常"
        station_ids.add(station_id)
        normalized_stations.append(
            {
                "id": station_id,
                "name": str(station.get("name") or station_id).strip(),
                "x": x,
                "y": y,
                "z": z,
                "status": status,
            }
        )

    db = get_db()
    db.execute("DELETE FROM base_stations WHERE area_id=?", (area["id"],))
    for station in normalized_stations:
        db.execute(
            """
            INSERT INTO base_stations
              (id,name,area_id,x,y,z,status,last_seen,source,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name,area_id=excluded.area_id,
              x=excluded.x,y=excluded.y,z=excluded.z,
              status=excluded.status,last_seen=excluded.last_seen,source='external'
            """,
            (
                station["id"], station["name"], area["id"],
                station["x"], station["y"], station["z"],
                station["status"], timestamp, "external", timestamp,
            ),
        )
    db.commit()
    event_payload = {
        "area_id": area["id"],
        "area": area["name"],
        "stations": normalized_stations,
        "timestamp": timestamp,
    }
    record_communication_event(
        "uwb_base_stations",
        "base_station_sync",
        event_payload,
        str(area["id"]),
    )
    return jsonify(
        ok=True,
        message="4 個 UWB 基站資料同步成功",
        data=event_payload,
    ), 201


@app.route("/api/iot/camera", methods=["GET", "POST", "OPTIONS"])
def api_iot_camera():
    """影像端：攝影機/辨識服務以 RESTful HTTP POST 傳送 JSON 結果。"""
    if request.method == "OPTIONS":
        return ("", 204)
    if request.method == "GET":
        return jsonify(
            ok=True, endpoint="/api/iot/camera",
            protocol={"transport": "HTTP RESTful API", "method": "POST", "format": "JSON"},
            sample={
                "camera_id": "CAM-01", "location": "工地入口", "status": "online",
                "detections": [{"device_id": "W-001", "helmet": True, "vest": False, "confidence": 0.97}],
                "timestamp": "2026-07-19T10:00:00+08:00",
            },
            recent=recent_communication_events("camera", request.args.get("limit", 20)),
        )
    denied = check_iot_api_key()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return message("Content-Type 必須是 application/json，且內容需為 JSON 物件")
    camera_id = str(data.get("camera_id", "")).strip()
    if not camera_id:
        return message("缺少 camera_id")
    detections = data.get("detections", [])
    if not isinstance(detections, list):
        return message("detections 必須是陣列")
    camera_id_upper = camera_id.upper()
    existing_camera = get_db().execute(
        "SELECT location FROM monitoring_devices WHERE id=?",
        (camera_id_upper,),
    ).fetchone()
    incoming_location = str(data.get("location", "")).strip()
    camera_location = (
        incoming_location
        or (existing_camera["location"] if existing_camera else "")
        or "未設定"
    )
    normalized = {
        "camera_id": camera_id,
        "location": camera_location,
        "status": str(data.get("status", "online")),
        "detections": detections,
        "image_url": data.get("image_url", ""),
        "timestamp": str(data.get("timestamp") or datetime.now().astimezone().isoformat(timespec="seconds")),
    }
    raw_status = normalized["status"].strip().lower()
    display_status = "離線" if raw_status in {"offline", "off", "0", "離線"} else "正常"
    get_db().execute(
        """
        INSERT INTO monitoring_devices (id,location,status,last_seen,created_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          location=excluded.location,status=excluded.status,last_seen=excluded.last_seen
        """,
        (
            camera_id_upper, camera_location, display_status,
            normalized["timestamp"], normalized["timestamp"],
        ),
    )
    get_db().commit()
    if display_status == "離線":
        record_system_error(
            "YOLO 攝影機",
            f"{camera_id_upper} 影像串流離線",
            f"位置：{camera_location}；最後回報：{normalized['timestamp']}",
        )
    normalized["safety_alert_ids"] = record_camera_safety_alerts(
        camera_id_upper,
        camera_location,
        detections,
        normalized["timestamp"],
        normalized["image_url"],
    )
    alert_ids = list(dict.fromkeys(normalized["safety_alert_ids"]))
    if alert_ids:
        placeholders = ",".join("?" for _ in alert_ids)
        normalized["line_notifications"] = rows(
            f"""
            SELECT alert_id,status,attempts,http_status,failure_reason,sent_at
            FROM line_alert_deliveries
            WHERE alert_id IN ({placeholders})
            ORDER BY id
            """,
            tuple(alert_ids),
        )
    else:
        normalized["line_notifications"] = []
    record_communication_event("camera", "detection_update", normalized, camera_id)
    return jsonify(ok=True, message="影像辨識資料接收成功", data=normalized), 201


def line_event_user_name(event):
    """從 LINE postback 事件取得接收者名稱；無法查詢時使用遮罩 ID。"""
    source = event.get("source", {}) if isinstance(event, dict) else {}
    user_id = str(source.get("userId") or "").strip()
    if not user_id:
        return "LINE 使用者", ""
    source_type = source.get("type")
    if source_type == "group" and source.get("groupId"):
        profile_path = (
            f"group/{quote(str(source['groupId']), safe='')}/member/"
            f"{quote(user_id, safe='')}"
        )
    elif source_type == "room" and source.get("roomId"):
        profile_path = (
            f"room/{quote(str(source['roomId']), safe='')}/member/"
            f"{quote(user_id, safe='')}"
        )
    else:
        profile_path = f"profile/{quote(user_id, safe='')}"
    try:
        profile = line_get_json(profile_path)
        display_name = str(profile.get("displayName") or "").strip()
        if display_name:
            return display_name[:80], user_id
    except Exception as exc:
        app.logger.info("無法取得 LINE 接收者名稱：%s", exc)
    return f"LINE 使用者 ···{user_id[-6:]}", user_id


def acknowledge_safety_alert_from_line(alert_id, acknowledged_by, user_id=""):
    """將警報標示為已由 LINE 接收；同一事件只記錄第一位接收者。"""
    db = get_db()
    alert = db.execute(
        "SELECT id,message,status,acknowledged_at,acknowledged_by FROM safety_alerts WHERE id=?",
        (alert_id,),
    ).fetchone()
    if not alert:
        return {"ok": False, "message": f"找不到警報 #{alert_id}"}
    if alert["status"] == "resolved":
        return {"ok": True, "message": f"警報 #{alert_id} 已完成處理", "already": True}
    if alert["acknowledged_at"]:
        by = alert["acknowledged_by"] or "其他管理員"
        return {
            "ok": True,
            "message": f"警報 #{alert_id} 已由 {by} 接收",
            "already": True,
        }

    acknowledged_at = datetime.now().astimezone().isoformat(timespec="seconds")
    cursor = db.execute(
        """
        UPDATE safety_alerts
        SET acknowledged_at=?,acknowledged_by=?,acknowledged_user_id=?
        WHERE id=? AND status='open' AND COALESCE(acknowledged_at,'')=''
        """,
        (
            acknowledged_at,
            str(acknowledged_by or "LINE 使用者")[:80],
            str(user_id or "")[:80],
            alert_id,
        ),
    )
    db.commit()
    if cursor.rowcount != 1:
        current = db.execute(
            "SELECT acknowledged_by FROM safety_alerts WHERE id=?", (alert_id,)
        ).fetchone()
        by = current["acknowledged_by"] if current else "其他管理員"
        return {
            "ok": True,
            "message": f"警報 #{alert_id} 已由 {by} 接收",
            "already": True,
        }
    record_communication_event(
        "line",
        "safety_alert_acknowledged",
        {
            "alert_id": alert_id,
            "acknowledged_by": acknowledged_by,
            "acknowledged_at": acknowledged_at,
        },
        str(user_id or ""),
    )
    return {
        "ok": True,
        "message": f"已接收警報 #{alert_id}：{alert['message']}",
        "already": False,
        "acknowledged_at": acknowledged_at,
    }


def reply_line_text(reply_token, text):
    if not reply_token or not app.config["LINE_CHANNEL_ACCESS_TOKEN"]:
        return
    try:
        line_post(
            "reply",
            {
                "replyToken": reply_token,
                "messages": [{"type": "text", "text": str(text)[:5000]}],
            },
        )
    except Exception as exc:
        app.logger.warning("LINE 回覆失敗：%s", exc)


@app.route("/api/line/webhook", methods=["GET", "POST"])
def line_webhook():
    """LINE Bot：LINE 官方伺服器以 HTTP POST JSON 呼叫此 webhook。"""
    if request.method == "GET":
        return jsonify(
            ok=True, endpoint="/api/line/webhook",
            protocol={"transport": "HTTPS POST", "format": "JSON", "signature_header": "X-Line-Signature"},
            configured=line_acknowledgement_configured(),
        )
    raw_body = request.get_data(cache=True)
    if not verify_line_signature(raw_body, request.headers.get("X-Line-Signature", "")):
        return message("LINE webhook 簽章驗證失敗", 401)
    data = request.get_json(silent=True) or {}
    events = data.get("events", []) if isinstance(data, dict) else []
    record_communication_event("line", "webhook", data)
    for event in events:
        if event.get("type") == "postback":
            postback_data = parse_qs(
                str(event.get("postback", {}).get("data") or ""),
                keep_blank_values=True,
            )
            action = (postback_data.get("action") or [""])[0]
            raw_alert_id = (postback_data.get("alert_id") or [""])[0]
            if action == "ack_safety_alert" and str(raw_alert_id).isdigit():
                acknowledged_by, user_id = line_event_user_name(event)
                result = acknowledge_safety_alert_from_line(
                    int(raw_alert_id), acknowledged_by, user_id
                )
                reply_line_text(event.get("replyToken"), result["message"])
            continue
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text" and event.get("replyToken"):
            text = event["message"].get("text", "")
            reply_line_text(event["replyToken"], f"SafeGuard 已收到：{text}")
    return jsonify(ok=True)


@app.route("/api/line/notify", methods=["POST", "OPTIONS"])
def line_notify():
    """系統伺服器主動透過 LINE Messaging API 推播警示。"""
    if request.method == "OPTIONS":
        return ("", 204)
    denied = check_iot_api_key()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not str(data.get("message", "")).strip():
        return message("請提供 message")
    try:
        status = send_line_alert(data["message"], data.get("user_id"))
    except RuntimeError as exc:
        return message(str(exc), 503)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return message(f"LINE API 錯誤 {exc.code}: {detail}", 502)
    except urllib.error.URLError as exc:
        return message(f"無法連線 LINE API：{exc.reason}", 502)
    return jsonify(ok=True, message="LINE 警示已送出", status=status)


@app.get("/api/communication/status")
def communication_status():
    return jsonify(
        ok=True,
        uwb={
            "http": "/api/iot/uwb",
            "base_stations_http": "/api/iot/base-stations",
            "stations_per_area": 4,
            "mqtt_enabled": app.config["MQTT_ENABLED"],
            "mqtt_topic": app.config["MQTT_TOPIC"],
        },
        camera={"http": "/api/iot/camera"},
        safety_alerts={
            "http": "/api/iot/safety-alerts",
            "sources": ["YOLO", "UWB"],
            "cooldown_seconds": app.config["SAFETY_ALERT_COOLDOWN_SECONDS"],
        },
        line={
            "webhook": "/api/line/webhook",
            "notify": "/api/line/notify",
            "safety_alert_test": "/api/safety-alerts/line-test",
            "configured": line_alert_configured(),
            "acknowledgement_configured": line_acknowledgement_configured(),
            "safety_alert_cooldown_seconds": app.config["SAFETY_ALERT_COOLDOWN_SECONDS"],
        },
        security={"iot_api_key_enabled": bool(app.config["IOT_API_KEY"]), "cors_origin": app.config["CORS_ORIGIN"]},
    )


@app.get("/sample-people.csv")
@login_required
def sample_people_csv():
    content = "裝置編號,員工姓名,裝置名稱,x,y,z,安全帽,背心,電量,風險\nW-004,陳小華,Helmet Tag W-004,45,55,1.3,是,是,98,低風險\n"
    return Response("\ufeff" + content, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=people-import-sample.csv"})


if __name__ == "__main__":
    # host=0.0.0.0 才能讓同一個區域網路內的 ESP32、手機與其他電腦連線。
    start_mqtt_client()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
