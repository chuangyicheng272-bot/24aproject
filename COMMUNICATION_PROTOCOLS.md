# SafeGuard 通訊協定

## 系統資料流

1. 感測端：ESP32S3 安全帽 → Wi-Fi → HTTP POST 或 MQTT Broker → SafeGuard Flask
2. 影像端：攝影機／辨識服務 → HTTP RESTful API → SafeGuard Flask
3. 應用端：SafeGuard Flask → LINE Messaging API → 主管手機

所有資料交換以 JSON 為主。

## API 一覽

| 用途 | Method | Endpoint | Content-Type |
|---|---|---|---|
| UWB 上報 | POST | `/api/iot/uwb` | `application/json` |
| UWB 狀態/最新紀錄 | GET | `/api/iot/uwb` | — |
| 影像辨識上報 | POST | `/api/iot/camera` | `application/json` |
| 影像端狀態/最新紀錄 | GET | `/api/iot/camera` | — |
| LINE Webhook | POST | `/api/line/webhook` | `application/json` |
| LINE 主動警示 | POST | `/api/line/notify` | `application/json` |
| 通訊總覽 | GET | `/api/communication/status` | — |

## MQTT

- Broker：由 `MQTT_HOST`、`MQTT_PORT` 設定
- Topic：預設 `safeguard/uwb`
- Payload：與 `POST /api/iot/uwb` 完全相同的 JSON
- 啟用：`MQTT_ENABLED=true`
