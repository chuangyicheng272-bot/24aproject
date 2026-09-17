# SafeGuard Flask 示範系統

## 在 VS Code 執行

1. 在 VS Code 開啟此資料夾。
2. 開啟終端機，建立虛擬環境：`python -m venv .venv`
3. 啟用環境（PowerShell）：`.\.venv\Scripts\Activate.ps1`
4. 安裝套件：`pip install -r requirements.txt`
5. 啟動：`python app.py`
6. 在瀏覽器開啟 `http://127.0.0.1:5000`。

登入帳號：`admin`　密碼：`admin123`

## 頁面

- 登入系統
- 所有系統總覽
- 工地平面定位
- 人員管理
- 系統總覽的「監控設備」可進入管理頁，使用裝置編號與位置新增、編輯或刪除攝影機
- 攝影機透過 Camera API 回傳資料後，監控設備狀態與最後更新時間會自動顯示
- 「設定區域」新增時只需輸入區域名稱，每個區域會顯示成獨立方框
- 每個區域方框內可新增及移除自己的 UWB 基站，基站資料不會混到其他區域
- 系統總覽右上角提供「管理帳戶」入口（僅管理員可使用）
- 帳戶管理包含「所有帳戶」與獨立的「Email 郵寄服務」入口
- Email 郵寄服務可查看 SMTP 設定狀態、寄送測試信、篩選最近寄送紀錄，並重新傳送失敗通知
- 系統總覽右上角提供「SQLite 資料庫」展示頁（僅管理員可使用），可查看資料表、欄位、筆數與最新資料
- 帳戶管理（帳號、姓名、電話、角色、密碼；可新增、編輯、停用、刪除、搜尋、CSV 匯出）
- 新增人員時只需填寫「員工姓名」與「裝置名稱」
- 座標、電量、風險與裝置狀態由 UWB HTTP／MQTT 資料自動更新，管理頁每 5 秒重新顯示最新資料
- 工地定位頁可拖曳人員圖示來儲存位置
- PPE 頁可匯入 CSV；可先下載範例 CSV，再依相同欄位準備資料
- YOLO 串流頁可上傳其他人提供的影片（MP4、WebM、MOV、M4V、OGG）並播放
- 登入頁不提供公開註冊；新帳戶統一由管理員建立
- 忘記密碼可透過帳戶綁定的電子郵件收取 10 分鐘有效、僅能使用一次的重設連結
- 管理員也可在「帳戶管理 → 編輯」輸入新密碼，替使用者人工重設

首次執行會在專案資料夾建立 `safeguard.db`。這是 SQLite 資料庫，所有互動後的資料都會保留在裡面。

## NKUST 學校信箱密碼重設信設定

`@nkust.edu.tw` 是 NKUST Google Workspace 信箱，外寄伺服器使用 `smtp.gmail.com`、TLS 連接埠 `587`。先在管理帳戶替每個使用者設定電子郵件，再於 PowerShell 設定寄件帳戶。請使用學校 Google 帳戶產生的「應用程式密碼」，不要把一般登入密碼寫入程式：

```powershell
$env:PUBLIC_BASE_URL="http://192.168.1.104:5000"
$env:SMTP_HOST="smtp.gmail.com"
$env:SMTP_PORT="587"
$env:SMTP_USERNAME="c113118118@nkust.edu.tw"
$env:SMTP_APP_PASSWORD="你的 Google 應用程式密碼"
$env:SMTP_FROM_EMAIL="c113118118@nkust.edu.tw"
python app.py
```

`PUBLIC_BASE_URL` 必須是收件者可以開啟的 SafeGuard 網址。若從同一個區域網路的手機開啟，請填執行伺服器電腦的 IPv4，而不是 `127.0.0.1`。

使用流程：登入頁點「忘記密碼」→ 輸入帳號與電子郵件 → 開啟信件中的連結 → 輸入兩次新密碼。重設權杖只以 SHA-256 雜湊存入 SQLite，使用後或超過 10 分鐘即失效。

## SQLite 報告展示

登入管理員帳戶後，在儀表板右上方點擊「SQLite 資料庫」，即可看到：

