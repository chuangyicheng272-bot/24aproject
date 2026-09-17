from __future__ import annotations

from flask import Flask, Response, jsonify

try:
    from flask_cors import CORS
except ImportError:  # pragma: no cover - CORS is optional during early setup
    CORS = None

try:
    from .routes.alerts import alerts_bp
    from .routes.cameras import cameras_bp
    from .routes.workers import workers_bp
    from .runtime import SafetyRuntime
except ImportError:  # Allows `python app.py` from the backend directory.
    from routes.alerts import alerts_bp
    from routes.cameras import cameras_bp
    from routes.workers import workers_bp
    from runtime import SafetyRuntime


def create_app() -> Flask:
    app = Flask(__name__)
    if CORS is not None:
        CORS(app)

    app.config["SAFETY_RUNTIME"] = SafetyRuntime()
    app.register_blueprint(cameras_bp, url_prefix="/api/cameras")
    app.register_blueprint(workers_bp, url_prefix="/api/workers")
    app.register_blueprint(alerts_bp, url_prefix="/api/alerts")

    @app.get("/")
    def index():
        return """
<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>工地安全監控系統</title>
    <style>
      :root {
        --bg: #f4f6f5;
        --panel: #ffffff;
        --ink: #17211c;
        --muted: #64736d;
        --line: #dce4df;
        --steel: #2d4a5d;
        --safe: #138a5b;
        --warn: #b56b00;
        --danger: #bd2b2b;
        --accent: #f3b61f;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background: var(--bg);
        color: var(--ink);
        font-family: Arial, "Microsoft JhengHei", "PingFang TC", sans-serif;
      }
      main {
        width: min(1440px, 100%);
        margin: 0 auto;
        padding: 24px;
      }
      header {
        display: flex;
        align-items: end;
        justify-content: space-between;
        gap: 18px;
        padding-bottom: 18px;
      }
      h1, h2, h3, p { margin-top: 0; }
      h1 {
        margin-bottom: 6px;
        font-size: clamp(24px, 3vw, 36px);
      }
      h2 {
        margin-bottom: 12px;
        font-size: 22px;
      }
      p {
        color: var(--muted);
      }
      section {
        border-top: 1px solid var(--line);
        padding: 18px 0;
      }
      .summary {
        display: grid;
        grid-template-columns: repeat(2, minmax(100px, 1fr));
        border: 1px solid var(--line);
        background: var(--panel);
      }
      .summary div {
        padding: 12px 16px;
      }
      .summary div + div {
        border-left: 1px solid var(--line);
      }
      .summary strong {
        display: block;
        font-size: 26px;
      }
      .summary span {
        color: var(--muted);
        font-size: 13px;
      }
      .video-wrap {
        position: relative;
        background: #111816;
        border: 1px solid #263631;
      }
      .video {
        display: block;
        width: 100%;
        min-height: 360px;
        max-height: 640px;
        aspect-ratio: 16 / 9;
        background: #111816;
        object-fit: contain;
      }
      .camera-chip {
        position: absolute;
        top: 14px;
        right: 14px;
        display: inline-flex;
        align-items: center;
        min-height: 30px;
        padding: 6px 10px;
        background: rgba(17, 24, 22, 0.84);
        border: 1px solid rgba(255, 255, 255, 0.22);
        color: #ffffff;
        font-size: 13px;
        font-weight: 800;
      }
      .range-overlay {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        cursor: crosshair;
        pointer-events: none;
      }
      .range-overlay.drawing {
        pointer-events: auto;
      }
      .range-tools {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        margin-top: 10px;
      }
      .range-tools button {
        min-height: 34px;
        padding: 7px 12px;
        border: 1px solid var(--line);
        background: #ffffff;
        color: var(--steel);
        font-weight: 800;
        cursor: pointer;
      }
      .range-tools button.primary {
        background: var(--steel);
        color: #ffffff;
        border-color: var(--steel);
      }
      .range-tools button:disabled {
        cursor: not-allowed;
        opacity: 0.45;
      }
      .mode-tools {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        margin-top: 10px;
      }
      .mode-tools span {
        color: var(--muted);
        font-size: 13px;
        font-weight: 800;
      }
      .mode-tools button {
        min-height: 34px;
        padding: 7px 12px;
        border: 1px solid var(--line);
        background: #ffffff;
        color: var(--steel);
        font-weight: 800;
        cursor: pointer;
      }
      .mode-tools button.active {
        background: var(--steel);
        color: #ffffff;
        border-color: var(--steel);
      }
      .range-status {
        margin: 0;
        color: var(--muted);
        font-size: 13px;
      }
      .section-head {
        display: flex;
        align-items: end;
        justify-content: space-between;
        gap: 16px;
      }
      .worker-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        gap: 14px;
      }
      .worker-card {
        min-height: 230px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--panel);
        padding: 16px;
      }
      .worker-card-head {
        display: flex;
        align-items: start;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 14px;
      }
      .worker-id {
        margin-bottom: 4px;
        color: var(--muted);
        font-size: 13px;
        font-weight: 700;
      }
      .badge {
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 5px 10px;
        border-radius: 999px;
        font-size: 13px;
        font-weight: 800;
        white-space: nowrap;
      }
      .normal { background: #dff5eb; color: var(--safe); }
      .warning { background: #fff0cf; color: var(--warn); }
      .danger { background: #ffe4e1; color: var(--danger); }
      dl {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        margin: 0 0 14px;
      }
      dt {
        margin-bottom: 4px;
        color: var(--muted);
        font-size: 12px;
      }
      dd {
        margin: 0;
        font-size: 15px;
        font-weight: 700;
        overflow-wrap: anywhere;
      }
      .ppe {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .ppe span {
        display: inline-flex;
        min-height: 28px;
        align-items: center;
        padding: 5px 9px;
        border: 1px solid transparent;
        font-size: 13px;
        font-weight: 800;
      }
      .ok {
        border-color: #bfe4d3;
        background: #eef8f3;
        color: var(--safe);
      }
      .missing {
        border-color: #f0c775;
        background: #fff5df;
        color: var(--warn);
      }
      .unknown {
        border-color: var(--line);
        background: #f7f9f8;
        color: var(--muted);
      }
      .ppe-detail {
        margin-top: 8px;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.45;
        overflow-wrap: anywhere;
      }
      .empty {
        border: 1px dashed var(--line);
        background: #ffffff;
        padding: 22px;
        color: var(--muted);
      }
      .links {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 14px;
      }
      a {
        display: inline-flex;
        padding: 9px 12px;
        border: 1px solid var(--line);
        color: var(--steel);
        background: #fff;
        text-decoration: none;
        font-weight: 700;
      }
      @media (max-width: 720px) {
        main { padding: 18px; }
        header, .section-head { align-items: stretch; flex-direction: column; }
        .summary { width: 100%; }
        .video { min-height: 220px; aspect-ratio: 16 / 9; }
        .camera-chip { top: 10px; right: 10px; }
        dl { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    <main>
      <header>
        <div>
          <h1>工地安全監控系統</h1>
          <p>整合手機串流、YOLO 裝備辨識、MediaPipe 姿態分析、人員追蹤與 UWB 範圍座標。</p>
        </div>
        <div class="summary" aria-label="監控摘要">
          <div>
            <strong id="worker-count">0</strong>
            <span>偵測人員</span>
          </div>
          <div>
            <strong id="alert-count">0</strong>
            <span>警示事件</span>
          </div>
        </div>
      </header>

      <section>
        <div class="section-head">
          <h2>即時畫面</h2>
          <p id="updated-at">等待資料更新</p>
        </div>
        <div class="video-wrap">
          <img class="video" src="/api/cameras/stream" alt="即時監控串流">
          <span id="camera-chip" class="camera-chip">CAM-01</span>
          <svg id="range-overlay" class="range-overlay" viewBox="0 0 1 1" preserveAspectRatio="none" aria-label="UWB 判定範圍繪製層">
            <polygon id="range-polygon" points="" fill="rgba(243, 182, 31, 0.15)" stroke="#f3b61f" stroke-width="0.004"></polygon>
            <polyline id="range-polyline" points="" fill="none" stroke="#f3b61f" stroke-width="0.004"></polyline>
            <g id="range-points"></g>
          </svg>
        </div>
        <div class="range-tools">
          <button id="draw-range" class="primary" type="button">繪製範圍</button>
          <button id="save-range" type="button" disabled>儲存範圍</button>
          <button id="clear-range" type="button">清除重畫</button>
          <p id="range-status" class="range-status">可在畫面上繪製 UWB 判定範圍；人員不在範圍內時座標顯示「無」。</p>
        </div>
        <div class="mode-tools" aria-label="主畫面顯示模式">
          <span>主畫面顯示</span>
          <button class="mode-button active" data-mode="worker" type="button">Worker</button>
          <button class="mode-button" data-mode="mediapipe" type="button">MediaPipe</button>
          <button class="mode-button" data-mode="ppe" type="button">PPE</button>
        </div>
      </section>

      <section>
        <div class="section-head">
          <h2>人員資訊</h2>
          <p>每偵測到一位人員，下方會建立一個資訊方格。</p>
        </div>
        <div id="worker-grid" class="worker-grid">
          <div class="empty">尚未取得人員資料，請確認手機串流與後端辨識流程正在運作。</div>
        </div>
        <div class="links">
          <a href="/api/health">健康檢查</a>
          <a href="/api/cameras">攝影機狀態</a>
          <a href="/api/workers">人員狀態 JSON</a>
          <a href="/api/alerts">警報事件 JSON</a>
        </div>
      </section>
    </main>
    <script>
      const grid = document.getElementById("worker-grid");
      const workerCount = document.getElementById("worker-count");
      const alertCount = document.getElementById("alert-count");
      const updatedAt = document.getElementById("updated-at");
      const cameraChip = document.getElementById("camera-chip");
      const rangeOverlay = document.getElementById("range-overlay");
      const rangePolygon = document.getElementById("range-polygon");
      const rangePolyline = document.getElementById("range-polyline");
      const rangePoints = document.getElementById("range-points");
      const drawRangeButton = document.getElementById("draw-range");
      const saveRangeButton = document.getElementById("save-range");
      const clearRangeButton = document.getElementById("clear-range");
      const rangeStatus = document.getElementById("range-status");
      const modeButtons = Array.from(document.querySelectorAll(".mode-button"));
      let rangeDrawing = false;
      let rangeDraft = [];
      let overlayMode = "worker";

      function escapeHtml(value) {
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#039;");
      }

      function ppeClass(value) {
        if (value === true) return "ok";
        if (value === false) return "missing";
        return "unknown";
      }

      function ppeText(label, value) {
        if (value === true) return `${label} 已確認`;
        if (value === false) return `${label} 未確認`;
        return `${label} 無資料`;
      }

      function ppeDetailText(worker) {
        const detections = worker.ppe_detections || [];
        if (!detections.length) return "PPE 原始偵測：無";
        const labels = detections.map((item) => {
          const kind = item.kind || item.label || "ppe";
          const confidence = Math.round((item.confidence || 0) * 100);
          return `${kind} ${confidence}%`;
        });
        return `PPE 原始偵測：${labels.join("、")}`;
      }

      function riskLabel(level) {
        if (level === "danger") return "危險";
        if (level === "warning") return "警告";
        return "正常";
      }

      function coordinateText(worker) {
        const range = worker.coordinate?.range;
        if (!range) return "無";

        const pixel = range.pixel || {};
        const normalized = range.normalized || {};
        if (pixel.x === undefined || pixel.y === undefined) return "無";

        const x = Math.round(pixel.x);
        const y = Math.round(pixel.y);
        const nx = normalized.x === undefined ? "-" : Number(normalized.x).toFixed(3);
        const ny = normalized.y === undefined ? "-" : Number(normalized.y).toFixed(3);
        return `(${x}, ${y}) / ${nx}, ${ny}`;
      }

      async function refreshCameraStatus() {
        try {
          const response = await fetch("/api/cameras", { cache: "no-store" });
          const data = await response.json();
          cameraChip.textContent = `${data.source_kind || "camera"}：${data.active_source || data.source || "CAM-01"}`;
          setOverlayModeState(data.overlay_mode || overlayMode);
        } catch (error) {
          cameraChip.textContent = "CAM-01";
        }
      }

      function setOverlayModeState(mode) {
        overlayMode = mode || "worker";
        modeButtons.forEach((button) => {
          button.classList.toggle("active", button.dataset.mode === overlayMode);
        });
      }

      async function setOverlayMode(mode) {
        setOverlayModeState(mode);
        try {
          const response = await fetch("/api/cameras/overlay-mode", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode })
          });
          const data = await response.json();
          if (!response.ok) {
            throw new Error(data.error || "顯示模式切換失敗");
          }
          setOverlayModeState(data.mode);
        } catch (error) {
          rangeStatus.textContent = error.message || "顯示模式切換失敗";
        }
      }

      function renderWorkers(workers) {
        workerCount.textContent = workers.length;
        alertCount.textContent = workers.filter((worker) => worker.risk_level !== "normal").length;
        updatedAt.textContent = `最後更新：${new Date().toLocaleTimeString("zh-TW")}`;

        if (!workers.length) {
          grid.innerHTML = '<div class="empty">目前沒有偵測到人員。</div>';
          return;
        }

        grid.innerHTML = workers.map((worker) => {
          const ppe = worker.ppe || {};
          const behavior = worker.behavior || {};
          const alerts = worker.alerts && worker.alerts.length ? worker.alerts.join("、") : "無";
          return `
            <article class="worker-card">
              <div class="worker-card-head">
                <div>
                  <p class="worker-id">${escapeHtml(worker.worker_id || "未命名")}</p>
                  <h3>Track ${escapeHtml(worker.track_id)}</h3>
                </div>
                <span class="badge ${escapeHtml(worker.risk_level || "normal")}">${riskLabel(worker.risk_level)}</span>
              </div>
              <dl>
                <div>
                  <dt>所在區域</dt>
                  <dd>${escapeHtml(worker.zone || "未設定")}</dd>
                </div>
                <div>
                  <dt>行為狀態</dt>
                  <dd>${escapeHtml(behavior.status || "正常")}</dd>
                </div>
                <div>
                  <dt>辨識信心</dt>
                  <dd>${Math.round((worker.confidence || 0) * 100)}%</dd>
                </div>
                <div>
                  <dt>警報</dt>
                  <dd>${escapeHtml(alerts)}</dd>
                </div>
                <div>
                  <dt>繪製範圍座標</dt>
                  <dd>${escapeHtml(coordinateText(worker))}</dd>
                </div>
              </dl>
              <div class="ppe">
                <span class="${ppeClass(ppe.helmet)}">${escapeHtml(ppeText("安全帽", ppe.helmet))}</span>
                <span class="${ppeClass(ppe.vest)}">${escapeHtml(ppeText("安全背心", ppe.vest))}</span>
              </div>
              <div class="ppe-detail">${escapeHtml(ppeDetailText(worker))}</div>
            </article>
          `;
        }).join("");
      }

      function pointList(points) {
        return points.map((point) => `${point.x},${point.y}`).join(" ");
      }

      function renderRange(points, closed = true) {
        rangePolygon.setAttribute("points", closed && points.length >= 3 ? pointList(points) : "");
        rangePolyline.setAttribute("points", pointList(points));
        rangePoints.innerHTML = points.map((point, index) => `
          <circle cx="${point.x}" cy="${point.y}" r="0.01" fill="#f3b61f" stroke="#111816" stroke-width="0.003"></circle>
          <text x="${point.x + 0.012}" y="${Math.max(0.035, point.y - 0.012)}" fill="#ffffff" stroke="#111816" stroke-width="0.002" font-size="0.035">${index + 1}</text>
        `).join("");
      }

      async function loadPairingRange() {
        try {
          const response = await fetch("/api/cameras/pairing-range", { cache: "no-store" });
          const data = await response.json();
          rangeDraft = data.points || [];
          renderRange(rangeDraft, true);
        } catch (error) {
          rangeStatus.textContent = "讀取 UWB 判定範圍失敗。";
        }
      }

      function startDrawingRange() {
        rangeDrawing = true;
        rangeDraft = [];
        rangeOverlay.classList.add("drawing");
        saveRangeButton.disabled = true;
        rangeStatus.textContent = "請在畫面上依序點選範圍頂點，至少需要 3 個點。";
        renderRange(rangeDraft, false);
      }

      function clearDrawingRange() {
        rangeDraft = [];
        saveRangeButton.disabled = true;
        rangeStatus.textContent = rangeDrawing
          ? "已清除目前草稿，請重新點選範圍。"
          : "已清除畫面上的範圍草稿。";
        renderRange(rangeDraft, false);
      }

      async function saveDrawingRange() {
        if (rangeDraft.length < 3) {
          rangeStatus.textContent = "至少需要 3 個點才能儲存範圍。";
          return;
        }

        const response = await fetch("/api/cameras/pairing-range", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ points: rangeDraft })
        });
        const data = await response.json();
        if (!response.ok) {
          rangeStatus.textContent = data.error || "儲存範圍失敗。";
          return;
        }

        rangeDraft = data.points || rangeDraft;
        rangeDrawing = false;
        rangeOverlay.classList.remove("drawing");
        saveRangeButton.disabled = true;
        rangeStatus.textContent = `已儲存 ${rangeDraft.length} 個點的 UWB 判定範圍。`;
        renderRange(rangeDraft, true);
      }

      rangeOverlay.addEventListener("click", (event) => {
        if (!rangeDrawing) return;
        const rect = rangeOverlay.getBoundingClientRect();
        const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
        const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
        rangeDraft.push({ x: Number(x.toFixed(4)), y: Number(y.toFixed(4)) });
        saveRangeButton.disabled = rangeDraft.length < 3;
        rangeStatus.textContent = `目前已選取 ${rangeDraft.length} 個點。`;
        renderRange(rangeDraft, rangeDraft.length >= 3);
      });

      drawRangeButton.addEventListener("click", startDrawingRange);
      clearRangeButton.addEventListener("click", clearDrawingRange);
      saveRangeButton.addEventListener("click", saveDrawingRange);
      modeButtons.forEach((button) => {
        button.addEventListener("click", () => setOverlayMode(button.dataset.mode));
      });

      async function refreshWorkers() {
        try {
          const response = await fetch("/api/workers", { cache: "no-store" });
          const data = await response.json();
          renderWorkers(data.workers || []);
        } catch (error) {
          grid.innerHTML = '<div class="empty">讀取人員資料失敗，請確認 Flask 後端仍在執行。</div>';
        }
      }

      refreshCameraStatus();
      refreshWorkers();
      loadPairingRange();
      setInterval(refreshCameraStatus, 3000);
      setInterval(refreshWorkers, 1500);
    </script>
  </body>
</html>
        """

    @app.get("/favicon.ico")
    def favicon():
        return Response(status=204)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
