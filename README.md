# UWB FastAPI／Flask 整合後端

系統資料流：

```text
ESP32 Anchor／智慧安全腰帶
  → FastAPI :8000（接收、驗證、設備狀態判斷）
  → Flask :5000（3D 定位、電子圍欄、SQLite、網頁儀表板）
```

## 本機啟動

安裝 `requirements.txt` 後，依序在不同終端執行：

```powershell
python app.py
python main.py
python safety_belt_tag_simulator.py
python anchor_simulator.py --anchor Anchor1
```

完整定位需另開終端，以相同方式啟動 Anchor2～Anchor4。腰帶模擬器同時在
`:5001` 提供模擬座標給 Anchor，並將電量與充電狀態送至 FastAPI。

FastAPI 預設將資料轉送至 `http://127.0.0.1:5000`。可在啟動 FastAPI 前設定：

```powershell
$env:FLASK_BASE_URL = "http://192.168.2.171:5000"
python main.py
```

未來 ESP32 應連到樹莓派的區域網路 IP，例如
`http://<樹莓派-IP>:8000/api/anchor/ranges`，而不是 ESP32 自己的
`127.0.0.1`。

## API 與資料格式

Anchor 將同一次測距循環的 `sequence_id` 原樣傳入；距離單位固定為毫米：

```json
{
  "sequence_id": 1024,
  "anchor_id": "Anchor1",
  "timestamp": 1781943343,
  "detected_belts": {
    "BELT-001": {"distance_mm": 1820},
    "BELT-002": {"distance_mm": 452}
  }
}
```

`POST /api/anchor/ranges` 接收後會以一次 HTTP 請求完整轉送至 Flask 的
`POST /api/uwb/range`，不拆分腰帶、不轉換單位，也不在 FastAPI 計算座標。

腰帶送至 `POST /api/belt/status` 的格式如下，不傳 `online`：

```json
{
  "belt_id": "BELT-001",
  "timestamp": 1781943343,
  "battery": 85,
  "charging": false
}
```

FastAPI 以實際收到資料的時間更新 `last_seen`，10 秒內視為 online，再加入
`online` 後完整轉送至 Flask 的 `POST /api/belt/status`。查詢
`GET /api/belt/{belt_id}/status` 時會即時計算連線狀態；電量低於 20 產生
`battery_low`，逾時產生 `belt_offline`。

Flask 未啟動或連線逾時時，FastAPI 仍保存收到的資料並回傳
`forward_status: "forward_error"`，不會因轉送例外而崩潰。

其他端點：`GET /health`（FastAPI）與 `GET /api/status`（Flask 儀表板資料）。

`legacy_uwb_simulator.py` 是舊格式工具，不供目前整合流程使用。
