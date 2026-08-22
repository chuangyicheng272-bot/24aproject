# Construction Safety System

工地安全監控系統，後端使用 Flask，前端使用 Next.js。後端整合影像輸入、YOLO 人員與 PPE 偵測、MediaPipe 姿態分析、IoU 人員追蹤，以及工人狀態管理。

## 專案內容

- `backend/`：Flask API 與即時影像串流
- `frontend/`：Next.js 前端示意畫面
- `person_v2.pt`：人員偵測模型
- `best_v3.pt`：PPE 裝備偵測模型
- `model/pose_landmarker_heavy.task`：MediaPipe Pose 模型
- `test_videos/`：本機測試影片

## 第一次在新裝置安裝

建議使用 Python 3.11 或 3.12，並先安裝 Node.js。

在 PowerShell 進入專案根目錄：

```powershell
cd C:\Users\Owner\Desktop\construction-safety-system
```

執行初始化：

```powershell
.\scripts\setup.ps1
```

這會建立 `.venv`、安裝後端套件、安裝前端套件，並從 `.env.example` 建立 `.env`，從 `frontend/.env.example` 建立 `frontend/.env.local`。

如果 PowerShell 擋住腳本，可改用手動步驟：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
cd frontend
npm ci
cd ..
copy .env.example .env
copy frontend\.env.example frontend\.env.local
```

## 啟動後端

```powershell
.\scripts\run-backend.ps1
```

或手動執行：

```powershell
.\.venv\Scripts\activate
python -m backend.app
```

後端頁面：

```text
http://127.0.0.1:5000/
```

即時串流：

```text
http://127.0.0.1:5000/api/cameras/stream
```

## 啟動前端

另開一個 PowerShell：

```powershell
.\scripts\run-frontend.ps1
```

或手動執行：

```powershell
cd frontend
npm run dev
```

Next.js 預設頁面通常是：

```text
http://127.0.0.1:3000/
```

## 更換影像來源

修改根目錄的 `.env`：

```env
CAMERA_SOURCE=test_videos/001.mp4
```

可改成 Webcam：

```env
CAMERA_SOURCE=0
```

可改成手機串流：

```env
CAMERA_SOURCE=http://手機IP:8080
```

可改成 RTSP：

```env
CAMERA_SOURCE=rtsp://user:password@camera-ip:554/stream
```

修改 `.env` 後要重新啟動後端。

## 重要設定

後端讀取根目錄 `.env`：

```env
PERSON_MODEL_PATH=person_v2.pt
EQUIPMENT_MODEL_PATH=best_v3.pt
MAX_PEOPLE=1
CAMERA_WIDTH=640
CAMERA_HEIGHT=360
CAMERA_TARGET_FPS=30.0
INFERENCE_FPS=15.0
PPE_INTERVAL_SECONDS=2.0
STREAM_JPEG_QUALITY=45
```

- `PERSON_MODEL_PATH`：人員偵測模型
- `EQUIPMENT_MODEL_PATH`：PPE 裝備偵測模型
- `MAX_PEOPLE`：最多追蹤人數，測試影片只有一人時建議為 `1`，設成 `0` 代表不限人數
- `CAMERA_WIDTH` / `CAMERA_HEIGHT`：後端輸出的統一畫面尺寸，較低解析度通常更流暢
- `CAMERA_TARGET_FPS`：主畫面串流目標 FPS
- `INFERENCE_FPS`：YOLO 與 MediaPipe 每秒更新次數，數值越高越流暢，但越吃效能
- `PPE_INTERVAL_SECONDS`：PPE 模型更新間隔；拉長可讓 MediaPipe 更新更快
- `STREAM_JPEG_QUALITY`：後端串流壓縮品質，數值越高畫質越好但資料量越大

`INFERENCE_FPS=15.0` 是目標值，實際能否穩定達到 15 FPS 取決於電腦效能、模型大小、影像來源延遲與目前畫面人數。

前端讀取 `frontend/.env.local`：

```env
NEXT_PUBLIC_API_BASE=http://127.0.0.1:5000
NEXT_PUBLIC_STREAM_URL=http://127.0.0.1:5000/api/cameras/stream
```

- `NEXT_PUBLIC_API_BASE`：Next.js 呼叫 Flask API 的基礎網址
- `NEXT_PUBLIC_STREAM_URL`：Next.js 前端要顯示的 Flask 串流網址

## 換裝置時要帶走的檔案

請確認以下檔案也有一起移到新裝置：

- `person_v2.pt`
- `best_v3.pt`
- `model/pose_landmarker_heavy.task`
- `test_videos/` 裡的測試影片
- `.env` 或依照 `.env.example` 重新建立

`.venv` 和 `frontend/node_modules` 不需要搬移，換裝置後重新安裝即可。
