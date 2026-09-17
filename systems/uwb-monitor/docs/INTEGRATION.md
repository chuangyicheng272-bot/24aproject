# GitHub 合併交接

## 模組邊界

本模組負責 UWB 測距接收、3D 定位、腰帶狀態、危險區判定、歷史資料與監控頁面。前端目前放在 `app.py` 的 `PAGE` 字串內，並非獨立 templates/static 專案。

若共同專案已有 `app.py`，請先將本模組放在独立的 `safety_monitor/` 目錄交付，再由整合分支調整成 Blueprint 或獨立服務，避免直接覆蓋同名入口。現有測試使用 `import app`，移動後也需同步調整測試執行位置或匯入方式。

## API 交接

| 方法 | 路徑 | 用途 |
| --- | --- | --- |
| GET | `/` | 監控頁面 |
| GET | `/api/status` | 儀表板狀態 |
| POST | `/api/uwb/range` | 單一 Anchor 測距回報 |
| POST | `/api/belt/status` | 腰帶電量、充電及連線狀態 |
| PATCH | `/api/belt/<belt_id>` | 更新座標及狀態 |
| GET | `/api/history/<belt_id>` | 定位歷史 |
| GET | `/api/geofence-events` | 區域進出事件 |
| PATCH | `/api/geofence-events/<event_id>` | 確認 ENTER 警示 |

POST/PATCH 使用 `Content-Type: application/json`。測距範例：

```json
{
  "sequence_id": 100,
  "anchor_id": "Anchor1",
  "timestamp": 1700000000,
  "detected_belts": {
    "BELT-001": {"distance_mm": 2000.0}
  }
}
```

四個 Anchor 要以相同的腰帶 ID 與 `sequence_id` 回報同一輪資料，緩衝有效時間為 3 秒。尚未完成定位通常回傳 HTTP 202，完成定位回傳 200；仍須查看 `results[belt_id].status`，因為未登記腰帶等個別錯誤也可能出現在 202 回應。座標位於 `results[belt_id].position_mm`。

`sequence_id`、`timestamp` 必須為整數；`anchor_id` 為 `Anchor1` 到 `Anchor4`；輸入距離限制為 0–6000 mm。後端會扣除校正偏移，硬體應回報原始距離，避免重複校正。

歷史與事件 API 支援 `limit`（1–200）、`start`、`end`（ISO 日期時間）；事件另外支援 `belt_id`。歷史回應包含 `records`，事件回應包含 `events`。確認事件的 body 為 `{"status":"ACKNOWLEDGED"}`，僅接受尚未結案的 ENTER 事件。

## 合併前需要對齊的設定

- **裝置 ID**：後端 `REGISTERED_BELT_IDS`、資料庫初始腰帶及硬體 ID 對應必須一致。硬體 T0 對應 `BELT-001`。
- **Anchor 位置**：目前 A1=(0,0,500)、A2=(3000,0,30)、A3=(0,3000,30)、A4=(3000,3000,870)，皆為 mm。修改現場位置時，更新 `app.py` 的 `UWB_ANCHORS`，並確認與實體基站一致。
- **校正值**：目前 A1–A4 分別為 374.3、493.3、640.0、1125.7 mm，為現場設定，換位置或設備需重新確認。
- **路由與連線**：主服務 port 5000，實體 ESP32 透過 Wi-Fi 呼叫 API。跨電腦時調整硬體本機設定中的 Flask 區網 IP。現有程式未設定 CORS，前後端分開網域時需整合代理或 CORS 設定。
- **資料庫**：目前 SQLite 放在 `app.py` 同目錄。匯入模組就會初始化並可能更新既有 schema/種子資料，整合時使用副本或新資料庫；不要把個人的 `.db` 覆蓋到共同資料庫。
- **部署方式**：測距緩衝與位置歷史存在程序記憶體，不能直接假設多 worker 會共享狀態。
- **舊模擬器**：已移至本機 `local_archive/simulators/`，被 Git 忽略。此次提交會移除原先追蹤的三個模擬器檔案。
- **量測紀錄**：僅保留在本機，不納入 GitHub 交付。既有 CSV 放在 `local_archive/measurements/`，新量測輸出目錄 `data/measurements/` 也被 Git 忽略。

## 提交方式

以下在確認這個 repo 是要提交的來源後執行；先使用功能分支與 PR，組員可以檢閱差異。

```powershell
git switch -c feature/safety-monitor-handoff
git add .gitignore README.md docs requirements.txt requirements-hardware.txt
git add app.py tests/test_app.py tools/capture_uwb_samples.py mauwb-anchor
git diff --cached --stat
git diff --cached --check
git diff --cached
git commit -m "Prepare safety monitor module for integration"
```

檢查 staged diff 中沒有 Wi-Fi 密碼、本機設定、日誌、虛擬環境、建置產物或資料庫。`local_config.h` 已被忽略，範例設定檔可以提交。

確認 `git remote -v` 指向正確的 GitHub repo，且有推送權限後，再執行 `git push -u origin feature/safety-monitor-handoff`。如果共同 repo 與目前 repo 不同，先在共同 repo 的功能分支匯入上述模組檔案；不要直接使用不相關歷史合併。

PR 描述可使用：

> 加入智慧安全腰帶監控模組，接收四個實體 UWB Anchor 的測距並產生 3D 定位、定位歷史與危險區進出事件。附上 ESP32 韌體與交接文件，移除舊模擬器。當前啟用 BELT-001；整合時需對齊路由、資料庫位置、Anchor 座標與現場校正值。測試結果請填入實際執行結果。
