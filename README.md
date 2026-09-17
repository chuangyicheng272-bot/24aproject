# 鐵軌振動頻率偵測器

這個專案是一個桌面應用程式，可從攝影機、影片檔案或麥克風中偵測振動頻率。它適合用於鐵軌或機械振動訊號的視覺化檢測，並提供基於 Tkinter 的即時頻率分析介面。

## 專案功能

- 使用攝影機進行即時振動偵測
- 從錄製影片檔案進行離線分析
- 使用麥克風進行高頻分析
- 可手動或自動選擇振動目標的 ROI
- 使用固定背景參考區進行晃動補償
- 在追蹤失敗後自動恢復
- 模糊偵測與暫停分析邏輯
- 低光源環境下的影像增強
- 頻譜、波形和相位的即時可視化
- 以 CSV 記錄正常振動基準資料
- 參考音頻產生器，用於驗證量測準確度

## 專案結構

- `frequency.py` — 主程式，包含 GUI 介面與分析邏輯

## 需求環境

- Python 3.10+
- Windows 是此專案的主要目標平台，因為 GUI 與音訊設定是針對 Windows 設計
- 需要安裝的套件：
  - `opencv-python`
  - `numpy`
  - `matplotlib`
  - `Pillow`
  - `sounddevice`

## 安裝與執行

1. 在專案資料夾中開啟終端機。
2. 建立並啟用虛擬環境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. 安裝依賴套件：

```powershell
pip install opencv-python numpy matplotlib pillow sounddevice
```

4. 啟動應用程式：

```powershell
python frequency.py
```

## 使用方式

1. 點選資料來源按鈕，選擇一個輸入來源：
   - 攝影機（即時）
   - 影片檔（離線）
   - 麥克風（高頻）
2. 用滑鼠左鍵拖曳選取待測振動區域。
3. 若需要，可使用滑鼠右鍵選取背景參考區域。
4. 使用偵測方向選擇器，設定為 `auto`、`vertical`、`horizontal` 或 `both`。
5. 在儀表板中觀察即時頻率、波形與相位資訊。
6. 使用基準音產生器，對照已知頻率驗證偵測準確性。

## 注意事項

- 本程式使用 `TkAgg` 來繪製 Matplotlib 圖表。
- 若需要麥克風輸入，系統必須可以存取有效的音訊後端。
- 程式會將正常振動基準資料寫入專案資料夾中的 `normal_vibration.csv` 和 `normal_baseline.csv`。

## 授權

此專案僅供目前工作區中的本地研究與分析使用。
