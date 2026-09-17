# 智慧安全腰帶：UWB 定位與危險區域監控

本版本使用實體 ESP32 / UWB 基站，電腦只需啟動 Flask 後端。包含監控頁面、四個 Anchor 測距整合、3D 定位、歷史軌跡與危險區進出事件。距離與座標單位皆為 **mm**。目前後端只登記 `BELT-001`。

## 檔案用途

```text
python-flask/
├─ app.py                     後端與監控頁面
├─ requirements*.txt          套件清單
├─ mauwb-anchor/              ESP32 韌體
├─ docs/                      合併交接文件
├─ tests/                     自動化測試
├─ tools/                     串口量測工具
└─ local_archive/             本機備份（不提交 Git）
   ├─ databases/              舊資料庫備份
   ├─ measurements/           舊量測 CSV（不上傳）
   └─ simulators/             舊模擬器
```

目前使用的 `safety_monitor.db` 留在根目錄，維持既有後端路徑。根目錄的日誌與快取是執行產物，已被 Git 忽略。

| 檔案 | 用途 | 合併建議 |
| --- | --- | --- |
| `app.py` | Flask API、內嵌網頁、定位計算、SQLite 初始化 | 核心程式 |
| `tests/test_app.py` | 定位歷史與圍籬事件等測試 | 一起交付 |
| `mauwb-anchor/` | ESP32-S3 PlatformIO 韌體 | 硬體模組 |
| `tools/capture_uwb_samples.py` | 串口擷取測距資料為 CSV | 量測工具 |
| `requirements*.txt` | Python 套件清單 | 一起交付 |
| `docs/INTEGRATION.md` | API、設定與 GitHub 合併交接 | 組員先閱讀 |

`.venv/`、`__pycache__/`、`.pio/`、日誌、SQLite 資料庫與備份不提交 Git。既有資料庫保留在本機。

## 啟動後端（Windows PowerShell）

目前環境為 Python 3.14.6；其他版本尚未驗證。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

開啟 <http://127.0.0.1:5000>。程式會初始化同目錄的 `safety_monitor.db`。目前使用 Flask debug 開發伺服器，正式部署時需另外調整。

舊模擬器保存在 Git 忽略的 `local_archive/simulators/`，不納入此次交付。

## 硬體設定與量測

將 `mauwb-anchor/include/local_config.example.h` 複製為同目錄的 `local_config.h`，填入 Wi-Fi 與 Flask 電腦的區網 IP。本機已存在的設定可直接沿用；請勿提交該檔。

在 `src/main.cpp` 設定各板子的 `UWB_INDEX`（1–4，目前為 4）；在 `platformio.ini` 設定串口（目前 COM4），再用 PlatformIO 建置與燒錄。電腦與 ESP32 必須能透過區網連線。

擷取 CSV 另需安裝硬體套件，並使用新的輸出檔名，避免覆寫既有量測：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-hardware.txt
.\.venv\Scripts\python.exe tools/capture_uwb_samples.py --port COM3 --count 30 --output data/measurements/uwb_new_samples.csv
```

量測程式預設 115200 baud、逾時 90 秒。串口請依實際裝置調整。省略 `--output` 時，會自動存到專案的 `data/measurements/`，檔名包含量測啟動時間。此輸出目錄已被 Git 忽略，不上傳 GitHub；既有 CSV 保存在 `local_archive/measurements/`。

## 測試

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

測試案例使用暫存資料庫，但匯入 `app.py` 時會先執行 `init_db()`；如需完全隔離既有資料，請在獨立 checkout 或程式副本內執行。
