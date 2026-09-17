# --- Make stdout/stderr UTF-8 so Unicode output (≤, →, …) does not crash on
# Windows consoles using cp950/cp1252. Safe no-op if already UTF-8. ---
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

import matplotlib
matplotlib.use("TkAgg")
matplotlib.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "SimHei", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False

import cv2
import numpy as np
from numpy.fft import rfft, rfftfreq
from PIL import Image, ImageTk
# sounddevice is imported lazily inside start_mic / start_tone to avoid
# blocking PortAudio device enumeration at startup on Windows.
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import threading
import time
import os
import csv
from datetime import datetime
from collections import deque


class VibrationAnalyzer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("震動頻率偵測器")
        # 置中於主螢幕, 避免之前位置被記在第二螢幕或螢幕外
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 1280, 880
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(1100, 760)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        # 強制顯示並提到最前
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(500, lambda: self.root.attributes("-topmost", False))

        # 共用狀態
        self.running = False
        self.mode = None  # "camera", "file", "mic"
        # 執行緒同步: capture/audio 在背景緒寫入, UI 在主緒讀取
        self._data_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread = None

        # 攝影機相關
        self.cap = None
        self.roi = None
        self.selecting_roi = False
        self.roi_start = None
        self.displacement_y = []
        self.displacement_x = []
        self.template = None
        self.template_offset = (0, 0)  # 最近一次匹配位置, 模板更新時用
        self.fps = 30.0
        self.frame_shape = None

        # 低光線優化
        self.correlation_threshold = 0.3
        self.consecutive_failures = 0
        self.confidence_scores = deque(maxlen=10)
        self.frame_count = 0
        self.template_update_interval = 30
        # CLAHE 只對 search area 局部做, 避免全局 equalizeHist 改變模板/搜尋區的亮度對應
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        # ── 攝影機晃動補償: 背景參考 ROI (靜止物, 追蹤它的位移即相機晃動) ──
        self.bg_roi = None
        self.bg_template = None
        self.bg_template_offset = (0, 0)  # 固定不 re-anchor: 背景是靜止的
        self.bg_search_margin = 0
        self.bg_found_x = 0.0
        self.bg_found_y = 0.0
        self.bg_confidence = 0.0
        self.bg_hist_x = deque(maxlen=150)  # 背景位移歷史 (驗證晃動量用)
        self.bg_hist_y = deque(maxlen=150)
        self.comp_baseline = None           # 補償訊號的初始基準 (rail-bg)
        self.selecting_bg = False           # 右鍵拖曳選背景 ROI 中
        self.bg_roi_start = None
        # checkbox 狀態鏡射成純 bool: worker thread 不可直接呼叫 Tk 變數 .get()
        self._shake_comp = True
        self._auto_recover = True
        self._blur_detect = True

        # ── 模糊偵測 (Laplacian 變異數, 相對基準) ──
        self.focus_history = deque(maxlen=90)
        self.is_blurry = False
        self.blur_frames = 0
        self.blur_ratio = 0.4               # 低於近期最佳的 40% 視為模糊

        # ── ROI 自動恢復 ──
        self.track_lost_frames = 0
        self.recovery_search_after = 45     # 連續失敗多少幀後全畫面重搜
        self.recovery_reset_after = 120     # 仍失敗多少幀後重跑自動框選
        # 自動框選的目標 (rail / background)
        self._auto_want_rail = True
        self._auto_want_bg = False

        # 自動框選 ROI
        self.auto_detecting = False
        self.auto_frames = []
        self.auto_target = 60

        # 麥克風相關
        self.audio_stream = None
        self.sample_rate = 44100
        self.audio_buffer = deque(maxlen=self.sample_rate * 2)

        # 基準訊號產生器（喇叭輸出已知頻率，用來驗證偵測準確度）
        self.tone_stream = None
        self.tone_playing = False
        self.tone_phase = 0.0  # radians, wraps in [0, 2π)
        self.tone_freq = 10.0
        self.tone_amp = 0.5
        self.tone_sr = 44100

        # 共用
        self.timestamps = []
        # wall-clock 節流: 主執行緒 matplotlib 重畫 / status label 文字更新, 各自最少間隔
        self._last_plot_time = 0.0
        self._last_status_time = 0.0
        self._plot_min_interval = 0.15  # 秒
        self._status_min_interval = 0.20

        # 噪聲基準量測 (靜止時的位移 std → 次像素 noise floor)
        self.noise_active = False
        self.noise_start_n = 0
        self.noise_target_count = 0

        # ── 低光源增強 (軟體自動增益 + gamma + 去雜訊) ──
        # worker thread 讀 self._low_light (純 bool); tk 變數只在主緒操作
        self._low_light = False
        self._ll_denoise = True
        self.ll_target = 120.0          # 目標平均亮度
        self.ll_gain = 1.0              # 平滑後的線性增益
        self.ll_gamma = 1.0             # 平滑後的 gamma
        self.ll_mean = 0.0              # 最近一幀原始平均亮度 (UI 顯示)

        # ── 頻率分析: band-pass / Top-3 peak / SNR (最近一次結果) ──
        self.last_peak_freq = 0.0
        self.last_peak_amp = 0.0
        self.last_snr_db = 0.0
        self.last_top_peaks = []        # [(freq, amp), ...] 最多 3 筆
        self.last_waveform = "--"
        self.last_phase_deg = 0.0
        self.last_disp_rms = 0.0
        self.session_min_freq = None
        self.session_max_freq = None

        # ── 正常震動資料 CSV (基準庫) ──
        try:
            _base_dir = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            _base_dir = os.getcwd()
        self.csv_path = os.path.join(_base_dir, "normal_vibration.csv")
        self.baseline_path = os.path.join(_base_dir, "normal_baseline.csv")
        self.CSV_HEADER = [
            "timestamp", "label", "mode", "fps", "roi", "direction",
            "peak_freq_hz", "peak_amp", "snr_db",
            "p2_freq_hz", "p2_amp", "p3_freq_hz", "p3_amp",
            "waveform", "phase_deg", "disp_rms_px", "bg_shake_std_px",
            "session_min_freq_hz", "session_max_freq_hz",
        ]

        self.build_ui()

    # ── UI 建構 ──────────────────────────────────────────

    # 配色 (Tailwind slate + blue accent)
    BG = "#f8fafc"
    CARD = "#ffffff"
    BORDER = "#e2e8f0"
    TEXT = "#0f172a"
    MUTED = "#64748b"
    ACCENT = "#2563eb"
    ACCENT_HOVER = "#1d4ed8"
    ACCENT_SOFT = "#dbeafe"
    SUCCESS = "#16a34a"
    ERROR = "#dc2626"
    PURPLE = "#7c3aed"
    HEADER_BG = "#0f172a"
    HEADER_FG = "#f1f5f9"
    HEADER_MUTED = "#94a3b8"
    PLOT_BG = "#fafafa"
    GRID = "#e2e8f0"
    FONT_FAMILY = "Microsoft JhengHei"

    def build_ui(self):
        self.root.configure(bg=self.BG)
        self._setup_styles()

        F = self.FONT_FAMILY

        # ── 主要操作: 資料來源 / ROI / 偵測方向 ──
        top = ttk.LabelFrame(self.root, text=" 主要操作 ",
                             style="Dashboard.TLabelframe", padding=(10, 5))
        top.pack(fill=tk.X, padx=12, pady=(7, 3))

        src = ttk.LabelFrame(top, text=" 01  資料來源 ", style="Section.TLabelframe", padding=(10, 6))
        src.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(src, text="攝影機 (即時)", style="Accent.TButton",
                   command=self.start_camera).pack(side=tk.LEFT, padx=(3, 0))
        ttk.Button(src, text="?", width=2, style="Help.TButton",
                   command=lambda: self.show_help("camera")).pack(side=tk.LEFT, padx=(1, 3))

        ttk.Button(src, text="影片檔 (離線)",
                   command=self.open_file).pack(side=tk.LEFT, padx=(3, 0))
        ttk.Button(src, text="?", width=2, style="Help.TButton",
                   command=lambda: self.show_help("file")).pack(side=tk.LEFT, padx=(1, 3))

        ttk.Button(src, text="麥克風 (高頻)",
                   command=self.start_mic).pack(side=tk.LEFT, padx=(3, 0))
        ttk.Button(src, text="?", width=2, style="Help.TButton",
                   command=lambda: self.show_help("mic")).pack(side=tk.LEFT, padx=(1, 3))

        ttk.Button(src, text="■ 停止", style="Stop.TButton",
                   command=self.stop).pack(side=tk.LEFT, padx=3)

        auto_frame = ttk.LabelFrame(top, text=" 02  ROI 與量測 ", style="Section.TLabelframe", padding=(10, 6))
        auto_frame.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(auto_frame, text="⊕ 自動框選振動區", style="Accent.TButton",
                   command=self.auto_detect_roi).pack(side=tk.LEFT, padx=(3, 0))
        ttk.Button(auto_frame, text="?", width=2, style="Help.TButton",
                   command=lambda: self.show_help("auto_roi")).pack(side=tk.LEFT, padx=(1, 3))
        ttk.Button(auto_frame, text="▣ 量噪聲基準",
                   command=self.measure_noise_floor).pack(side=tk.LEFT, padx=(3, 0))
        ttk.Button(auto_frame, text="?", width=2, style="Help.TButton",
                   command=lambda: self.show_help("noise")).pack(side=tk.LEFT, padx=(1, 3))

        dirf = ttk.LabelFrame(top, text=" 03  偵測方向 ", style="Section.TLabelframe", padding=(10, 6))
        dirf.pack(side=tk.LEFT, padx=(0, 8))
        self.direction_var = tk.StringVar(value="auto")
        for txt, val in (("自動", "auto"), ("垂直", "vertical"),
                         ("水平", "horizontal"), ("兩者", "both")):
            ttk.Radiobutton(dirf, text=txt, variable=self.direction_var,
                            value=val).pack(side=tk.LEFT, padx=3)
        self.dir_detect_label = tk.Label(dirf, text="", bg=self.BG,
                                         fg=self.PURPLE, font=(F, 9, "bold"))
        self.dir_detect_label.pack(side=tk.LEFT, padx=(8, 0))

        # 主頻率卡片在 hero 列, 此處不放

        self.shake_comp_var = tk.BooleanVar(value=True)
        self.auto_recover_var = tk.BooleanVar(value=True)
        self.blur_detect_var = tk.BooleanVar(value=True)
        self.low_light_var = tk.BooleanVar(value=False)
        self.ll_denoise_var = tk.BooleanVar(value=True)

        # ── 進階監測設定: 預設收合，把高度留給影像與頻譜 ──
        self.advanced_expanded = False
        self.advanced_toggle_row = tk.Frame(self.root, bg=self.BG)
        self.advanced_toggle_row.pack(fill=tk.X, padx=16, pady=(3, 0))
        tk.Label(self.advanced_toggle_row, text="進階監測設定", bg=self.BG,
                 fg=self.TEXT, font=(F, 9, "bold")).pack(side=tk.LEFT)
        self.advanced_summary_label = tk.Label(
            self.advanced_toggle_row,
            text="  補償開啟 · 自動恢復開啟 · 模糊暫停開啟 · 低光增強關閉",
            bg=self.BG, fg=self.MUTED, font=(F, 8))
        self.advanced_summary_label.pack(side=tk.LEFT)
        self.advanced_toggle_button = ttk.Button(
            self.advanced_toggle_row, text="▼ 展開設定",
            style="Compact.TButton", command=self._toggle_advanced_panel)
        self.advanced_toggle_button.pack(side=tk.RIGHT)

        self.advanced_panel = ttk.LabelFrame(
            self.root, text="",
            style="Dashboard.TLabelframe", padding=(10, 4))
        adv = self.advanced_panel
        adv_top = ttk.Frame(adv)
        adv_top.pack(fill=tk.X)

        bgf = ttk.LabelFrame(adv_top, text=" 晃動補償 (背景參考) ",
                             style="Section.TLabelframe", padding=(10, 5))
        bgf.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bgf, text="◨ 自動背景參考",
                   command=self.auto_detect_background).pack(side=tk.LEFT, padx=(3, 0))
        ttk.Button(bgf, text="?", width=2, style="Help.TButton",
                   command=lambda: self.show_help("shake")).pack(side=tk.LEFT, padx=(1, 6))
        ttk.Checkbutton(bgf, text="啟用補償", variable=self.shake_comp_var,
                        command=self._sync_flags).pack(side=tk.LEFT, padx=3)
        self.bg_shake_label = tk.Label(bgf, text="背景晃動: 未設定背景參考區",
                                       bg=self.BG, fg=self.MUTED, font=(F, 9))
        self.bg_shake_label.pack(side=tk.LEFT, padx=(10, 0))

        stabf = ttk.LabelFrame(adv_top, text=" 追蹤穩定性 ",
                               style="Section.TLabelframe", padding=(10, 5))
        stabf.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(stabf, text="追蹤失敗自動恢復", variable=self.auto_recover_var,
                        command=self._sync_flags).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(stabf, text="模糊時暫停分析", variable=self.blur_detect_var,
                        command=self._sync_flags).pack(side=tk.LEFT, padx=3)
        ttk.Button(stabf, text="?", width=2, style="Help.TButton",
                   command=lambda: self.show_help("stability")).pack(side=tk.LEFT, padx=(1, 3))

        llf = ttk.LabelFrame(adv_top, text=" 低光源增強 ",
                             style="Section.TLabelframe", padding=(10, 5))
        llf.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(llf, text="啟用 (自動增益/gamma)", variable=self.low_light_var,
                        command=self._sync_flags).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(llf, text="去雜訊", variable=self.ll_denoise_var,
                        command=self._sync_flags).pack(side=tk.LEFT, padx=3)
        ttk.Button(llf, text="?", width=2, style="Help.TButton",
                   command=lambda: self.show_help("low_light")).pack(side=tk.LEFT, padx=(1, 6))
        self.ll_label = tk.Label(llf, text="亮度: --", bg=self.BG,
                                 fg=self.MUTED, font=(F, 9))
        self.ll_label.pack(side=tk.LEFT, padx=(6, 0))
        self._sync_flags()

        calibration_row = ttk.LabelFrame(
            adv, text=" 資料與校正 ", style="Dashboard.TLabelframe",
            padding=(8, 3))
        calibration_row.pack(fill=tk.X, pady=(5, 0))

        csvf = ttk.LabelFrame(
            calibration_row, text=" 正常震動資料 (基準庫) ",
            style="Section.TLabelframe", padding=(8, 3))
        csvf.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(csvf, text="樣本名稱").pack(side=tk.LEFT, padx=(2, 4))
        self.sample_label_var = tk.StringVar(value="normal_rail")
        ttk.Entry(csvf, textvariable=self.sample_label_var, width=12).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(csvf, text="● 記錄正常樣本", style="Accent.TButton",
                   command=self.record_normal_sample).pack(side=tk.LEFT, padx=2)
        ttk.Button(csvf, text="Σ 統計基準",
                   command=self.compute_baseline).pack(side=tk.LEFT, padx=2)
        ttk.Button(csvf, text="?", width=2, style="Help.TButton",
                   command=lambda: self.show_help("normal_csv")).pack(side=tk.LEFT, padx=(1, 3))
        self.session_range_label = ttk.Label(
            csvf, text="本次範圍：最低 -- Hz｜最高 -- Hz",
            style="Muted.TLabel")
        self.session_range_label.pack(side=tk.LEFT, padx=(8, 2))

        tone = ttk.LabelFrame(
            calibration_row, text=" 基準訊號產生器  (已知頻率 → 喇叭 → 驗證偵測) ",
            style="Section.TLabelframe", padding=(10, 5))
        tone.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(tone, text="頻率").pack(side=tk.LEFT, padx=(2, 4))
        self.tone_freq_var = tk.StringVar(value="10")
        ttk.Entry(tone, textvariable=self.tone_freq_var, width=8).pack(side=tk.LEFT)
        ttk.Label(tone, text="Hz", style="Muted.TLabel").pack(side=tk.LEFT, padx=(3, 14))
        ttk.Label(tone, text="振幅").pack(side=tk.LEFT, padx=(0, 4))
        self.tone_amp_var = tk.StringVar(value="0.5")
        ttk.Entry(tone, textvariable=self.tone_amp_var, width=6).pack(side=tk.LEFT)
        ttk.Label(tone, text="(0 ~ 1)", style="Muted.TLabel").pack(side=tk.LEFT, padx=(3, 14))
        self.tone_button = ttk.Button(
            tone, text="▶ 播放基準音", style="Accent.TButton",
            command=self.toggle_tone)
        self.tone_button.pack(side=tk.LEFT, padx=4)
        self.tone_status = ttk.Label(
            tone, text="將喇叭振膜當標準答案, 對準鏡頭或麥克風即可驗證偵測值",
            style="Muted.TLabel")
        self.tone_status.pack(side=tk.LEFT, padx=(16, 0))

        # ── 即時分析摘要 ──
        summary_head = tk.Frame(self.root, bg=self.BG)
        summary_head.pack(fill=tk.X, padx=16, pady=(4, 2))
        tk.Label(summary_head, text="即時分析摘要", bg=self.BG, fg=self.TEXT,
                 font=(F, 11, "bold")).pack(side=tk.LEFT)
        tk.Label(summary_head, text="  主頻率為核心指標，波形與相位提供判讀依據",
                 bg=self.BG, fg=self.MUTED, font=(F, 9)).pack(side=tk.LEFT)
        self.status_label = tk.Label(
            summary_head, text="● 系統就緒", bg=self.ACCENT_SOFT, fg=self.SUCCESS,
            font=(F, 9, "bold"), padx=10, pady=2)
        self.status_label.pack(side=tk.RIGHT)

        hero_row = ttk.Frame(self.root, padding=(12, 0, 12, 4))
        hero_row.pack(fill=tk.X)
        hero_row.columnconfigure(0, weight=2)
        hero_row.columnconfigure(1, weight=1)
        hero_row.columnconfigure(2, weight=1)

        def make_tile(parent, accent_color, label_en, label_zh):
            tile = tk.Frame(parent, bg=self.CARD,
                            highlightbackground=self.BORDER, highlightthickness=1)
            # 頂部 accent 色條
            tk.Frame(tile, bg=accent_color, height=2).pack(fill=tk.X)
            inner = tk.Frame(tile, bg=self.CARD)
            inner.pack(fill=tk.BOTH, expand=True, padx=16, pady=(1, 2))
            header = tk.Frame(inner, bg=self.CARD)
            header.pack(fill=tk.X, anchor=tk.W)
            tk.Label(header, text=label_en, bg=self.CARD, fg=accent_color,
                     font=(F, 7, "bold")).pack(side=tk.LEFT)
            tk.Label(header, text=label_zh, bg=self.CARD, fg=self.MUTED,
                     font=(F, 8)).pack(side=tk.LEFT, padx=(6, 0))
            return tile, inner

        # 主頻率
        freq_tile, freq_inner = make_tile(hero_row, self.ACCENT, "FREQUENCY", "主頻率")
        freq_tile.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.freq_label = tk.Label(freq_inner, text="-- Hz", bg=self.CARD,
                                   fg=self.ACCENT, font=(F, 20, "bold"))
        self.freq_label.pack(anchor=tk.W)
        self.freq_sub = tk.Label(freq_inner, text="SNR -- dB", bg=self.CARD,
                                 fg=self.MUTED, font=(F, 8))
        self.freq_sub.pack(anchor=tk.W)

        # 波形
        shape_tile, shape_inner = make_tile(hero_row, self.PURPLE, "WAVEFORM", "波形")
        shape_tile.grid(row=0, column=1, sticky="nsew", padx=5)
        self.shape_label = tk.Label(shape_inner, text="--", bg=self.CARD,
                                    fg=self.TEXT, font=(F, 16, "bold"))
        self.shape_label.pack(anchor=tk.W)

        # 峰值相位
        phase_tile, phase_inner = make_tile(hero_row, "#ea580c", "PHASE", "峰值相位")
        phase_tile.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        self.phase_label = tk.Label(phase_inner, text="--", bg=self.CARD,
                                    fg=self.TEXT, font=(F, 16, "bold"))
        self.phase_label.pack(anchor=tk.W)

        # 主要區域
        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        # 左: 影像顯示
        left = ttk.LabelFrame(main, text="  即時影像  ｜  左鍵框選振動物 · 右鍵框選背景  ",
                              style="Workspace.TLabelframe", padding=6)
        main.add(left, weight=1)

        self.canvas_video = tk.Canvas(left, bg="#0b0b0f", cursor="crosshair",
                                      highlightthickness=0, bd=0)
        self.canvas_video.pack(fill=tk.BOTH, expand=True)
        self.canvas_video.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas_video.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas_video.bind("<ButtonRelease-1>", self.on_mouse_up)
        # 右鍵拖曳 = 選背景參考 ROI (晃動補償)
        self.canvas_video.bind("<ButtonPress-3>", self.on_bg_mouse_down)
        self.canvas_video.bind("<B3-Motion>", self.on_bg_mouse_drag)
        self.canvas_video.bind("<ButtonRelease-3>", self.on_bg_mouse_up)
        self.photo_image = None

        # 右: 圖表
        right = ttk.LabelFrame(main, text="  趨勢與頻譜分析  ",
                               style="Workspace.TLabelframe", padding=6)
        main.add(right, weight=1)

        self.fig = Figure(figsize=(5, 8), dpi=90, facecolor=self.CARD)
        self.ax_disp = self.fig.add_subplot(3, 1, 1)
        self.ax_freq = self.fig.add_subplot(3, 1, 2)
        self.ax_phase = self.fig.add_subplot(3, 1, 3)
        self.fig.tight_layout(pad=2.5)

        self.canvas_plot = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas_plot.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.init_plots()

    def _toggle_advanced_panel(self):
        """展開或收合進階監測控制列。"""
        if self.advanced_expanded:
            self.advanced_panel.pack_forget()
            self.advanced_expanded = False
            self.advanced_toggle_button.config(text="▼ 展開設定")
        else:
            self.advanced_panel.pack(
                fill=tk.X, padx=12, pady=(0, 3),
                after=self.advanced_toggle_row)
            self.advanced_expanded = True
            self.advanced_toggle_button.config(text="▲ 收合設定")

    # ── 操作流程彈出視窗 ──────────────────────────────────

    HELP_CONTENT = {
        "camera": {
            "title": "攝影機模式  —  操作流程",
            "desc": "用電腦攝影機即時偵測振動 (上限約 1 ~ 14 Hz, 受 FPS 限制)",
            "steps": [
                ("1", "按「攝影機 (即時)」",
                 "程式會開啟預設攝影機\n影像出現但尚未開始偵測"),
                ("2", "在影像上拖曳選取追蹤區域 (ROI)",
                 "選有明顯紋理的地方:\n貼紙 / 角落 / 螺絲 / 文字 / 反差大的邊緣\n建議大小 30×30 ~ 80×80 像素"),
                ("3", "讓物體振動",
                 "可同時按「▶ 播放基準音」\n用喇叭振膜當驗證基準"),
                ("4", "查看右側結果",
                 "累積 32 筆後開始畫圖\n主頻率卡片即時更新\n圖表約每 0.15 秒重畫一次"),
                ("5", "按「■ 停止」結束",
                 "停止後影像區會顯示最終偵測頻率"),
            ],
            "tip": "重點: FPS 30 → 最高只能測到 15 Hz (奈奎斯特極限)\n超過這個頻率會出現 aliasing 錯誤結果",
        },
        "file": {
            "title": "影片檔模式  —  操作流程",
            "desc": "離線分析已錄好的影片檔 (.mp4 / .avi / .mov / .mkv / .wmv)",
            "steps": [
                ("1", "按「影片檔 (離線)」",
                 "在檔案對話框選擇要分析的影片"),
                ("2", "在影像上拖曳選取追蹤區域 (ROI)",
                 "方式與攝影機模式相同\n選紋理明顯的區域"),
                ("3", "影片會依原始 FPS 自動播放並偵測",
                 "位移 / 頻譜 / 主頻率同步更新"),
                ("4", "播到結尾自動停止",
                 "或中途按「■ 停止」提前結束\n結束後顯示最終頻率"),
            ],
            "tip": "重點: 偵測頻率上限 = 影片 FPS ÷ 2\n用手機慢動作 (120 / 240 FPS) 錄影可以測到 60 / 120 Hz",
        },
        "auto_roi": {
            "title": "自動框選振動區  —  操作流程",
            "desc": "用時間變異量找出畫面中抖動最劇烈的地方, 自動設為追蹤區域",
            "steps": [
                ("1", "先按「攝影機 (即時)」或「影片檔 (離線)」",
                 "要有影像在播才能分析\n純麥克風模式沒有用"),
                ("2", "讓要測的物體開始振動",
                 "可以同時按「▶ 播放基準音」\n或直接對準風扇/馬達/引擎等振動源"),
                ("3", "按「⊕ 自動框選振動區」",
                 "程式會收集 2 秒的影像 (約 60 幀)\n狀態列會顯示進度"),
                ("4", "分析完成自動設定 ROI",
                 "綠色方框會出現在抖最兇的地方\n接著自動開始追蹤與頻率偵測"),
                ("5", "結果不理想可再按一次 或 手動拖曳",
                 "自動選取失敗時狀態列會說明原因\n(振動太弱 / 太分散 / 區域太小)"),
            ],
            "tip": "原理: 計算每個像素在這 2 秒內的標準差\n標準差大 = 該像素一直在變 = 很可能是振動源\n取前 5% 最會動的像素, 連通後框出最大區塊",
        },
        "noise": {
            "title": "量噪聲基準  —  操作流程",
            "desc": "量出當前 ROI 在靜止時的位移雜訊 std → 判斷可偵測振幅下限",
            "steps": [
                ("1", "先讓追蹤穩定下來",
                 "用攝影機/影片並設好 ROI\n等狀態列顯示「追蹤中... 信心 > 0.5」"),
                ("2", "讓物體保持靜止",
                 "這個量測要的是「不動時還會抖多少」\n物體真正不動才能反映次像素噪聲"),
                ("3", "按「▣ 量噪聲基準」",
                 "程式會收集約 2 秒的位移資料\n期間請繼續保持靜止"),
                ("4", "彈出結果",
                 "顯示 x / y / 總位移 std (像素)\n以及建議的可偵測振幅下限 (約 3× std)"),
                ("5", "判讀",
                 "想測 0.05 像素振動 → std 必須 ≤ 0.017\n若實際 std 太大: 加光線 / 換紋理好的 ROI / 用更穩的相機架"),
            ],
            "tip": "原理: 物體靜止時 displacement 不應該有變化\n所以 std 就是次像素演算法 + 雜訊 + 鏡頭抖動的綜合下限\n用喇叭驗證時, 把振幅一路調到只剩這個值的 3~5 倍, 還能測到 = 偵測有用",
        },
        "mic": {
            "title": "麥克風模式  —  操作流程",
            "desc": "用麥克風收音分析 (取樣率 44100 Hz, 最高可測 22050 Hz)",
            "steps": [
                ("1", "按「麥克風 (高頻)」",
                 "程式開啟麥克風串流\n不需要選取 ROI"),
                ("2", "(建議) 先驗證基準",
                 "按「▶ 播放基準音」輸入已知頻率\n確認主頻率顯示值與輸入相符"),
                ("3", "對準聲源或振動物",
                 "風扇 / 馬達 / 引擎 / 喇叭 / 電器噪音都可以"),
                ("4", "即時顯示主頻率",
                 "緩衝區累積到 4096 筆就更新一次\n波形 / 頻譜圖即時繪製"),
                ("5", "按「■ 停止」結束",
                 "結束後顯示最終頻率"),
            ],
            "tip": "重點: 適合高頻 (人耳範圍) 的機械或聲學振動\n因為不靠鏡頭, 不受光線 / 距離影響",
        },
        "shake": {
            "title": "晃動補償 (背景參考)  —  操作流程",
            "desc": "同時追蹤『振動物』與『靜止背景』, 相減後扣掉攝影機 / 手持晃動",
            "steps": [
                ("1", "先設好振動物 ROI",
                 "用「⊕ 自動框選振動區」或左鍵拖曳選振動區"),
                ("2", "設定背景參考區",
                 "按「◨ 自動背景參考」自動找『低振動且有紋理』的區域\n"
                 "或用『右鍵拖曳』手動框一塊不會動的背景 (牆角 / 固定標記)"),
                ("3", "勾選「啟用補償」",
                 "系統計算 振動物位移 − 背景位移\n背景 (= 相機晃動) 會被抵銷"),
                ("4", "看驗證數據",
                 "工具列顯示「背景晃動 std」= 被扣掉的晃動量\n"
                 "值越大代表補償越有感 (手持 / 沒腳架時明顯)"),
                ("5", "驗證是否有效",
                 "手持輕晃相機: 未補償時頻譜會多出雜峰\n"
                 "開補償後主頻率應維持穩定 = 晃動已消除"),
            ],
            "tip": "原理: 背景靜止, 它在畫面中的位移純粹來自相機晃動\n"
                   "振動物位移 = 真實振動 + 相機晃動; 兩者相減 → 只剩真實振動\n"
                   "背景參考區要選『不會振動、但有紋理可追蹤』的地方",
        },
        "stability": {
            "title": "追蹤穩定性 (自動恢復 / 模糊偵測)  —  說明",
            "desc": "兩個讓長時間追蹤更穩的自動機制",
            "steps": [
                ("1", "追蹤失敗自動恢復",
                 "追蹤信心持續過低時, 先在整張畫面重新搜尋原模板\n找回來就自動重新鎖定, 不用人工重框"),
                ("2", "仍找不到 → 自動重新框選",
                 "全畫面也搜不到時, 自動重跑『振動區偵測』\n選出新的追蹤區繼續"),
                ("3", "模糊時暫停分析",
                 "用 Laplacian 變異數判斷畫面清晰度\n失焦 / 晃糊時暫停收集資料與 FFT"),
                ("4", "模糊解除自動恢復",
                 "畫面恢復清晰後自動繼續\n避免糊掉的幀污染頻譜"),
            ],
            "tip": "模糊判斷是相對的: 以最近數秒最清晰的畫面為基準\n"
                   "低於基準約 4 成才算模糊, 因此不同場景都適用\n"
                   "低紋理場景 (純色牆) 會自動略過模糊判斷避免誤判",
        },
        "low_light": {
            "title": "低光源增強  —  說明",
            "desc": "光線不足時用軟體自動增益補亮, 讓追蹤與頻譜更穩 (不依賴相機硬體)",
            "steps": [
                ("1", "勾選「啟用 (自動增益/gamma)」",
                 "程式量測整張畫面平均亮度\n自動算 gamma 把亮度拉到目標值 (約 120)"),
                ("2", "亮度自動收斂",
                 "gamma 隨畫面亮度平滑變化\n工具列顯示「亮度 → gamma」即時讀數"),
                ("3", "(選配)「去雜訊」",
                 "低光雜訊大時開啟\n用邊緣保留濾波 (bilateral) 壓雜訊又不糊掉紋理"),
                ("4", "配合 CLAHE 局部對比",
                 "搜尋區另有 CLAHE 增強局部對比\n兩者互補, 暗處紋理更容易追"),
            ],
            "tip": "追蹤用的模板比對 (TM_CCOEFF_NORMED) 對線性亮度不敏感,\n"
                   "所以自動增益不會破壞 template 與搜尋區的對應。\n"
                   "太暗時建議仍先加實體光源, 軟體增益會同時放大雜訊。",
        },
        "bandpass": {
            "title": "頻率分析 (帶通 / Top-3 / SNR)  —  說明",
            "desc": "限定分析頻段、列出前三大峰值、量化訊噪比, 讓主頻率更可靠",
            "steps": [
                ("1", "帶通濾波",
                 "勾選後只在『低 ~ 高』頻段內找峰與算 SNR\n"
                 "可濾掉低頻漂移 (DC 晃動) 與高頻雜訊"),
                ("2", "設定頻段",
                 "低: 想保留的最低頻 (例 0.5 Hz 濾掉緩慢漂移)\n"
                 "高: 想保留的最高頻 (留空 = 到取樣上限)"),
                ("3", "Top-3 峰值",
                 "主頻率卡片下方 / 頻譜圖標出前三大峰\n判斷是否有多個振動成分或諧波"),
                ("4", "SNR (訊噪比)",
                 "主頻率卡片顯示 SNR dB = 峰值 / 帶內雜訊中位數\n"
                 "越大代表主頻率越明確 (建議 ≥ 14 dB)"),
            ],
            "tip": "SNR 用相對中位數而非絕對門檻, 因此不同光線 / 振幅都適用。\n"
                   "主頻率至少要是帶內雜訊中位數的 5 倍才會被判定為有效峰值。",
        },
        "normal_csv": {
            "title": "正常震動資料 (基準庫)  —  操作流程",
            "desc": "把多次『正常狀態』的偵測結果存成 CSV, 統計出正常頻率範圍",
            "steps": [
                ("1", "取得穩定主頻率",
                 "先用攝影機/影片/麥克風偵測\n等頻譜出現明顯峰值 (SNR 足夠)"),
                ("2", "填樣本名稱",
                 "例如 normal_rail / motor_idle\n同名樣本會被歸為同一組統計"),
                ("3", "按「● 記錄正常樣本」",
                 "把主頻率 / Top-3 / SNR / 波形 / 位移 RMS\n等一整列寫入 normal_vibration.csv"),
                ("4", "多次記錄不同時間點",
                 "同一正常狀態多記幾筆 (建議 ≥ 5)\n樣本越多, 統計出的正常範圍越可靠"),
                ("5", "按「Σ 統計基準」",
                 "依樣本名稱分組算 主頻率 mean ± 3σ\n輸出正常範圍並存 normal_baseline.csv"),
            ],
            "tip": "CSV 用 utf-8-sig 編碼, Excel 直接打開中文不亂碼。\n"
                   "之後偵測值若落在 mean ± 3σ 之外, 即可視為異常震動。\n"
                   f"檔案位置: 與程式同目錄 (normal_vibration.csv)。",
        },
    }

    def _sync_flags(self):
        """把 checkbox 狀態鏡射成純 bool, 供背景 worker thread 安全讀取
        (Tcl 非執行緒安全, 不能在 worker 呼叫 Tk 變數的 .get())"""
        self._shake_comp = bool(self.shake_comp_var.get())
        self._auto_recover = bool(self.auto_recover_var.get())
        self._blur_detect = bool(self.blur_detect_var.get())
        self._low_light = bool(self.low_light_var.get())
        self._ll_denoise = bool(self.ll_denoise_var.get())

    def show_help(self, mode):
        info = self.HELP_CONTENT.get(mode)
        if not info:
            return
        self._open_help_window(info)

    def _open_help_window(self, info):
        win = tk.Toplevel(self.root)
        win.title(info["title"])
        win.configure(bg=self.BG)
        win.geometry("580x620")
        win.transient(self.root)
        win.grab_set()

        F = self.FONT_FAMILY

        # 標題列
        header = tk.Frame(win, bg=self.BG)
        header.pack(fill=tk.X, padx=20, pady=(18, 4))
        tk.Label(header, text=info["title"], bg=self.BG, fg=self.TEXT,
                 font=(F, 16, "bold")).pack(anchor=tk.W)
        tk.Label(header, text=info["desc"], bg=self.BG, fg=self.MUTED,
                 font=(F, 10)).pack(anchor=tk.W, pady=(2, 0))

        # 流程卡片
        steps_frame = tk.Frame(win, bg=self.BG)
        steps_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 6))

        for i, (num, title, desc) in enumerate(info["steps"]):
            card = tk.Frame(steps_frame, bg=self.CARD,
                            highlightbackground=self.BORDER, highlightthickness=1)
            card.pack(fill=tk.X)

            badge = tk.Label(card, text=num, bg=self.ACCENT, fg="#ffffff",
                             font=(F, 14, "bold"), width=3, height=2)
            badge.pack(side=tk.LEFT, padx=(10, 12), pady=10)

            txt = tk.Frame(card, bg=self.CARD)
            txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=10, padx=(0, 12))
            tk.Label(txt, text=title, bg=self.CARD, fg=self.TEXT,
                     font=(F, 11, "bold"), anchor=tk.W,
                     justify=tk.LEFT).pack(fill=tk.X)
            tk.Label(txt, text=desc, bg=self.CARD, fg=self.MUTED,
                     font=(F, 9), anchor=tk.W,
                     justify=tk.LEFT).pack(fill=tk.X, pady=(3, 0))

            if i < len(info["steps"]) - 1:
                tk.Label(steps_frame, text="▼", bg=self.BG, fg="#9ca3af",
                         font=(F, 11)).pack(pady=1)

        # 提示框
        tip = tk.Frame(win, bg="#eff6ff",
                       highlightbackground="#bfdbfe", highlightthickness=1)
        tip.pack(fill=tk.X, padx=20, pady=(8, 10))
        tk.Label(tip, text="提示", bg="#eff6ff", fg=self.ACCENT,
                 font=(F, 9, "bold")).pack(anchor=tk.W, padx=12, pady=(8, 0))
        tk.Label(tip, text=info["tip"], bg="#eff6ff", fg="#1e40af",
                 font=(F, 9), anchor=tk.W,
                 justify=tk.LEFT).pack(anchor=tk.W, padx=12, pady=(2, 10))

        # 關閉按鈕
        btn_row = tk.Frame(win, bg=self.BG)
        btn_row.pack(fill=tk.X, padx=20, pady=(0, 14))
        ttk.Button(btn_row, text="關閉", style="Accent.TButton",
                   command=win.destroy).pack(side=tk.RIGHT)

    def _setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        F = self.FONT_FAMILY
        style.configure(".", background=self.BG, foreground=self.TEXT, font=(F, 10))
        style.configure("TFrame", background=self.BG)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT, font=(F, 10))
        style.configure("Muted.TLabel", background=self.BG, foreground=self.MUTED, font=(F, 9))

        style.configure("Section.TLabelframe",
                        background=self.BG, borderwidth=1,
                        relief="solid", bordercolor=self.BORDER)
        style.configure("Section.TLabelframe.Label",
                        background=self.BG, foreground=self.MUTED, font=(F, 9, "bold"))

        style.configure("Dashboard.TLabelframe",
                        background=self.BG, borderwidth=1,
                        relief="solid", bordercolor="#cbd5e1")
        style.configure("Dashboard.TLabelframe.Label",
                        background=self.BG, foreground=self.TEXT,
                        font=(F, 10, "bold"))

        style.configure("Workspace.TLabelframe",
                        background=self.CARD, borderwidth=1,
                        relief="solid", bordercolor="#cbd5e1")
        style.configure("Workspace.TLabelframe.Label",
                        background=self.BG, foreground=self.TEXT,
                        font=(F, 10, "bold"))

        style.configure("TButton", padding=(10, 6), font=(F, 10),
                        background="#ffffff", foreground=self.TEXT,
                        borderwidth=1, relief="flat", bordercolor=self.BORDER)
        style.map("TButton",
                  background=[("active", "#f9fafb"), ("pressed", "#f3f4f6")],
                  bordercolor=[("active", self.ACCENT)])

        style.configure("Accent.TButton", padding=(12, 7), font=(F, 10, "bold"),
                        background=self.ACCENT, foreground="#ffffff",
                        borderwidth=0, relief="flat")
        style.map("Accent.TButton",
                  background=[("active", self.ACCENT_HOVER),
                              ("pressed", self.ACCENT_HOVER)],
                  foreground=[("active", "#ffffff")])

        style.configure("Stop.TButton", padding=(10, 6), font=(F, 10),
                        background="#fef2f2", foreground=self.ERROR,
                        borderwidth=1, relief="flat", bordercolor="#fecaca")
        style.map("Stop.TButton",
                  background=[("active", "#fee2e2"), ("pressed", "#fecaca")])

        style.configure("Help.TButton", padding=(4, 2), font=(F, 10, "bold"),
                        background="#eef2ff", foreground=self.ACCENT,
                        borderwidth=0, relief="flat")
        style.map("Help.TButton",
                  background=[("active", "#e0e7ff"), ("pressed", "#c7d2fe")])

        style.configure("Compact.TButton", padding=(8, 2), font=(F, 9),
                        background="#ffffff", foreground=self.ACCENT,
                        borderwidth=1, relief="flat", bordercolor=self.BORDER)
        style.map("Compact.TButton",
                  background=[("active", self.ACCENT_SOFT),
                              ("pressed", "#bfdbfe")])

        style.configure("TRadiobutton", background=self.BG,
                        foreground=self.TEXT, font=(F, 10))
        style.map("TRadiobutton", background=[("active", self.BG)])
        style.configure("TEntry", padding=4,
                        fieldbackground="#ffffff", bordercolor=self.BORDER)

    def _style_axis(self, ax):
        ax.set_facecolor(self.PLOT_BG)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color("#9ca3af")
            ax.spines[spine].set_linewidth(0.8)
        ax.tick_params(colors=self.MUTED, labelsize=9, length=3)
        ax.grid(True, alpha=0.5, linestyle="--", linewidth=0.5, color=self.GRID)

    def _set_x_axis_label(self, ax, text):
        ax.set_xlabel(text, fontsize=9, color=self.MUTED,
                      fontfamily=self.FONT_FAMILY)
        ax.xaxis.set_label_coords(1.02, -0.04)
        ax.xaxis.label.set_horizontalalignment("left")

    def _reset_session_frequency_range(self):
        self.session_min_freq = None
        self.session_max_freq = None
        if hasattr(self, "session_range_label"):
            self.session_range_label.config(
                text="本次範圍：最低 -- Hz｜最高 -- Hz")

    def _update_session_frequency_range(self, frequency):
        try:
            frequency = float(frequency)
        except (TypeError, ValueError):
            return
        if not np.isfinite(frequency) or frequency <= 0:
            return
        if self.session_min_freq is None or frequency < self.session_min_freq:
            self.session_min_freq = frequency
        if self.session_max_freq is None or frequency > self.session_max_freq:
            self.session_max_freq = frequency
        if hasattr(self, "session_range_label"):
            self.session_range_label.config(
                text=(f"本次範圍：最低 {self.session_min_freq:.2f} Hz｜"
                      f"最高 {self.session_max_freq:.2f} Hz"))

    def init_plots(self):
        F = self.FONT_FAMILY
        for ax in (self.ax_disp, self.ax_freq, self.ax_phase):
            self._style_axis(ax)
        self.ax_disp.set_title("訊號", fontsize=11, color=self.TEXT, fontfamily=F, pad=8, x=0.50)
        self._set_x_axis_label(self.ax_disp, "時間 (秒)")
        self.ax_disp.set_ylabel("振幅", fontsize=9, color=self.MUTED, fontfamily=F)
        self.ax_freq.set_title("頻譜 (振幅)", fontsize=11, color=self.TEXT, fontfamily=F, pad=8, x=0.50)
        self._set_x_axis_label(self.ax_freq, "頻率 (Hz)")
        self.ax_freq.set_ylabel("振幅", fontsize=9, color=self.MUTED, fontfamily=F)
        self.ax_phase.set_title("相位譜", fontsize=11, color=self.TEXT, fontfamily=F, pad=8, x=0.50)
        self._set_x_axis_label(self.ax_phase, "頻率 (Hz)")
        self.ax_phase.set_ylabel("相位 (°)", fontsize=9, color=self.MUTED, fontfamily=F)
        self.ax_phase.set_ylim(-190, 190)
        self.canvas_plot.draw()

    # ── ROI 選取（攝影機/影片模式）────────────────────────

    def on_mouse_down(self, event):
        if self.mode == "mic":
            return
        # 手動拖曳時取消正在進行的自動分析
        if self.auto_detecting:
            self.auto_detecting = False
            self.auto_frames.clear()
        self.selecting_roi = True
        self.roi_start = (event.x, event.y)

    def on_mouse_drag(self, event):
        if self.selecting_roi and self.roi_start:
            self.canvas_video.delete("roi_rect")
            self.canvas_video.create_rectangle(
                self.roi_start[0], self.roi_start[1], event.x, event.y,
                outline="lime", width=2, tags="roi_rect"
            )

    def _canvas_to_frame_rect(self, x1, y1, x2, y2):
        """把 canvas 上的拖曳矩形換算成影像座標 (ix, iy, w, h); 無影像則 None"""
        if self.frame_shape is None:
            return None
        cw = self.canvas_video.winfo_width()
        ch = self.canvas_video.winfo_height()
        fh, fw = self.frame_shape[:2]
        scale = min(cw / fw, ch / fh)
        offset_x = (cw - fw * scale) / 2
        offset_y = (ch - fh * scale) / 2
        ix1 = int((min(x1, x2) - offset_x) / scale)
        iy1 = int((min(y1, y2) - offset_y) / scale)
        ix2 = int((max(x1, x2) - offset_x) / scale)
        iy2 = int((max(y1, y2) - offset_y) / scale)
        ix1 = max(0, min(ix1, fw - 1))
        iy1 = max(0, min(iy1, fh - 1))
        ix2 = max(0, min(ix2, fw - 1))
        iy2 = max(0, min(iy2, fh - 1))
        return ix1, iy1, ix2 - ix1, iy2 - iy1

    def on_mouse_up(self, event):
        if not self.selecting_roi or not self.roi_start:
            return
        self.selecting_roi = False
        rect = self._canvas_to_frame_rect(self.roi_start[0], self.roi_start[1],
                                          event.x, event.y)
        if rect is None:
            return
        ix1, iy1, w, h = rect
        if w < 10 or h < 10:
            self.status_label.config(text="選取區域太小，請重新選取", fg="red")
            return

        with self._data_lock:
            self.roi = (ix1, iy1, w, h)
            self.template = None
            self.displacement_x.clear()
            self.displacement_y.clear()
            self.timestamps.clear()
            self.confidence_scores.clear()
            self.frame_count = 0
            self.consecutive_failures = 0
            self.track_lost_frames = 0
            self.comp_baseline = None
            self.noise_active = False
        self.status_label.config(text=f"追蹤區域: {w}x{h} @ ({ix1},{iy1})", fg="green")

    # ── 啟動來源 ─────────────────────────────────────────

    def start_camera(self):
        self.stop()
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            messagebox.showerror("錯誤", "無法開啟攝影機")
            return
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._reset_session_frequency_range()
        self.mode = "camera"
        self.running = True
        self._stop_event.clear()
        self.status_label.config(
            text=f"攝影機已開啟 (FPS={self.fps:.0f}, 最高偵測 {self.fps/2:.0f} Hz) — 即將自動分析振動區域",
            fg="blue"
        )
        self._worker_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self._worker_thread.start()
        # 相機暖機一下再啟動自動偵測, 避免第一張黑畫面被算進去
        self.root.after(200, self.auto_detect_roi)

    def open_file(self):
        path = filedialog.askopenfilename(
            title="選擇影片檔",
            filetypes=[("影片檔", "*.mp4 *.avi *.mov *.mkv *.wmv"), ("所有檔案", "*.*")]
        )
        if not path:
            return
        self.stop()
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            messagebox.showerror("錯誤", "無法開啟影片檔")
            return
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        # 診斷: 印出影片實際時長 / 幀數 / 計算出的平均 fps, 判斷是否 VFR
        frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count > 0:
            real_duration_s = frame_count / self.fps
            print(f"[video diag] nominal_fps={self.fps:.4f}  frame_count={frame_count}  "
                  f"implied_duration={real_duration_s:.2f}s  "
                  f"path={path}", flush=True)
        self._reset_session_frequency_range()
        self.mode = "file"
        self.running = True
        self._stop_event.clear()
        self.status_label.config(
            text=f"影片已載入 (FPS={self.fps:.0f}, 最高偵測 {self.fps/2:.0f} Hz) — 即將自動分析振動區域",
            fg="blue"
        )
        self._worker_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self._worker_thread.start()
        self.root.after(200, self.auto_detect_roi)

    def start_mic(self):
        self.stop()
        self._reset_session_frequency_range()
        self.mode = "mic"
        self.running = True
        self._stop_event.clear()
        with self._data_lock:
            self.audio_buffer.clear()

        # 顯示麥克風模式提示 (canvas 還沒 layout 時 winfo_width() 可能是 1, 延後重畫)
        self._draw_canvas_centered_text(
            "麥克風模式\n\n正在收音中...\n最高可偵測 22050 Hz",
            font_size=18
        )

        self.status_label.config(
            text=f"麥克風收音中 (取樣率={self.sample_rate} Hz, 最高偵測 {self.sample_rate//2} Hz)",
            fg="blue"
        )

        # 啟動音訊串流
        import sounddevice as sd
        self.audio_stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=2048,
            callback=self.audio_callback
        )
        self.audio_stream.start()

    def audio_callback(self, indata, frames, time_info, status):
        if not self.running or self._stop_event.is_set():
            return
        with self._data_lock:
            # deque(maxlen=sample_rate*2) 自動丟掉最舊的取樣
            self.audio_buffer.extend(indata[:, 0].tolist())
            buf_len = len(self.audio_buffer)
        if buf_len >= 4096:
            self.root.after(0, self.update_mic_plots)

    def stop(self):
        was_running = self.running and self.mode is not None
        self.running = False
        self._stop_event.set()

        # 等待 capture thread 真的退出再 release cap, 避免 cap.read() 與 release 競爭
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        self._worker_thread = None

        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.cap = None
        if self.audio_stream:
            try:
                self.audio_stream.stop()
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None

        # 在清除資料前顯示最終頻率
        if was_running:
            self.show_final_result()

        with self._data_lock:
            self.displacement_x.clear()
            self.displacement_y.clear()
            self.timestamps.clear()
            self.audio_buffer.clear()
        self.roi = None
        self.template = None
        self.frame_shape = None
        self.mode = None
        self.confidence_scores.clear()
        self.frame_count = 0
        self.consecutive_failures = 0
        self.correlation_threshold = 0.3
        self.auto_detecting = False
        self.auto_frames.clear()
        self.noise_active = False
        # 晃動補償 / 模糊 / 自動恢復 狀態歸零
        self.bg_roi = None
        self.bg_template = None
        self.bg_confidence = 0.0
        self.comp_baseline = None
        self.selecting_bg = False
        self.bg_hist_x.clear()
        self.bg_hist_y.clear()
        self.focus_history.clear()
        self.is_blurry = False
        self.blur_frames = 0
        self.track_lost_frames = 0

    # ── 攝影機/影片擷取迴圈 ─────────────────────────────

    def capture_loop(self):
        frame_interval = 1.0 / self.fps
        while (self.running and not self._stop_event.is_set()
               and self.cap and self.cap.isOpened()):
            t_start = time.time()
            ret, frame = self.cap.read()
            if not ret:
                self.root.after(0, self.on_video_finished)
                break

            self.frame_shape = frame.shape

            if self.auto_detecting:
                self._collect_auto_frame(frame)
            else:
                self.track_displacement(frame)

            if not self._stop_event.is_set():
                self.root.after(0, self.update_video, frame.copy())

            elapsed = time.time() - t_start
            wait = frame_interval - elapsed
            if wait > 0:
                # 用 Event.wait 取代 sleep, 讓 stop() 能即時喚醒
                if self._stop_event.wait(timeout=wait):
                    break

    # ── 自動框選振動區 ────────────────────────────────────

    def auto_detect_roi(self):
        if self.mode not in ("camera", "file") or not self.cap:
            messagebox.showinfo("提示", "請先開啟攝影機或影片")
            return
        if self.auto_detecting:
            return

        with self._data_lock:
            self.roi = None
            self.template = None
            self.displacement_x.clear()
            self.displacement_y.clear()
            self.timestamps.clear()
            self.confidence_scores.clear()
            self.frame_count = 0
            self.consecutive_failures = 0
            self.track_lost_frames = 0
            self.comp_baseline = None
            self.auto_frames.clear()
            self.noise_active = False
            # 重新框選後要用新場景建立清晰度基準，避免沿用失效 ROI 的舊基準。
            self.focus_history.clear()
            self.is_blurry = False
            self.blur_frames = 0

        # 找振動區; 若啟用晃動補償, 同一批幀順便挑一塊背景參考區
        self._auto_want_rail = True
        self._auto_want_bg = self._shake_comp
        self.auto_target = max(12, int(round(self.fps * 0.5)))
        self.auto_detecting = True
        self.status_label.config(
            text=f"● 自動分析中... 預計收集 {self.auto_target} 幀 (約 0.5 秒)",
            fg=self.ACCENT
        )

    def _collect_auto_frame(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = self._enhance_low_light(gray)  # [低光源增強] 低光時同步增強再算振動圖
        self.auto_frames.append(gray)
        c = len(self.auto_frames)
        if c % 5 == 0:
            self.root.after(0, lambda cc=c: self.status_label.config(
                text=f"● 自動分析中... {cc} / {self.auto_target} 幀",
                fg=self.ACCENT
            ))
        if c >= self.auto_target:
            self._compute_auto_roi()

    def _compute_auto_roi(self):
        frames = self.auto_frames
        self.auto_frames = []
        self.auto_detecting = False
        want_rail = self._auto_want_rail
        want_bg = self._auto_want_bg

        if len(frames) < 10:
            self.root.after(0, lambda: self.status_label.config(
                text="幀數不足無法分析 — 請手動拖曳 ROI", fg=self.ERROR))
            return

        # 每個像素隨時間的標準差 → 振動愈劇烈的地方值愈大
        stack = np.stack(frames, axis=0).astype(np.float32)
        motion_map = stack.std(axis=0)
        mean_gray = stack.mean(axis=0).astype(np.uint8)  # 挑背景時算紋理用

        fh, fw = motion_map.shape
        max_motion = float(motion_map.max())
        rail_roi = self.roi  # 只重算背景時沿用現有振動物 ROI

        # ── 振動物 ROI (取最會動的連通區) ──
        if want_rail:
            if max_motion < 1.5:
                self.root.after(0, lambda: self.status_label.config(
                    text="沒偵測到明顯振動 — 請手動拖曳 ROI 或加強光線", fg=self.ERROR))
                return

            threshold = float(np.percentile(motion_map, 95))
            mask = (motion_map >= threshold).astype(np.uint8) * 255
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

            num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
            if num_labels <= 1:
                self.root.after(0, lambda: self.status_label.config(
                    text="振動區域太分散 — 請手動拖曳 ROI", fg=self.ERROR))
                return

            areas = stats[1:, cv2.CC_STAT_AREA]
            best = int(np.argmax(areas)) + 1
            x = int(stats[best, cv2.CC_STAT_LEFT])
            y = int(stats[best, cv2.CC_STAT_TOP])
            bw = int(stats[best, cv2.CC_STAT_WIDTH])
            bh = int(stats[best, cv2.CC_STAT_HEIGHT])

            pad = 8
            x = max(0, x - pad)
            y = max(0, y - pad)
            bw = min(fw - x, bw + 2 * pad)
            bh = min(fh - y, bh + 2 * pad)

            if bw < 20 or bh < 20:
                self.root.after(0, lambda: self.status_label.config(
                    text=f"振動區域太小 ({bw}x{bh}) — 請手動拖曳 ROI", fg=self.ERROR))
                return

            rail_roi = (x, y, bw, bh)
            with self._data_lock:
                self.roi = rail_roi
                self.template = None
                self.comp_baseline = None

        # ── 背景參考 ROI (低振動 + 有紋理, 避開振動物) ──
        bg_roi = None
        if want_bg:
            bg_roi = self._pick_background_roi(mean_gray, motion_map, rail_roi)
            if bg_roi is not None:
                with self._data_lock:
                    self.bg_roi = bg_roi
                    self.bg_template = None
                    self.bg_hist_x.clear()
                    self.bg_hist_y.clear()
                    self.comp_baseline = None

        def _report():
            parts = []
            if want_rail and rail_roi:
                parts.append(f"振動區 {rail_roi[2]}x{rail_roi[3]} (強度 {max_motion:.1f})")
            if want_bg:
                parts.append(f"背景參考 {bg_roi[2]}x{bg_roi[3]}" if bg_roi
                             else "背景參考: 找不到合適低振動紋理區 (可右鍵手動框)")
            ok = (not want_bg) or bg_roi is not None
            self.status_label.config(
                text="● 自動選取完成: " + "  ｜  ".join(parts),
                fg=self.SUCCESS if ok else self.ACCENT)
        self.root.after(0, _report)

    # ── 噪聲基準量測 (次像素 noise floor) ─────────────────

    def measure_noise_floor(self):
        if self.mode not in ("camera", "file"):
            messagebox.showinfo("提示", "請先開啟攝影機或影片並設好 ROI")
            return
        if self.roi is None or self.template is None:
            messagebox.showinfo("提示", "請等追蹤穩定 (狀態列顯示「追蹤中」) 後再量")
            return
        if self.noise_active:
            return
        with self._data_lock:
            self.noise_start_n = len(self.displacement_y)
        self.noise_target_count = max(30, int(round(self.fps * 2)))
        self.noise_active = True
        self.status_label.config(
            text=f"● 量噪聲基準: 請保持物體靜止 ~2 秒 (將收集 {self.noise_target_count} 幀)",
            fg=self.ACCENT)

    def _show_noise_floor(self, rms_x, rms_y):
        rms_total = float(np.sqrt(rms_x * rms_x + rms_y * rms_y))
        suggested = 3.0 * rms_total
        msg = (
            f"位移雜訊基準 (靜止狀態 std):\n\n"
            f"   水平 (x):  {rms_x:.3f} 像素\n"
            f"   垂直 (y):  {rms_y:.3f} 像素\n"
            f"   合成:      {rms_total:.3f} 像素\n\n"
            f"判讀:\n"
            f"   • 此值就是次像素演算法 + 鏡頭抖動 + 光線雜訊的綜合下限\n"
            f"   • 振動振幅需 ≥ 此值 3~5 倍才能可靠偵測\n"
            f"   • 建議可偵測振幅下限: {suggested:.3f} 像素\n\n"
            f"若值太大可嘗試:\n"
            f"   • 增加環境光\n"
            f"   • 換紋理對比更強的 ROI (角落 / 文字 / 反差大邊緣)\n"
            f"   • 改用更穩的相機支架 (三腳架)"
        )
        messagebox.showinfo("噪聲基準量測結果", msg)
        self.status_label.config(
            text=f"● 噪聲基準: x={rms_x:.3f}px  y={rms_y:.3f}px  → 可測振幅 ≥ {suggested:.3f}px",
            fg=self.SUCCESS)

    def _throttled_status(self, text, color):
        """節流的 status 更新 (可安全從 worker thread 呼叫)"""
        now = time.time()
        if now - self._last_status_time >= self._status_min_interval:
            self._last_status_time = now
            self.root.after(0, lambda: self.status_label.config(text=text, fg=color))

    # ═══════════════════════════════════════════════════════════════════
    #  模糊偵測 (功能三)  —  Blur Detection
    #
    #  以 Laplacian 變異數量化清晰度, 相對近期最清晰畫面判斷模糊。
    #  可獨立搬移的方法只有 _update_blur_state; 另有 2 處內嵌 hook,
    #  已於原處以 [模糊偵測] 標記:
    #    • track_displacement() → 模糊時提前 return, 暫停收集資料與 FFT
    #    • update_video()       → 畫面左下「模糊」警告橫幅
    #  狀態初始化見 __init__ 的「模糊偵測」段。
    # ═══════════════════════════════════════════════════════════════════

    def _update_blur_state(self, gray_raw):
        """以 Laplacian 變異數判斷是否模糊 (相對近期最清晰畫面)。
        回傳 True = 模糊 (應暫停分析)。"""
        if not self._blur_detect:
            self.is_blurry = False
            return False
        focus = float(cv2.Laplacian(gray_raw, cv2.CV_64F).var())
        if len(self.focus_history) < 15:
            self.focus_history.append(focus)
            self.is_blurry = False
            return False
        baseline = float(np.percentile(self.focus_history, 80))
        if baseline < 30.0:
            # 場景本身低紋理 → 不做模糊判斷, 避免整片誤判為模糊
            self.focus_history.append(focus)
            self.is_blurry = False
            return False
        self.is_blurry = focus < self.blur_ratio * baseline
        # 模糊幀不可寫回清晰度基準，否則高 FPS 下舊清晰幀會先被擠出，
        # baseline 隨模糊畫面下降，導致持續模糊被誤判成「已恢復」。
        if not self.is_blurry:
            self.focus_history.append(focus)
        return self.is_blurry

    # ═══════════════════════════════ 模糊偵測區塊結束 ═══════════════════

    # ═══════════════════════════════════════════════════════════════════
    #  低光源增強 (功能四)  —  Low-light Enhancement (軟體自動增益)
    #
    #  依整體平均亮度自動算 gamma (讓平均收斂到目標亮度), 時間平滑避免
    #  template 亮度突跳; 選配 bilateral 去雜訊。TM_CCOEFF_NORMED 對線性
    #  亮度/對比不變, gamma 又緩慢變化 → 不破壞 template↔搜尋區的對應。
    #  CLAHE(局部對比) 仍在 _locate 內對搜尋區另做, 兩者互補。
    #
    #  本區塊集中可獨立搬移的方法 (_gamma_lut / _enhance_low_light /
    #  _apply_display_gamma)。另有 4 處內嵌 hook 已於原處以 [低光源增強] 標記:
    #    • track_displacement()   → 增強灰階後再追蹤
    #    • _collect_auto_frame()  → 自動框選振動區時同步增強
    #    • update_video()         → 顯示幀套用同一 gamma
    #    • update_camera_plots()  → 亮度 / gamma 讀數
    #  UI 控制項見 build_ui「低光源增強」frame; 狀態初始化見 __init__ 同名段。
    # ═══════════════════════════════════════════════════════════════════

    def _gamma_lut(self, gamma):
        lut = (np.arange(256, dtype=np.float32) / 255.0) ** gamma
        return np.clip(lut * 255.0, 0, 255).astype(np.uint8)

    def _enhance_low_light(self, gray):
        """回傳增強後的灰階影像 (worker thread 呼叫)。未啟用時原樣回傳。"""
        mean = float(gray.mean())
        self.ll_mean = mean
        if not self._low_light:
            self.ll_gamma = 1.0
            return gray
        if self._ll_denoise:
            # 邊緣保留去雜訊; 比 fastNlMeansDenoising 快很多, 適合即時
            gray = cv2.bilateralFilter(gray, 5, 40, 40)
            mean = float(gray.mean())
        # 目標亮度 → gamma: m^gamma = target (夾在合理範圍避免過曝/雜訊爆增)
        m = min(254.0, max(1.0, mean)) / 255.0
        tgt = self.ll_target / 255.0
        desired = float(np.log(tgt) / np.log(m))
        desired = min(2.5, max(0.35, desired))
        # 時間平滑
        self.ll_gamma += 0.15 * (desired - self.ll_gamma)
        return cv2.LUT(gray, self._gamma_lut(self.ll_gamma))

    def _apply_display_gamma(self, frame):
        """把目前的 low-light gamma 套到彩色顯示幀 (主緒), 讓使用者看到增強效果。"""
        if not self._low_light or abs(self.ll_gamma - 1.0) < 0.02:
            return frame
        return cv2.LUT(frame, self._gamma_lut(self.ll_gamma))

    # ═══════════════════════════════ 低光源增強結束 ═══════════════════

    def _locate(self, gray, anchor, template, search_margin):
        """模板比對共用函式 (rail 追蹤與 [晃動補償] 背景追蹤共用)。
        在 anchor(x,y,w,h) 周圍 search_margin 範圍內比對 template。
        回傳 (found_x, found_y, max_val): template 左上角在整張影像的次像素座標。
        搜尋區比模板小則回傳 (None, None, 0.0)。"""
        x, y, w, h = anchor
        m = search_margin
        fh, fw = gray.shape
        sx1 = max(0, x - m)
        sy1 = max(0, y - m)
        sx2 = min(fw, x + w + m)
        sy2 = min(fh, y + h + m)
        # CLAHE 只對搜尋區做, 模板建立時也做過 → 亮度對應一致
        search_area = self._clahe.apply(gray[sy1:sy2, sx1:sx2])
        if (search_area.shape[0] < template.shape[0]
                or search_area.shape[1] < template.shape[1]):
            return None, None, 0.0

        result = cv2.matchTemplate(search_area, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        # 次像素內插：以 3x3 相關係數峰值作二維二次曲面擬合。
        # 相較於分別沿 x/y 做一維拋物線，此作法包含 xy 交叉項，
        # 對斜向的微小振動較準確。峰值在邊界或曲面不穩定時，
        # 保留整數像素座標，避免低信心影格製造假的次像素位移。
        px, py = max_loc
        rh, rw = result.shape
        sub_x = float(px)
        sub_y = float(py)
        if 0 < px < rw - 1 and 0 < py < rh - 1:
            # f(dx,dy) = ax² + by² + cdxdy + ddx + edy + k
            # Least-squares fit over the local 3x3 neighbourhood.
            yy, xx = np.mgrid[-1:2, -1:2]
            design = np.column_stack((
                (xx * xx).ravel(), (yy * yy).ravel(), (xx * yy).ravel(),
                xx.ravel(), yy.ravel(), np.ones(9),
            ))
            values = result[py - 1:py + 2, px - 1:px + 2].astype(float).ravel()
            try:
                a, b, c, d, e, _ = np.linalg.lstsq(design, values, rcond=None)[0]
                hessian = np.array(((2.0 * a, c), (c, 2.0 * b)))
                offset = np.linalg.solve(hessian, -np.array((d, e)))
                # 只接受在鄰域內、且為局部最大值的解。
                if (np.all(np.isfinite(offset))
                        and np.all(np.abs(offset) <= 1.0)
                        and a < 0.0 and b < 0.0
                        and np.linalg.det(hessian) > 1e-9):
                    sub_x += float(offset[0])
                    sub_y += float(offset[1])
            except np.linalg.LinAlgError:
                pass

        return sx1 + sub_x, sy1 + sub_y, max_val

    # ═══════════════════════════════════════════════════════════════════
    #  ROI 自動恢復 (功能二)  —  Auto-Recovery
    #
    #  追蹤信心持續過低時, 兩階段自動找回目標, 免人工重框:
    #    階段一  全畫面重搜原模板 → 找回即重新鎖定
    #    階段二  全畫面也失敗 → 重跑自動框選 (auto_detect_roi)
    #  可獨立搬移的方法只有 _handle_tracking_lost; 內嵌 hook 已標 [自動恢復]:
    #    • track_displacement() → 信心過低時累計失幀並呼叫本方法
    #  狀態初始化見 __init__ 的「ROI 自動恢復」段。
    # ═══════════════════════════════════════════════════════════════════

    def _handle_tracking_lost(self, gray):
        """追蹤信心持續過低: 先全畫面重搜原模板, 再不行就重跑自動框選。"""
        if not self._auto_recover:
            return
        roi = self.roi
        if roi is None or self.template is None:
            return
        fh, fw = gray.shape
        w, h = roi[2], roi[3]

        # 階段一: 整張畫面重新搜尋現有模板 (只在剛達門檻那一幀做一次, 省 CPU)
        if self.track_lost_frames == self.recovery_search_after:
            fx, fy, val = self._locate(gray, roi, self.template, max(fw, fh))
            if fx is not None and val >= 0.4:
                nx = int(max(0, min(round(fx), fw - w)))
                ny = int(max(0, min(round(fy), fh - h)))
                with self._data_lock:
                    self.roi = (nx, ny, w, h)
                    self.comp_baseline = None
                self.template_offset = (nx, ny)
                self.consecutive_failures = 0
                self.track_lost_frames = 0
                self.confidence_scores.clear()
                self._throttled_status("● 自動恢復: 已重新鎖定追蹤區", self.SUCCESS)
                return

        # 階段二: 全畫面也搜不到 → 重跑自動框選振動區
        if self.track_lost_frames >= self.recovery_reset_after and not self.auto_detecting:
            self.track_lost_frames = 0
            self._throttled_status("● 追蹤遺失 — 自動重新框選振動區...", self.ACCENT)
            self.root.after(0, self.auto_detect_roi)

    # ═══════════════════════════════ 自動恢復區塊結束 ═══════════════════

    # ═══════════════════════════════════════════════════════════════════
    #  攝影機晃動補償 (功能一)  —  背景參考 ROI
    #
    #  同時追蹤『振動物 ROI』與『靜止背景 ROI』, 兩者以絕對座標相減即可
    #  抵銷相機 / 手持晃動 (背景是靜止的, 它的位移純粹來自相機晃動)。
    #
    #  本區塊集中所有「可獨立搬移」的方法。另有 3 處內嵌於大方法無法搬出,
    #  已於原處以 [晃動補償] 標記, 方便對照:
    #    • track_displacement()  → 呼叫 _track_background() 並做相減補償
    #    • update_camera_plots()  → 背景晃動 std 驗證讀數
    #  共用函式 _locate() (rail 追蹤與背景追蹤共用) 定義於上方追蹤輔助區。
    # ═══════════════════════════════════════════════════════════════════

    def _track_background(self, gray):
        """追蹤靜止背景 ROI → 它的位移即相機晃動量。背景不 re-anchor。"""
        bg_roi = self.bg_roi
        if bg_roi is None:
            self.bg_confidence = 0.0
            return
        if self.bg_template is None:
            x, y, w, h = bg_roi
            self.bg_template = self._clahe.apply(gray[y:y+h, x:x+w]).copy()
            self.bg_template_offset = (x, y)
            self.bg_search_margin = max(w, h)
            self.bg_found_x = float(x)
            self.bg_found_y = float(y)
            self.bg_confidence = 1.0
            return

        fx, fy, val = self._locate(gray, bg_roi, self.bg_template, self.bg_search_margin)
        self.bg_confidence = val
        if fx is None or val < 0.2:
            return  # 沒對上 → 保留上一次位置 (別讓補償亂跳)
        self.bg_found_x = fx
        self.bg_found_y = fy
        bx, by = self.bg_template_offset
        with self._data_lock:
            self.bg_hist_x.append(fx - bx)
            self.bg_hist_y.append(fy - by)

    def _pick_background_roi(self, mean_gray, motion_map, rail_roi):
        """在低振動且有紋理的地方挑一塊當背景參考 (避開振動物 ROI)。
        分數 = 紋理 / (1 + 振動): 動得少又紋理強者勝。"""
        fh, fw = motion_map.shape
        win = int(min(80, max(32, min(fw, fh) // 8)))
        if fw <= win or fh <= win:
            return None
        step = max(8, win // 2)
        # 局部梯度強度 → 紋理 (matchTemplate 需要紋理才追得動)
        gx = cv2.Sobel(mean_gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(mean_gray, cv2.CV_32F, 0, 1, ksize=3)
        grad = cv2.magnitude(gx, gy)

        rx, ry, rw, rh = rail_roi if rail_roi else (0, 0, 0, 0)
        best = None  # (score, x, y, texture)
        for yy in range(0, fh - win + 1, step):
            for xx in range(0, fw - win + 1, step):
                # 與振動物 ROI 重疊 (含 10px margin) 則跳過
                if rail_roi and not (xx + win < rx - 10 or xx > rx + rw + 10
                                     or yy + win < ry - 10 or yy > ry + rh + 10):
                    continue
                motion = float(motion_map[yy:yy+win, xx:xx+win].mean())
                texture = float(grad[yy:yy+win, xx:xx+win].mean())
                score = texture / (1.0 + 3.0 * motion)
                if best is None or score > best[0]:
                    best = (score, xx, yy, texture)
        if best is None or best[3] < 8.0:
            return None  # 沒有足夠紋理可當背景參考
        return (best[1], best[2], win, win)

    def auto_detect_background(self):
        """只重新挑背景參考區 (振動物 ROI 沿用現有)"""
        if self.mode not in ("camera", "file") or not self.cap:
            messagebox.showinfo("提示", "請先開啟攝影機或影片")
            return
        if self.auto_detecting:
            return
        with self._data_lock:
            self.auto_frames.clear()
        self._auto_want_rail = False
        self._auto_want_bg = True
        self.auto_target = max(12, int(round(self.fps * 0.5)))
        self.auto_detecting = True
        self.status_label.config(
            text=f"● 分析背景參考區... 收集 {self.auto_target} 幀 (請保持場景靜止)",
            fg=self.ACCENT)

    # ── 背景參考 ROI 選取 (右鍵拖曳) ──
    def on_bg_mouse_down(self, event):
        if self.mode == "mic" or self.frame_shape is None:
            return
        self.selecting_bg = True
        self.bg_roi_start = (event.x, event.y)

    def on_bg_mouse_drag(self, event):
        if self.selecting_bg and self.bg_roi_start:
            self.canvas_video.delete("bg_rect")
            self.canvas_video.create_rectangle(
                self.bg_roi_start[0], self.bg_roi_start[1], event.x, event.y,
                outline="#f59e0b", width=2, tags="bg_rect"
            )

    def on_bg_mouse_up(self, event):
        if not self.selecting_bg or not self.bg_roi_start:
            return
        self.selecting_bg = False
        rect = self._canvas_to_frame_rect(self.bg_roi_start[0], self.bg_roi_start[1],
                                          event.x, event.y)
        if rect is None:
            return
        ix1, iy1, w, h = rect
        if w < 10 or h < 10:
            self.status_label.config(text="背景參考區太小，請重新選取", fg="red")
            return
        with self._data_lock:
            self.bg_roi = (ix1, iy1, w, h)
            self.bg_template = None
            self.bg_hist_x.clear()
            self.bg_hist_y.clear()
            self.comp_baseline = None
        self.status_label.config(
            text=f"背景參考區: {w}x{h} @ ({ix1},{iy1}) — 勾選「啟用補償」即生效",
            fg=self.SUCCESS)

    # ═══════════════════════════════ 晃動補償區塊結束 ═══════════════════

    def track_displacement(self, frame):
        # snapshot 一次 → 防止 main thread 中途把 self.roi 設成 None / 換成不同 size
        roi = self.roi
        if roi is None:
            return
        x, y, w, h = roi
        gray_raw = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # ── [模糊偵測] 失焦/晃糊時暫停資料收集與 FFT (見「模糊偵測」區塊) ──
        if self._update_blur_state(gray_raw):
            self.blur_frames += 1
            blur_recovery_after = max(15, int(round(self.fps * 2.0)))
            if self.blur_frames >= blur_recovery_after:
                self.blur_frames = 0
                self._throttled_status(
                    "● 持續模糊 — 正在自動重新框選振動區...", self.ERROR)
                self.root.after(0, self.auto_detect_roi)
            else:
                self._throttled_status(
                    "● 畫面模糊 — 已暫停 FFT 分析 (請對焦或穩定畫面)", self.ERROR)
            return
        self.blur_frames = 0

        # [低光源增強] 自動 gamma/去雜訊 (見「低光源增強」區塊); 未啟用時原樣
        gray_e = self._enhance_low_light(gray_raw)
        gray = cv2.GaussianBlur(gray_e, (3, 3), 0)
        # 不做全局 equalizeHist: 它會隨畫面內容變化, 破壞 template 與 search area
        # 的亮度對應. 改在 search area 局部用 CLAHE (在 _locate 裁切後再做)

        if self.template is None:
            roi_patch = gray[y:y+h, x:x+w]
            self.template = self._clahe.apply(roi_patch).copy()
            self.template_offset = (x, y)
            self.search_margin = max(w, h)
            self.frame_count = 0
            self.consecutive_failures = 0
            self.track_lost_frames = 0
            self.comp_baseline = None
            return

        self.frame_count += 1

        # ── [晃動補償] 背景參考追蹤 → 定義見「攝影機晃動補償」區塊 ──
        self._track_background(gray)

        # ── 主 (振動物) ROI 追蹤: 模板比對 + 次像素內插 ──
        found_x, found_y, max_val = self._locate(
            gray, roi, self.template, self.search_margin)
        if found_x is None:
            return  # 搜尋區比模板還小

        # 相關系數平滑：deque(maxlen=10) 自動丟最舊
        self.confidence_scores.append(max_val)
        avg_confidence = float(np.mean(self.confidence_scores))

        # 自適應閾值：連續失敗則降低閾值
        if avg_confidence < self.correlation_threshold:
            self.consecutive_failures += 1
            if self.consecutive_failures > 5:
                self.correlation_threshold = max(0.15, self.correlation_threshold - 0.02)
        else:
            self.consecutive_failures = 0
            self.correlation_threshold = min(0.35, self.correlation_threshold + 0.01)

        if avg_confidence < self.correlation_threshold:
            # [自動恢復] 追蹤失敗 → 全畫面重搜 → 重新框選 (見「ROI 自動恢復」區塊)
            self.track_lost_frames += 1
            self._handle_tracking_lost(gray)
            return

        self.track_lost_frames = 0
        fh, fw = gray.shape

        # ── [晃動補償] 位移計算 (振動物 − 背景, 抵銷相機晃動) ──
        # 條件不看『本幀』信心, 避免背景比對偶爾掉分時在兩種公式間跳動
        # (污染同一段 FFT 資料). 背景短暫沒對上時 _track_background 會沿用上一位置。
        comp_active = (self._shake_comp and self.bg_roi is not None
                       and self.bg_template is not None)
        if comp_active:
            # 振動物與背景含相同的相機晃動, 兩者絕對座標相減即抵銷晃動;
            # 再扣掉初始基準讓訊號從 0 起算 (FFT 後續還會去均值)
            rel_x = found_x - self.bg_found_x
            rel_y = found_y - self.bg_found_y
            if self.comp_baseline is None:
                self.comp_baseline = (rel_x, rel_y)
            dx = rel_x - self.comp_baseline[0]
            dy = rel_y - self.comp_baseline[1]
        else:
            # 未補償: 位移以 template 上次被擷取的位置為基準
            tx, ty = self.template_offset
            dx = found_x - tx
            dy = found_y - ty

        with self._data_lock:
            t = len(self.displacement_y) / self.fps
            self.displacement_x.append(dx)
            self.displacement_y.append(dy)
            self.timestamps.append(t)
            count = len(self.displacement_y)

        # 用 wall-clock 節流, 不再依賴 frame count → 高 FPS 影片不會把 main thread 灌爆
        now = time.time()
        if now - self._last_status_time >= self._status_min_interval:
            self._last_status_time = now
            comp_txt = "  ｜  晃動補償 ON" if comp_active else ""
            self.root.after(0, lambda c=count, ac=avg_confidence, ct=comp_txt:
                            self.status_label.config(
                                text=f"追蹤中... 已收集 {c} 筆資料 (信心: {ac:.2f}){ct}",
                                fg="green"))
        # FFT 起始門檻 32 幀, 之後最少間隔 _plot_min_interval 才重畫一次
        if count >= 32 and now - self._last_plot_time >= self._plot_min_interval:
            self._last_plot_time = now
            self.root.after(0, self.update_camera_plots)

        # 噪聲基準量測: 收集到指定樣本後計算 std 並彈出結果
        if self.noise_active and count - self.noise_start_n >= self.noise_target_count:
            with self._data_lock:
                start = self.noise_start_n
                target = self.noise_target_count
                sx = list(self.displacement_x[start:start + target])
                sy = list(self.displacement_y[start:start + target])
                self.noise_active = False
            rms_x = float(np.std(sx)) if sx else 0.0
            rms_y = float(np.std(sy)) if sy else 0.0
            self.root.after(0, lambda rx=rms_x, ry=rms_y: self._show_noise_floor(rx, ry))

        # 模板動態更新：以最近匹配位置 (round) re-anchor, 否則 ROI 漂移時模板會錯位
        if (self.frame_count % self.template_update_interval == 0
                or self.consecutive_failures > 10):
            new_x = int(max(0, min(round(found_x), fw - w)))
            new_y = int(max(0, min(round(found_y), fh - h)))
            new_patch = gray[new_y:new_y + h, new_x:new_x + w]
            if new_patch.shape == (h, w):
                self.template = self._clahe.apply(new_patch).copy()
                self.template_offset = (new_x, new_y)
                self.consecutive_failures = 0

    # ── 畫面更新 ─────────────────────────────────────────

    def _draw_dashed_rect(self, frame, x, y, w, h, color, thickness=2, dash=14, gap=8):
        x2, y2 = x + w, y + h
        # 上邊
        for dx in range(x, x2, dash + gap):
            cv2.line(frame, (dx, y), (min(dx + dash, x2), y), color, thickness)
        # 下邊
        for dx in range(x, x2, dash + gap):
            cv2.line(frame, (dx, y2), (min(dx + dash, x2), y2), color, thickness)
        # 左邊
        for dy in range(y, y2, dash + gap):
            cv2.line(frame, (x, dy), (x, min(dy + dash, y2)), color, thickness)
        # 右邊
        for dy in range(y, y2, dash + gap):
            cv2.line(frame, (x2, dy), (x2, min(dy + dash, y2)), color, thickness)

    def _draw_canvas_centered_text(self, text, font_size=18, fill="white"):
        """在影像 canvas 中央寫一行字; canvas 尚未 layout 時延後重畫一次"""
        cw = self.canvas_video.winfo_width()
        ch = self.canvas_video.winfo_height()
        if cw < 10 or ch < 10:
            # 還沒被 layout, 100ms 後再試
            self.root.after(100, lambda: self._draw_canvas_centered_text(text, font_size, fill))
            return
        self.canvas_video.delete("all")
        self.canvas_video.create_text(
            cw // 2, ch // 2,
            text=text, fill=fill,
            font=("Microsoft JhengHei", font_size), justify=tk.CENTER
        )

    def _draw_final_result_text(self, title, final_freq):
        """顯示停止後的最終頻率; canvas 尚未 layout 時延後重畫一次"""
        cw = self.canvas_video.winfo_width()
        ch = self.canvas_video.winfo_height()
        if cw < 10 or ch < 10:
            self.root.after(100, lambda: self._draw_final_result_text(title, final_freq))
            return
        self.canvas_video.delete("all")
        self.canvas_video.create_text(
            cw // 2, ch // 2 - 20, text=title,
            fill="white", font=("Microsoft JhengHei", 22, "bold"), justify=tk.CENTER
        )
        self.canvas_video.create_text(
            cw // 2, ch // 2 + 30, text=final_freq,
            fill="lime", font=("Microsoft JhengHei", 28, "bold"), justify=tk.CENTER
        )

    def _draw_corner_markers(self, frame, x, y, w, h, color, length=18, thickness=4):
        x2, y2 = x + w, y + h
        # 左上
        cv2.line(frame, (x, y), (x + length, y), color, thickness)
        cv2.line(frame, (x, y), (x, y + length), color, thickness)
        # 右上
        cv2.line(frame, (x2, y), (x2 - length, y), color, thickness)
        cv2.line(frame, (x2, y), (x2, y + length), color, thickness)
        # 左下
        cv2.line(frame, (x, y2), (x + length, y2), color, thickness)
        cv2.line(frame, (x, y2), (x, y2 - length), color, thickness)
        # 右下
        cv2.line(frame, (x2, y2), (x2 - length, y2), color, thickness)
        cv2.line(frame, (x2, y2), (x2, y2 - length), color, thickness)

    def update_video(self, frame):
        if not self.running:
            return

        # [低光源增強] 顯示幀套用同一 gamma, 讓使用者看到增強後畫面 (需在畫框前)
        frame = self._apply_display_gamma(frame)

        fh, fw = frame.shape[:2]

        # 自動分析模式: 整張畫面黃色虛線外框
        if self.auto_detecting:
            self._draw_dashed_rect(frame, 4, 4, fw - 8, fh - 8,
                                   color=(0, 215, 255), thickness=3, dash=16, gap=10)

        # 追蹤 ROI: 綠色方框 + 四角標記
        if self.roi:
            x, y, w, h = self.roi
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            self._draw_corner_markers(frame, x, y, w, h,
                                      color=(0, 255, 0), length=16, thickness=4)

        # 背景參考 ROI: 琥珀色方框 (BGR)
        if self.bg_roi:
            bx, by, bw, bh = self.bg_roi
            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 165, 255), 2)

        cw = self.canvas_video.winfo_width()
        ch = self.canvas_video.winfo_height()
        if cw < 10 or ch < 10:
            return

        scale = min(cw / fw, ch / fh)
        new_w, new_h = int(fw * scale), int(fh * scale)
        resized = cv2.resize(frame, (new_w, new_h))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

        img = Image.fromarray(rgb)
        self.photo_image = ImageTk.PhotoImage(img)
        self.canvas_video.delete("all")
        self.canvas_video.create_image(cw // 2, ch // 2,
                                       image=self.photo_image, anchor=tk.CENTER)

        # 中文進度提示 (放在 canvas 上, 避開 OpenCV 不支援 CJK 的問題)
        if self.auto_detecting:
            c = len(self.auto_frames)
            pct = int(100 * c / max(1, self.auto_target))
            text = f"● 自動分析中   {c} / {self.auto_target} 幀   ({pct}%)"
            # 半透明黑底
            self.canvas_video.create_rectangle(
                14, 14, 14 + 360, 14 + 36,
                fill="#000000", stipple="gray50", outline="#ffd700", width=2
            )
            self.canvas_video.create_text(
                26, 32, text=text, anchor=tk.W,
                fill="#ffd700",
                font=("Microsoft JhengHei", 12, "bold")
            )

        # ROI 標籤 (追蹤中時)
        if self.roi and not self.auto_detecting:
            x, y, w, h = self.roi
            sc = min(cw / fw, ch / fh)
            off_x = (cw - fw * sc) / 2
            off_y = (ch - fh * sc) / 2
            lx = off_x + x * sc
            ly = off_y + y * sc - 22
            self.canvas_video.create_rectangle(
                lx, ly, lx + 72, ly + 20,
                fill="#16a34a", outline=""
            )
            self.canvas_video.create_text(
                lx + 8, ly + 10, text="追蹤中",
                fill="white", anchor=tk.W,
                font=("Microsoft JhengHei", 9, "bold")
            )

        # 背景參考標籤
        if self.bg_roi and not self.auto_detecting:
            bx, by, bw, bh = self.bg_roi
            sc = min(cw / fw, ch / fh)
            off_x = (cw - fw * sc) / 2
            off_y = (ch - fh * sc) / 2
            lx = off_x + bx * sc
            ly = off_y + by * sc - 22
            self.canvas_video.create_rectangle(
                lx, ly, lx + 84, ly + 20, fill="#d97706", outline=""
            )
            self.canvas_video.create_text(
                lx + 8, ly + 10, text="背景參考",
                fill="white", anchor=tk.W,
                font=("Microsoft JhengHei", 9, "bold")
            )

        # [模糊偵測] 模糊警告橫幅 (畫面左下)
        if self.is_blurry and self.mode in ("camera", "file"):
            self.canvas_video.create_rectangle(
                14, ch - 50, 14 + 300, ch - 14,
                fill="#000000", stipple="gray50", outline="#ef4444", width=2
            )
            self.canvas_video.create_text(
                26, ch - 32, text="● 畫面模糊 — 已暫停分析", anchor=tk.W,
                fill="#ef4444", font=("Microsoft JhengHei", 12, "bold")
            )

    # ── 攝影機/影片圖表 ─────────────────────────────────

    def update_camera_plots(self):
        # 在 lock 內取 snapshot, 避免讀 disp_x/disp_y 時 worker 還在 append
        # 造成兩個陣列長度不一致 → FFT 用到錯誤的 signal
        with self._data_lock:
            t = np.array(self.timestamps, dtype=float)
            sig_x = np.array(self.displacement_x, dtype=float)
            sig_y = np.array(self.displacement_y, dtype=float)
        # 安全裁切到相同長度 (即使 lock 也是再保險)
        n = min(len(t), len(sig_x), len(sig_y))
        if n == 0:
            return
        t, sig_x, sig_y = t[:n], sig_x[:n], sig_y[:n]

        # [晃動補償] 背景晃動量讀數 (驗證: 這就是補償會扣掉的相機晃動)
        if hasattr(self, "bg_shake_label"):
            with self._data_lock:
                bxs = np.array(self.bg_hist_x, dtype=float)
                bys = np.array(self.bg_hist_y, dtype=float)
            if self.bg_roi is not None and bxs.size > 5:
                self.bg_shake_label.config(
                    text=f"背景晃動 std  x={np.std(bxs):.2f}  y={np.std(bys):.2f} px",
                    fg=self.SUCCESS if self._shake_comp else self.MUTED)
            else:
                self.bg_shake_label.config(
                    text="背景晃動: 未設定背景參考區", fg=self.MUTED)

        # [低光源增強] 亮度 / gamma 讀數 (見「低光源增強」區塊)
        if hasattr(self, "ll_label"):
            if self._low_light:
                self.ll_label.config(
                    text=f"亮度: {self.ll_mean:.0f} → gamma {self.ll_gamma:.2f}",
                    fg=self.SUCCESS)
            else:
                self.ll_label.config(text=f"亮度: {self.ll_mean:.0f}", fg=self.MUTED)

        direction = self.direction_var.get()
        if direction == "auto":
            var_x = float(np.var(sig_x)) if n else 0.0
            var_y = float(np.var(sig_y)) if n else 0.0
            if var_x > var_y * 1.5:
                direction = "horizontal"
                dir_text = "偵測方向: 水平"
            elif var_y > var_x * 1.5:
                direction = "vertical"
                dir_text = "偵測方向: 垂直"
            else:
                direction = "both"
                dir_text = "偵測方向: 兩者"
            self.dir_detect_label.config(text=dir_text)
        else:
            self.dir_detect_label.config(text="")

        F = self.FONT_FAMILY
        self.ax_disp.clear()
        self._style_axis(self.ax_disp)
        self.ax_disp.set_title("位移 (像素)", fontsize=11, color=self.TEXT, fontfamily=F, pad=8, x=0.50)
        self._set_x_axis_label(self.ax_disp, "時間 (秒)")
        self.ax_disp.set_ylabel("位移", fontsize=9, color=self.MUTED, fontfamily=F)

        if direction in ("vertical", "both"):
            self.ax_disp.plot(t, sig_y, color=self.ACCENT,
                              label="垂直", linewidth=1.0)
        if direction in ("horizontal", "both"):
            self.ax_disp.plot(t, sig_x, color="#ef4444",
                              label="水平", linewidth=1.0)
        if direction == "both":
            self.ax_disp.legend(fontsize=8)

        if direction == "horizontal":
            signal = sig_x
        elif direction == "vertical":
            signal = sig_y
        else:
            signal = sig_x if np.var(sig_x) > np.var(sig_y) else sig_y

        self._do_fft_plot(signal, self.fps)

    # ── 麥克風圖表 ──────────────────────────────────────

    def update_mic_plots(self):
        # snapshot under lock — audio callback may extend mid-read
        with self._data_lock:
            data = np.array(self.audio_buffer, dtype=float)
        if data.size == 0:
            return

        display_len = min(4096, len(data))
        display_data = data[-display_len:]
        t = np.arange(display_len) / self.sample_rate

        F = self.FONT_FAMILY
        self.ax_disp.clear()
        self._style_axis(self.ax_disp)
        self.ax_disp.set_title("音訊波形", fontsize=11, color=self.TEXT, fontfamily=F, pad=8, x=0.50)
        self._set_x_axis_label(self.ax_disp, "時間 (秒)")
        self.ax_disp.set_ylabel("振幅", fontsize=9, color=self.MUTED, fontfamily=F)
        self.ax_disp.plot(t, display_data, color=self.ACCENT, linewidth=0.7)

        self.dir_detect_label.config(text="")
        self._do_fft_plot(data, self.sample_rate)

        count = len(self.audio_buffer)
        self.status_label.config(
            text=f"● 收音中... 緩衝區 {count} 筆取樣", fg=self.SUCCESS)

    # ── 波形形狀分類 ────────────────────────────────────

    def _classify_waveform(self, xf, yf, peak_freq):
        """
        用諧波比例分辨: 正弦 (圓滑) / 三角波 / 方波
        理論值: 正弦 h3/h1 ≈ 0 , 三角 ≈ 0.111 (=1/9) , 方波 ≈ 0.333 (=1/3)
        回傳 (顯示文字, 顯示顏色)
        """
        if peak_freq <= 0 or len(yf) == 0 or float(np.max(yf)) <= 1e-6:
            return "--", self.TEXT

        nyquist = float(xf[-1])
        if 3.0 * peak_freq > nyquist:
            return "(頻率過高無法判斷)", self.MUTED

        def amp_near(target):
            idx = int(np.argmin(np.abs(xf - target)))
            lo = max(0, idx - 1)
            hi = min(len(yf), idx + 2)
            return float(np.max(yf[lo:hi]))

        h1 = amp_near(peak_freq)
        if h1 <= 1e-9:
            return "--", self.TEXT

        h3 = amp_near(3.0 * peak_freq) / h1
        h5 = amp_near(5.0 * peak_freq) / h1 if 5.0 * peak_freq <= nyquist else None

        if h3 < 0.07 and (h5 is None or h5 < 0.05):
            return "○ 正弦 (圓)", "#0ea5e9"
        if h3 > 0.22:
            return "□ 方波 (方)", self.PURPLE
        if 0.07 <= h3 <= 0.20:
            return "△ 三角波", "#ea580c"
        return "? 其他 / 混合", self.MUTED

    # ═══════════════════════════════════════════════════════════════════
    #  頻率分析 (功能五)  —  Band-pass / Top-3 Peak / SNR
    #
    #  帶通只在 [lo, hi] 內選峰與算 SNR (濾掉低頻漂移 + 高頻雜訊);
    #  Top-3 取帶內前三大局部極大; SNR = 峰值 / 帶內雜訊中位數 (dB),
    #  用相對門檻 (峰值 ≥ 5× 中位數) 判定有效峰值, 不受光線/振幅影響。
    #
    #  本區塊集中可獨立搬移的方法 (_get_band / _find_top_peaks)。主要邏輯
    #  內嵌於 _do_fft_plot, 已於原處以 [頻率分析] 標記; 分析結果 (主頻率 /
    #  Top-3 / SNR / 波形 / 相位 / 位移 RMS) 存入 __init__「最近一次結果」的
    #  self.last_* 供「正常震動資料 CSV」記錄。UI 見 build_ui「頻率分析」frame。
    # ═══════════════════════════════════════════════════════════════════

    def _get_band(self, xf):
        """讀取帶通設定 → (f_low, f_high); 未啟用或無效回傳 None (= 全頻段)。"""
        if not hasattr(self, "bp_enable_var") or not self.bp_enable_var.get():
            return None
        nyq = float(xf[-1]) if len(xf) else 0.0
        try:
            lo = float(self.bp_low_var.get())
        except (ValueError, tk.TclError):
            lo = 0.0
        hs = self.bp_high_var.get().strip()
        try:
            hi = float(hs) if hs else nyq
        except (ValueError, tk.TclError):
            hi = nyq
        lo = max(0.0, lo)
        hi = min(nyq, hi)
        if hi <= lo:
            return None
        return (lo, hi)

    def _find_top_peaks(self, xf, yf, n=3, min_sep_bins=3):
        """找頻譜前 n 個局部極大 (依振幅排序, 彼此至少隔 min_sep_bins bin)。
        回傳 [(freq, amp), ...]。"""
        m = len(yf)
        if m == 0:
            return []
        if m < 3:
            i = int(np.argmax(yf))
            return [(float(xf[i]), float(yf[i]))]
        # 局部極大候選
        cand = [i for i in range(1, m - 1)
                if yf[i] >= yf[i - 1] and yf[i] > yf[i + 1]]
        if not cand:
            cand = [int(np.argmax(yf))]
        cand.sort(key=lambda i: yf[i], reverse=True)
        chosen = []
        for i in cand:
            if all(abs(i - j) >= min_sep_bins for j in chosen):
                chosen.append(i)
            if len(chosen) >= n:
                break
        return [(float(xf[i]), float(yf[i])) for i in chosen]

    # ═══════════════════════════════ 頻率分析區塊結束 ═══════════════════

    # ── 共用 FFT 繪圖 ───────────────────────────────────

    def _do_fft_plot(self, signal, sample_rate):
        n = len(signal)
        signal = signal - np.mean(signal)
        self.last_disp_rms = float(np.std(signal))

        window = np.hanning(n)
        signal_windowed = signal * window

        yf_complex = rfft(signal_windowed)
        yf = np.abs(yf_complex)
        yf_phase_rad = np.angle(yf_complex)
        xf = rfftfreq(n, 1.0 / sample_rate)

        if len(xf) > 1:
            xf = xf[1:]
            yf = yf[1:]
            yf_phase_rad = yf_phase_rad[1:]

        F = self.FONT_FAMILY

        # ── [頻率分析] 帶通: 只在 [lo, hi] 內找峰 / 算 SNR (譜線仍全畫, 頻帶加底色) ──
        band = self._get_band(xf)
        if band is not None and len(xf):
            lo, hi = band
            band_mask = (xf >= lo) & (xf <= hi)
        else:
            band_mask = np.ones(len(xf), dtype=bool)
        yf_sel = np.where(band_mask, yf, 0.0)  # 帶外歸零, 供選峰用

        # ── 振幅譜 ──
        self.ax_freq.clear()
        self._style_axis(self.ax_freq)
        self.ax_freq.set_title("頻譜 (振幅)", fontsize=11, color=self.TEXT, fontfamily=F, pad=8, x=0.50)
        self._set_x_axis_label(self.ax_freq, "頻率 (Hz)")
        self.ax_freq.set_ylabel("振幅", fontsize=9, color=self.MUTED, fontfamily=F)
        self.ax_freq.fill_between(xf, yf, color=self.ACCENT, alpha=0.15)
        self.ax_freq.plot(xf, yf, color=self.ACCENT, linewidth=1.0)
        if band is not None:
            self.ax_freq.axvspan(band[0], band[1], color=self.ACCENT, alpha=0.06)
            for bx in band:
                self.ax_freq.axvline(bx, color=self.ACCENT, linestyle=":",
                                     linewidth=0.8, alpha=0.5)

        # ── 相位譜 ──
        self.ax_phase.clear()
        self._style_axis(self.ax_phase)
        self.ax_phase.set_title("相位譜", fontsize=11, color=self.TEXT, fontfamily=F, pad=8, x=0.50)
        self._set_x_axis_label(self.ax_phase, "頻率 (Hz)")
        self.ax_phase.set_ylabel("相位 (°)", fontsize=9, color=self.MUTED, fontfamily=F)
        self.ax_phase.set_ylim(-190, 190)
        self.ax_phase.axhline(0, color="#9ca3af", linewidth=0.5, alpha=0.6)

        phase_deg = np.degrees(yf_phase_rad)
        # 只畫振幅夠大的頻率點 (雜訊區域相位沒意義)
        if len(yf) > 0 and float(np.max(yf)) > 0:
            mask = yf > 0.1 * float(np.max(yf))
            if np.any(mask):
                self.ax_phase.scatter(xf[mask], phase_deg[mask],
                                      color=self.PURPLE, s=10, alpha=0.7)

        # ── [頻率分析] SNR: 帶內峰值 / 帶內雜訊中位數 (相對門檻, 峰值 ≥ 5× 中位數才算有效) ──
        in_band = yf[band_mask]
        if in_band.size > 0:
            yf_med = float(np.median(in_band))
            yf_peak = float(np.max(yf_sel))
            snr_ratio = (yf_peak / yf_med) if yf_med > 1e-12 else 0.0
            snr_db = 20.0 * np.log10(snr_ratio) if snr_ratio > 0 else 0.0
            has_peak = yf_med > 0 and yf_peak >= 5.0 * yf_med
        else:
            snr_db = 0.0
            has_peak = False

        # ── [頻率分析] Top-3 峰值 (帶內, 依振幅排序) ──
        top_peaks = self._find_top_peaks(xf, yf_sel, n=3) if has_peak else []

        if has_peak and top_peaks:
            peak_freq, peak_amp = top_peaks[0]
            peak_idx = int(np.argmin(np.abs(xf - peak_freq)))
            peak_phase = float(phase_deg[peak_idx])

            # 主峰 (紅色實線)
            self.ax_freq.axvline(peak_freq, color=self.ERROR, linestyle="--", linewidth=1)
            self.ax_freq.annotate(f"{peak_freq:.2f} Hz",
                                  (peak_freq, peak_amp),
                                  fontsize=10, color=self.ERROR, fontweight="bold",
                                  textcoords="offset points", xytext=(10, 5))
            # 第 2 / 3 峰 (橘色點 + 標籤)
            for rank, (pf, pa) in enumerate(top_peaks[1:], start=2):
                self.ax_freq.scatter([pf], [pa], color="#ea580c", s=28, zorder=5)
                self.ax_freq.annotate(f"#{rank} {pf:.2f}",
                                      (pf, pa), fontsize=8, color="#ea580c",
                                      textcoords="offset points", xytext=(6, 4))

            self.ax_phase.axvline(peak_freq, color=self.ERROR, linestyle="--", linewidth=1)
            self.ax_phase.scatter([peak_freq], [peak_phase],
                                  color=self.ERROR, s=35, zorder=5)
            self.ax_phase.annotate(f"{peak_phase:+.1f}°",
                                   (peak_freq, peak_phase),
                                   fontsize=10, color=self.ERROR, fontweight="bold",
                                   textcoords="offset points", xytext=(10, 5))

            shape, color = self._classify_waveform(xf, yf, float(peak_freq))
            self.freq_label.config(text=f"{peak_freq:.2f} Hz")
            self.freq_sub.config(text=f"SNR {snr_db:.1f} dB", fg=self.SUCCESS)
            self.shape_label.config(text=shape, fg=color)
            self.phase_label.config(text=f"{peak_phase:+.1f}°", fg=self.PURPLE)
            peaks_txt = "  ｜  ".join(f"{pf:.2f}" for pf, _ in top_peaks)
            if hasattr(self, "peaks_label"):
                self.peaks_label.config(text=f"Top-3: {peaks_txt} Hz", fg=self.TEXT)

            # [頻率分析] 存最近結果供「正常震動資料 CSV」記錄
            self.last_peak_freq = float(peak_freq)
            self._update_session_frequency_range(peak_freq)
            self.last_peak_amp = float(peak_amp)
            self.last_snr_db = float(snr_db)
            self.last_top_peaks = [(float(pf), float(pa)) for pf, pa in top_peaks]
            self.last_waveform = shape
            self.last_phase_deg = float(peak_phase)
        else:
            self.freq_label.config(text="-- Hz")
            self.freq_sub.config(text="SNR -- dB", fg=self.MUTED)
            self.shape_label.config(text="--", fg=self.TEXT)
            self.phase_label.config(text="--", fg=self.TEXT)
            if hasattr(self, "peaks_label"):
                self.peaks_label.config(text="Top-3: --", fg=self.MUTED)
            self.last_peak_freq = 0.0
            self.last_peak_amp = 0.0
            self.last_snr_db = 0.0
            self.last_top_peaks = []
            self.last_waveform = "--"
            self.last_phase_deg = 0.0

        try:
            self.fig.tight_layout(pad=2.5)
        except Exception:
            pass
        self.canvas_plot.draw()
        self.canvas_plot.flush_events()

    # ═══════════════════════════════════════════════════════════════════
    #  正常震動資料 CSV (功能六)  —  基準庫 (Baseline Library)
    #
    #  把多次『正常狀態』的頻譜結果各存一列摘要 → normal_vibration.csv,
    #  再依樣本名稱分組算主頻率 mean ± 3σ → normal_baseline.csv 當正常範圍。
    #  之後偵測值落在範圍外即可視為異常震動。
    #
    #  資料來源是「頻率分析」存下的 self.last_* (見該區塊)。本區塊兩個方法
    #  皆由 build_ui「正常震動資料」frame 的按鈕觸發 (主緒), 不需 lock 保護
    #  last_* (皆在主緒 _do_fft_plot 內更新)。欄位定義見 __init__ CSV_HEADER。
    # ═══════════════════════════════════════════════════════════════════

    def _append_normal_sample_row(self, row):
        """Append a row while upgrading legacy CSV headers without losing data."""
        if os.path.exists(self.csv_path):
            try:
                with open(self.csv_path, newline="", encoding="utf-8-sig") as file:
                    reader = csv.DictReader(file)
                    old_header = reader.fieldnames or []
                    old_rows = list(reader)
                if old_header != self.CSV_HEADER:
                    temp_path = self.csv_path + ".tmp"
                    with open(temp_path, "w", newline="", encoding="utf-8-sig") as file:
                        writer = csv.DictWriter(file, fieldnames=self.CSV_HEADER)
                        writer.writeheader()
                        for old_row in old_rows:
                            writer.writerow({key: old_row.get(key, "")
                                             for key in self.CSV_HEADER})
                    os.replace(temp_path, self.csv_path)
            except OSError:
                raise

        new_file = not os.path.exists(self.csv_path)
        with open(self.csv_path, "a", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            if new_file:
                writer.writerow(self.CSV_HEADER)
            writer.writerow(row)

    def record_normal_sample(self):
        """把目前的頻譜結果 (主頻率 / Top-3 / SNR / 波形 …) 存成一列正常樣本。"""
        if self.mode not in ("camera", "file", "mic"):
            messagebox.showinfo("提示", "請先開始偵測 (攝影機 / 影片 / 麥克風) 並取得穩定主頻率")
            return
        if self.last_peak_freq <= 0 or not self.last_top_peaks:
            messagebox.showinfo("提示",
                                "目前沒有有效主頻率 (SNR 不足)\n請等頻譜出現明顯峰值後再記錄")
            return
        self._update_session_frequency_range(self.last_peak_freq)

        label = (self.sample_label_var.get() or "").strip() or "normal"

        # 背景晃動 std (僅相機/影片有背景參考時)
        with self._data_lock:
            bxs = np.array(self.bg_hist_x, dtype=float)
            bys = np.array(self.bg_hist_y, dtype=float)
        bg_std = (float(np.sqrt(np.std(bxs) ** 2 + np.std(bys) ** 2))
                  if bxs.size > 5 else 0.0)

        tp = self.last_top_peaks
        p2f, p2a = tp[1] if len(tp) > 1 else (0.0, 0.0)
        p3f, p3a = tp[2] if len(tp) > 2 else (0.0, 0.0)
        roi_str = str(self.roi) if self.roi else ""

        row = [
            datetime.now().isoformat(timespec="seconds"),
            label, self.mode, f"{self.fps:.2f}",
            roi_str, self.direction_var.get(),
            f"{self.last_peak_freq:.4f}", f"{self.last_peak_amp:.4f}",
            f"{self.last_snr_db:.2f}",
            f"{p2f:.4f}", f"{p2a:.4f}", f"{p3f:.4f}", f"{p3a:.4f}",
            self.last_waveform, f"{self.last_phase_deg:.2f}",
            f"{self.last_disp_rms:.4f}", f"{bg_std:.4f}",
            (f"{self.session_min_freq:.4f}"
             if self.session_min_freq is not None else ""),
            (f"{self.session_max_freq:.4f}"
             if self.session_max_freq is not None else ""),
        ]

        try:
            self._append_normal_sample_row(row)
        except OSError as e:
            messagebox.showerror("錯誤", f"寫入 CSV 失敗: {e}")
            return

        self.status_label.config(
            text=(f"● 已記錄正常樣本「{label}」 {self.last_peak_freq:.2f} Hz "
                  f"(最低 {self.session_min_freq:.2f} / 最高 {self.session_max_freq:.2f} Hz, "
                  f"SNR {self.last_snr_db:.1f} dB) → {os.path.basename(self.csv_path)}"),
            fg=self.SUCCESS)

    def compute_baseline(self):
        """讀 CSV, 依樣本名稱分組算主頻率 mean / std → 正常範圍 (mean ± 3σ)。"""
        if not os.path.exists(self.csv_path):
            messagebox.showinfo("提示", "還沒有任何記錄\n請先按「● 記錄正常樣本」")
            return
        try:
            with open(self.csv_path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except OSError as e:
            messagebox.showerror("錯誤", f"讀取 CSV 失敗: {e}")
            return
        if not rows:
            messagebox.showinfo("提示", "CSV 沒有資料列")
            return

        groups = {}
        for r in rows:
            try:
                f0 = float(r["peak_freq_hz"])
            except (ValueError, KeyError, TypeError):
                continue
            g = groups.setdefault(r.get("label") or "normal",
                                  {"freq": [], "snr": [], "rms": []})
            g["freq"].append(f0)
            for key, col in (("snr", "snr_db"), ("rms", "disp_rms_px")):
                try:
                    g[key].append(float(r[col]))
                except (ValueError, KeyError, TypeError):
                    pass

        if not groups:
            messagebox.showinfo("提示", "沒有可用的主頻率資料")
            return

        out_rows, lines = [], []
        for label, g in sorted(groups.items()):
            fr = np.array(g["freq"], dtype=float)
            n = len(fr)
            mean = float(fr.mean())
            std = float(fr.std(ddof=1)) if n > 1 else 0.0
            lo, hi = mean - 3 * std, mean + 3 * std
            snr_mean = float(np.mean(g["snr"])) if g["snr"] else 0.0
            rms_mean = float(np.mean(g["rms"])) if g["rms"] else 0.0
            out_rows.append([label, n, f"{mean:.4f}", f"{std:.4f}",
                             f"{lo:.4f}", f"{hi:.4f}", f"{snr_mean:.2f}",
                             f"{rms_mean:.4f}"])
            note = "  (樣本數 <2, σ 無意義, 請多記幾筆)" if n < 2 else ""
            lines.append(
                f"【{label}】 n={n}{note}\n"
                f"   主頻率  {mean:.3f} ± {std:.3f} Hz\n"
                f"   正常範圍 (±3σ):  {lo:.3f} ~ {hi:.3f} Hz\n"
                f"   平均 SNR {snr_mean:.1f} dB   平均位移 RMS {rms_mean:.3f} px")

        try:
            with open(self.baseline_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["label", "count", "freq_mean_hz", "freq_std_hz",
                            "freq_lo_3sigma", "freq_hi_3sigma",
                            "snr_mean_db", "disp_rms_mean_px"])
                w.writerows(out_rows)
        except OSError as e:
            messagebox.showerror("錯誤", f"寫入基準檔失敗: {e}")
            return

        messagebox.showinfo(
            "正常震動基準 (mean ± 3σ)",
            "\n\n".join(lines) + f"\n\n已存基準檔:\n{self.baseline_path}")
        self.status_label.config(
            text=f"● 已統計 {len(groups)} 組基準 → {os.path.basename(self.baseline_path)}",
            fg=self.SUCCESS)

    # ═══════════════════════════════ 正常震動資料 CSV 區塊結束 ═══════════

    # ── 結束處理 ─────────────────────────────────────────

    def show_final_result(self, title="偵測已停止"):
        # 做最後一次圖表更新
        if self.mode == "mic" and len(self.audio_buffer) >= 4096:
            self.update_mic_plots()
        elif self.mode in ("camera", "file") and len(self.displacement_y) >= 8:
            self.update_camera_plots()

        # 取得最終頻率文字
        final_freq = self.freq_label.cget("text")

        self.status_label.config(text=title, fg="orange")

        # 在影像區域顯示最終頻率 (canvas 還沒 layout 時延後重畫)
        self._draw_final_result_text(title, final_freq)

    def on_video_finished(self):
        self.show_final_result(title="影片播放結束")

    # ── 基準訊號產生器 ────────────────────────────────────

    def toggle_tone(self):
        if self.tone_playing:
            self.stop_tone()
        else:
            self.start_tone()

    def start_tone(self):
        try:
            freq = float(self.tone_freq_var.get())
            amp = float(self.tone_amp_var.get())
        except ValueError:
            messagebox.showerror("錯誤", "頻率或振幅格式錯誤")
            return
        if not (0.1 <= freq <= 20000):
            messagebox.showerror("錯誤", "頻率請介於 0.1 ~ 20000 Hz")
            return
        if not (0.0 <= amp <= 1.0):
            messagebox.showerror("錯誤", "振幅請介於 0 ~ 1")
            return

        self.tone_freq = freq
        self.tone_amp = amp
        self.tone_phase = 0.0

        try:
            import sounddevice as sd
            self.tone_stream = sd.OutputStream(
                samplerate=self.tone_sr,
                channels=1,
                dtype="float32",
                blocksize=1024,
                callback=self.tone_callback
            )
            self.tone_stream.start()
        except Exception as e:
            messagebox.showerror("錯誤", f"無法開啟喇叭輸出: {e}")
            self.tone_stream = None
            return

        self.tone_playing = True
        self.tone_button.config(text="■ 停止基準音")
        self.tone_status.config(
            text=f"播放中: 指令 {freq:.2f} Hz, 振幅 {amp:.2f} — 對準主頻率驗證",
            foreground="blue"
        )

    def tone_callback(self, outdata, frames, time_info, status):
        # phase 以 radians 累積並 wrap 2π, 任意頻率(含非整除取樣率者)都不會有秒邊界 click
        omega = 2.0 * np.pi * self.tone_freq / self.tone_sr
        n = np.arange(frames)
        outdata[:, 0] = (self.tone_amp * np.sin(omega * n + self.tone_phase)).astype(np.float32)
        self.tone_phase = (self.tone_phase + omega * frames) % (2.0 * np.pi)

    def stop_tone(self):
        if self.tone_stream is not None:
            try:
                self.tone_stream.stop()
                self.tone_stream.close()
            except Exception:
                pass
            self.tone_stream = None
        self.tone_playing = False
        if hasattr(self, "tone_button"):
            self.tone_button.config(text="▶ 播放基準音")
        if hasattr(self, "tone_status"):
            self.tone_status.config(text="基準音已停止", foreground="gray")

    # ── 關閉 ─────────────────────────────────────────────

    def on_close(self):
        self.stop_tone()
        self.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = VibrationAnalyzer()
    app.run()