- 資料從 Flask 寫入 SQLite 再查詢顯示的四個步驟
- SQLite 版本、資料庫檔案大小與外鍵狀態
- 六個資料表的欄位、筆數與最新五筆紀錄
- 可實際新增一筆報告測試資料的按鈕與 SQL 執行紀錄

終端機也能重現完整流程：

```powershell
python sqlite_report_demo.py
python sqlite_report_demo.py --insert
```

報告內容與示範講稿請參考 [`SQLITE_DATABASE_REPORT.md`](SQLITE_DATABASE_REPORT.md)。

## 已加入的通訊協定

### 1. UWB／ESP32S3 感測端

- HTTP：`POST /api/iot/uwb`
- MQTT：Topic 預設為 `safeguard/uwb`
- 資料格式：`application/json`
- 測試/查看最新資料：`GET /api/iot/uwb`

JSON 範例：

```json
{
  "device_id": "W-001",
  "name": "Helmet Tag W-001",
  "x": 12.5,
  "y": 8.2,
  "z": 1.4,
  "helmet": true,
  "vest": true,
  "battery": 88,
  "risk": "低風險",
  "status": "online",
  "timestamp": "2026-07-19T10:00:00+08:00"
}
```

`name` 請與管理頁填入的裝置名稱相同。第一次收到該裝置的資料時，系統會保留已綁定的員工姓名，並開始自動更新其他欄位。

PowerShell 測試：

```powershell
$body = @{
  device_id = "W-001"; name = "Helmet Tag W-001"
  x = 12.5; y = 8.2; z = 1.4
  helmet = $true; vest = $true; battery = 88
  risk = "低風險"; status = "online"
  timestamp = "2026-07-19T10:00:00+08:00"
} | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/iot/uwb" -Method POST -ContentType "application/json" -Body $body
```

啟用 MQTT（PowerShell）：

```powershell
$env:MQTT_ENABLED="true"
$env:MQTT_HOST="127.0.0.1"
$env:MQTT_PORT="1883"
$env:MQTT_TOPIC="safeguard/uwb"
python app.py
```

### 2. 影像端 RESTful API

- HTTP：`POST /api/iot/camera`
- 資料格式：`application/json`
- 測試/查看最新資料：`GET /api/iot/camera`

```json
{
  "camera_id": "CAM-01",
  "status": "online",
  "detections": [
    {"device_id": "W-001", "helmet": true, "vest": false, "confidence": 0.97}
  ],
  "timestamp": "2026-07-19T10:00:00+08:00"
}
```

### 3. LINE Bot

- Webhook：`POST /api/line/webhook`
- 系統主動推播：`POST /api/line/notify`
- 資料格式：`application/json`

設定環境變數：

```powershell
$env:LINE_CHANNEL_SECRET="你的 Channel secret"
$env:LINE_CHANNEL_ACCESS_TOKEN="你的 Channel access token"
$env:LINE_TARGET_USER_ID="主管的 LINE userId"
python app.py
```

主動推播測試：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/line/notify" -Method POST -ContentType "application/json" -Body '{"message":"SafeGuard 測試警示"}'
```

### 4. 區域網路存取與 API Key

伺服器已改為監聽 `0.0.0.0:5000`。同一個 Wi-Fi 的設備請使用主機 IPv4，例如：

```text
http://192.168.1.123:5000/api/iot/uwb
```

可選擇設定 API Key 保護 UWB、Camera 與 LINE notify：

```powershell
$env:IOT_API_KEY="請換成安全的隨機字串"
python app.py
```

設定後，裝置請在 HTTP Header 加入：

```text
X-API-Key: 請換成安全的隨機字串
```

查看所有通訊狀態：`GET /api/communication/status`

Windows 第一次允許區域網路設備連線時，請允許 Python 通過「私人網路」防火牆；也可以系統管理員 PowerShell 執行：

```powershell
New-NetFirewallRule -DisplayName "SafeGuard Flask 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
```

最簡單啟動方式：在專案資料夾對 `start-server.ps1` 按右鍵，以 PowerShell 執行。啟動後另開 PowerShell 執行 `test-uwb.ps1` 測試 UWB JSON 上報。
