# ESP32-S3 UWB Anchor 模擬程式

目前尚未接上正式 Tag 韌體，`UwbManager` 使用固定測試值模擬 UWB 測距。
Anchor 只傳測距資料，不傳腰帶裝置狀態；YOLO 與穿戴辨識不在本模組範圍內。

## FastAPI 端點與格式

```text
POST http://BACKEND_PC_IP:8000/api/anchor/ranges
```

```json
{
  "sequence_id": 1024,
  "anchor_id": "Anchor1",
  "timestamp": 1781943343,
  "detected_belts": {
    "BELT-001": {"distance_mm": 1820}
  }
}
```

距離單位是毫米，程式與後端皆不做單位轉換。`detected_belts` 可包含多個
腰帶 ID。

## sequence_id 測試模式

`src/config.h` 的 `SEQUENCE_ID` 是暫時測試值。同一次完整測距循環中的
Anchor1、Anchor2、Anchor3、Anchor4 必須設定或接收到相同 `sequence_id`；
四個 Anchor 不可各自產生無法對應的值。正式韌體應由 Tag 封包提供每輪的新
`sequence_id`，Anchor 僅沿用該值。

## 設定與執行

在 `src/config.h` 設定 Wi-Fi、後端電腦 IP、Anchor ID 與測試腰帶 ID。
ESP32 上的 `localhost` 指向 ESP32 本身，不可作為後端位址。

```powershell
pio run
pio run -t upload
pio device monitor -b 115200
```

預期序列埠會顯示送出的新批次 JSON 與 HTTP 回應碼。

## 模組

- `UwbManager`：目前提供毫米測距模擬值，之後替換為 DW3000 資料。
- `PayloadBuilder`：建立 Anchor 批次 JSON。
- `BackendClient`：POST 到 FastAPI。
- `WiFiManager`：處理 Wi-Fi 連線。

腰帶的電量與充電狀態由腰帶本身另行傳到 `/api/belt/status`；`online` 由
FastAPI 根據 `last_seen` 計算。

> 舊版 ESP32 payload 已停用；版本歷史中的舊格式僅供追溯，不是現行契約。
