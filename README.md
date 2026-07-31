# UWB FastAPI Backend

本專案以同一個 FastAPI app 提供兩個獨立資料模組：Anchor 只傳 UWB
測距資料；腰帶直接傳送電量與充電狀態。YOLO 與穿戴辨識不在本模組範圍內。

## 執行

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API

- `POST /api/anchor/ranges`：接收 Anchor 批次測距。
- `POST /api/belt/status`：接收腰帶裝置狀態。
- `GET /api/belt/{belt_id}/status`：查詢腰帶狀態與警示。
- `GET /health`：健康檢查。

Anchor 正式格式：

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

腰帶正式格式：

```json
{
  "belt_id": "BELT-001",
  "timestamp": 1781943343,
  "battery": 85,
  "charging": false
}
```

`sequence_id` 代表一次完整測距循環；同一循環的 Anchor1～Anchor4 必須
沿用來源提供的相同值，FastAPI 不產生或改寫它。距離及未來的座標欄位統一
使用毫米，本 API 不做單位轉換。

FastAPI 將 `detected_belts` 拆開，逐筆 POST 到
`http://192.168.2.171:5000/api/uwb/range`：

```json
{
  "belt_id": "BELT-001",
  "sequence_id": 1024,
  "anchor_id": "Anchor1",
  "timestamp": 1781943343,
  "distance_mm": 1820
}
```

腰帶不傳 `online`。後端以實際接收時間寫入 `last_seen`，查詢當下與
`last_seen` 相差不超過 10 秒時為 online，否則產生 `belt_offline` 警示。
電量低於 20 時產生 `battery_low` 警示。

Flask 端必須同步接收 `belt_id`、整數 `sequence_id`、`anchor_id`、Unix
`timestamp` 與毫米 `distance_mm`。不得在整合層轉回舊版欄位。

> 舊版格式曾將裝置、穿戴與公分測距混在單一 `/api/locations` payload；
> 該格式已停用，僅作為歷史說明。
