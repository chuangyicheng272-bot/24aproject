# API 測試計畫

## 自動測試

執行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

涵蓋項目：

1. Anchor1 批次接收兩條腰帶，並產生兩筆 Flask 轉送。
2. Anchor1～Anchor4 沿用相同 `sequence_id`。
3. 拒絕非法 `anchor_id`、小於 0 或大於 4500 的 `distance_mm`。
4. 拒絕 Anchor payload 的舊版或非測距欄位。
5. 電量低於 20 產生 `battery_low`。
6. `last_seen` 超過 10 秒時回傳 `online: false` 與 `belt_offline`。
7. 腰帶狀態 payload 拒絕測距欄位。
8. `device_judgment.py` 不包含影像或穿戴辨識規則。

## 整合測試

確認 Flask `/api/uwb/range` 對每條腰帶各收到一筆 JSON，欄位為
`belt_id`、`sequence_id`、`anchor_id`、`timestamp`、`distance_mm`。同一輪
四個 Anchor 應使用相同 `sequence_id`，距離值直接以毫米保存，不轉換。

腰帶狀態應分別透過 `/api/belt/status` 上報。斷開腰帶上報超過 10 秒後，
查詢 `/api/belt/{belt_id}/status` 應得到 `online: false`。

> 舊版 `/api/locations` 測試計畫已停用；若從版本歷史查閱，請勿當作現行契約。
