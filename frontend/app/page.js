"use client";

import { useEffect, useMemo, useState } from "react";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:5000").replace(/\/$/, "");
const STREAM_URL = process.env.NEXT_PUBLIC_STREAM_URL || `${API_BASE}/api/cameras/stream`;
const MODES = [
  { key: "worker", label: "Worker" },
  { key: "mediapipe", label: "MediaPipe" },
  { key: "ppe", label: "PPE" },
];
const SOURCE_PRESETS = [
  { label: "\u6e2c\u8a66\u5f71\u7247", value: "test_videos/001.mp4" },
  { label: "Webcam", value: "0" },
  { label: "\u624b\u6a5f\u4e32\u6d41", value: "http://phone-ip:8080" },
];

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

async function fetchJson(path, options) {
  const response = await fetch(apiUrl(path), {
    cache: "no-store",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed: ${response.status}`);
  return data;
}

function streamUrl(key) {
  return `${STREAM_URL}${STREAM_URL.includes("?") ? "&" : "?"}t=${key}`;
}

function riskLabel(level) {
  if (level === "danger") return "\u5371\u96aa";
  if (level === "warning") return "\u8b66\u793a";
  return "\u6b63\u5e38";
}

function riskTone(level) {
  if (level === "danger") return "danger";
  if (level === "warning") return "warn";
  return "safe";
}

function ppeLabel(value) {
  if (value === true) return "\u5df2\u7a7f\u6234";
  if (value === false) return "\u672a\u7a7f\u6234";
  return "\u78ba\u8a8d\u4e2d";
}

function behaviorLabel(behavior) {
  if (!behavior) return "\u7121\u8cc7\u6599";
  if (behavior.fall) return "\u7591\u4f3c\u8dcc\u5012";
  if (behavior.wave) return "\u7591\u4f3c\u6c42\u6551";
  if (behavior.unstable) return "\u6b65\u614b\u4e0d\u7a69";
  if (behavior.running) return "\u5954\u8dd1";
  if (behavior.tracking_lost) return "\u8ffd\u8e64\u4e2d\u65b7";
  if (behavior.fallback) return "\u59ff\u614b\u5099\u63f4\u5224\u65b7";
  return "\u6b63\u5e38";
}

function formatConfidence(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "\u7121\u8cc7\u6599";
  return `${Math.round((number <= 1 ? number * 100 : number) * 10) / 10}%`;
}

function formatRelativeTime(unixSeconds) {
  const number = Number(unixSeconds);
  if (!Number.isFinite(number)) return "\u5c1a\u672a\u66f4\u65b0";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - number));
  if (seconds < 3) return "\u525b\u525b";
  if (seconds < 60) return `${seconds} \u79d2\u524d`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} \u5206\u9418\u524d`;
  return `${Math.floor(minutes / 60)} \u5c0f\u6642\u524d`;
}

function formatPoint(point) {
  if (!point) return "\u7121";
  const pixel = point.pixel;
  const normalized = point.normalized;
  if (!pixel && !normalized) return "\u7121";
  const pixelText = pixel ? `(${pixel.x}, ${pixel.y})` : "\u7121\u50cf\u7d20";
  const normalizedText = normalized ? `${normalized.x}, ${normalized.y}` : "\u7121\u6bd4\u4f8b";
  return `${pixelText} / ${normalizedText}`;
}

function StatusPill({ tone = "neutral", children }) {
  return <span className={`status-pill status-${tone}`}>{children}</span>;
}

function SourcePanel({ camera, draftSource, setDraftSource, busy, onSubmit }) {
  return (
    <form className="source-panel" onSubmit={onSubmit}>
      <div className="source-header">
        <div>
          <p className="eyebrow">Camera Source</p>
          <h2>{"\u651d\u5f71\u6a5f\u4f86\u6e90"}</h2>
        </div>
        <StatusPill tone={camera?.is_open ? "safe" : "warn"}>
          {camera?.is_open ? "\u9023\u7dda\u4e2d" : "\u7b49\u5f85\u756b\u9762"}
        </StatusPill>
      </div>

      <label className="source-field">
        <span>{"\u5f71\u50cf\u4f86\u6e90"}</span>
        <input
          value={draftSource}
          onChange={(event) => setDraftSource(event.target.value)}
          placeholder="test_videos/001.mp4, 0, http://phone-ip:8080, rtsp://..."
        />
      </label>

      <div className="preset-row" aria-label="source presets">
        {SOURCE_PRESETS.map((preset) => (
          <button key={preset.label} type="button" className="ghost-button" onClick={() => setDraftSource(preset.value)}>
            {preset.label}
          </button>
        ))}
      </div>

      <button className="primary-button" type="submit" disabled={busy || !draftSource.trim()}>
        {busy ? "\u5957\u7528\u4e2d..." : "\u5957\u7528\u4f86\u6e90\u4e26\u91cd\u7f6e\u8ffd\u8e64"}
      </button>

      <dl className="camera-details">
        <div>
          <dt>{"\u76ee\u524d\u4f86\u6e90"}</dt>
          <dd>{camera?.source || "\u5c1a\u672a\u53d6\u5f97"}</dd>
        </div>
        <div>
          <dt>{"\u5be6\u969b\u4e32\u6d41"}</dt>
          <dd>{camera?.active_source || "\u5c1a\u672a\u958b\u555f"}</dd>
        </div>
        <div>
          <dt>{"\u89e3\u6790\u5ea6"}</dt>
          <dd>{camera?.width && camera?.height ? `${camera.width} x ${camera.height}` : "\u7121\u8cc7\u6599"}</dd>
        </div>
        <div>
          <dt>{"\u4e32\u6d41 FPS"}</dt>
          <dd>{camera?.target_fps || "\u7121\u8cc7\u6599"}</dd>
        </div>
      </dl>
    </form>
  );
}

function MonitorDisplay({ camera, workers, workerStatus, mode, onModeChange, streamKey, streamError, onStreamError }) {
  const src = useMemo(() => streamUrl(`${streamKey}-${mode}`), [streamKey, mode]);
  const summary = workerStatus?.last_frame || {};

  return (
    <section className="monitor-section" aria-label="live monitor">
      <div className="section-title-row">
        <div>
          <p className="eyebrow">Live Monitor</p>
          <h2>{"\u5373\u6642\u756b\u9762"}</h2>
        </div>
        <div className="mode-switch" aria-label="overlay mode">
          {MODES.map((item) => (
            <button key={item.key} className={mode === item.key ? "mode-active" : ""} type="button" onClick={() => onModeChange(item.key)}>
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="video-shell">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="live-stream" src={src} alt="live stream" decoding="async" onError={onStreamError} />
        <div className="camera-chip">{camera?.camera_id || "CAM-01"} · {camera?.overlay_mode || mode}</div>
        <div className="stream-status">
          <StatusPill tone={camera?.is_open ? "safe" : "warn"}>
            {camera?.is_open ? "\u4e32\u6d41\u9023\u7dda" : "\u5c1a\u672a\u958b\u555f"}
          </StatusPill>
          <span>{camera?.active_source || camera?.source || "\u7b49\u5f85\u651d\u5f71\u6a5f\u4f86\u6e90"}</span>
        </div>
        {streamError && <div className="stream-error">{"\u4e32\u6d41\u8f09\u5165\u5931\u6557\uff0c\u8acb\u6aa2\u67e5 Flask \u5f8c\u7aef\u8207\u651d\u5f71\u6a5f\u4f86\u6e90\u3002"}</div>}
      </div>

      <div className="monitor-metrics" aria-label="monitor summary">
        <div><span>{workers.length}</span><small>{"\u76ee\u524d\u4eba\u54e1"}</small></div>
        <div><span>{summary.actual_analysis_fps ?? 0}</span><small>{"\u5206\u6790 FPS"}</small></div>
        <div><span>{summary.tracks ?? 0}</span><small>{"\u8ffd\u8e64\u6578"}</small></div>
        <div><span>{summary.alerts ?? 0}</span><small>{"\u7570\u5e38\u72c0\u614b"}</small></div>
      </div>
    </section>
  );
}

function WorkerCard({ worker }) {
  const ppe = worker.ppe || {};
  const coordinate = worker.coordinate || {};
  const alerts = Array.isArray(worker.alerts) ? worker.alerts : [];

  return (
    <article className="worker-card">
      <div className="worker-card-header">
        <div>
          <p className="worker-id">{worker.worker_id || "worker-unknown"}</p>
          <h3>Track {worker.track_id ?? "\u7121"}</h3>
        </div>
        <StatusPill tone={riskTone(worker.risk_level)}>{riskLabel(worker.risk_level)}</StatusPill>
      </div>

      <dl className="worker-details">
        <div><dt>{"\u6240\u5728\u5340\u57df"}</dt><dd>{worker.zone || "\u7121\u8cc7\u6599"}</dd></div>
        <div><dt>{"\u884c\u70ba\u72c0\u614b"}</dt><dd>{behaviorLabel(worker.behavior)}</dd></div>
        <div><dt>{"\u7e6a\u88fd\u7bc4\u570d\u5ea7\u6a19"}</dt><dd>{formatPoint(coordinate.range)}</dd></div>
        <div><dt>{"\u6574\u756b\u9762\u5ea7\u6a19"}</dt><dd>{formatPoint(coordinate.frame)}</dd></div>
        <div><dt>{"\u5075\u6e2c\u4fe1\u5fc3"}</dt><dd>{formatConfidence(worker.confidence)}</dd></div>
        <div><dt>{"\u6700\u5f8c\u66f4\u65b0"}</dt><dd>{formatRelativeTime(worker.last_seen_unix)}</dd></div>
      </dl>

      <div className="ppe-row" aria-label="ppe status">
        <span className={ppe.helmet === false ? "ppe-missing" : ppe.helmet === true ? "ppe-ok" : "ppe-pending"}>
          {"\u5b89\u5168\u5e3d"}: {ppeLabel(ppe.helmet)}
        </span>
        <span className={ppe.vest === false ? "ppe-missing" : ppe.vest === true ? "ppe-ok" : "ppe-pending"}>
          {"\u5b89\u5168\u80cc\u5fc3"}: {ppeLabel(ppe.vest)}
        </span>
      </div>

      {alerts.length > 0 && (
        <div className="alert-list">
          {alerts.map((alert, index) => <span key={`${alert}-${index}`}>{alert}</span>)}
        </div>
      )}
    </article>
  );
}

function WorkerGrid({ workers, loading }) {
  return (
    <section className="workers-section" aria-label="workers">
      <div className="section-title-row">
        <div>
          <p className="eyebrow">Detected Workers</p>
          <h2>{"\u4eba\u54e1\u8cc7\u8a0a"}</h2>
        </div>
        <p className="data-note">{loading ? "\u6b63\u5728\u66f4\u65b0\u8cc7\u6599..." : `\u5171 ${workers.length} \u4f4d\u756b\u9762\u4eba\u54e1`}</p>
      </div>

      {workers.length === 0 ? (
        <div className="empty-state">
          <strong>{"\u76ee\u524d\u672a\u5075\u6e2c\u5230\u4eba\u54e1"}</strong>
          <span>{"\u8acb\u78ba\u8a8d\u651d\u5f71\u6a5f\u756b\u9762\u3001\u6a21\u578b\u8f09\u5165\u72c0\u614b\uff0c\u6216\u7b49\u5f85\u4e0b\u4e00\u6b21\u8fa8\u8b58\u66f4\u65b0\u3002"}</span>
        </div>
      ) : (
        <div className="worker-grid">
          {workers.map((worker) => <WorkerCard key={`${worker.worker_id}-${worker.track_id}`} worker={worker} />)}
        </div>
      )}
    </section>
  );
}

export default function Home() {
  const [camera, setCamera] = useState(null);
  const [workerStatus, setWorkerStatus] = useState(null);
  const [workers, setWorkers] = useState([]);
  const [draftSource, setDraftSource] = useState("");
  const [mode, setMode] = useState("worker");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [streamKey, setStreamKey] = useState(() => Date.now());
  const [streamError, setStreamError] = useState(false);

  async function applyStatus(cameraData, workerData) {
    setCamera(cameraData);
    setWorkerStatus(workerData);
    setWorkers(workerData.workers || []);
    setMode(cameraData.overlay_mode || "worker");
    setDraftSource((current) => current || cameraData.source || "");
  }

  async function refreshStatus() {
    const [cameraData, workerData] = await Promise.all([fetchJson("/api/cameras"), fetchJson("/api/workers")]);
    await applyStatus(cameraData, workerData);
    setLoading(false);
  }

  useEffect(() => {
    let active = true;
    async function tick() {
      try {
        const [cameraData, workerData] = await Promise.all([fetchJson("/api/cameras"), fetchJson("/api/workers")]);
        if (!active) return;
        await applyStatus(cameraData, workerData);
        setMessage("");
      } catch (error) {
        if (active) setMessage(error.message || "\u7121\u6cd5\u53d6\u5f97\u5f8c\u7aef\u72c0\u614b");
      } finally {
        if (active) setLoading(false);
      }
    }
    tick();
    const timer = setInterval(tick, 1500);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  async function handleSourceSubmit(event) {
    event.preventDefault();
    const source = draftSource.trim();
    if (!source) return;
    setBusy(true);
    setMessage("");
    try {
      const updated = await fetchJson("/api/cameras", { method: "POST", body: JSON.stringify({ source }) });
      setCamera(updated);
      setWorkers([]);
      setWorkerStatus(null);
      setStreamError(false);
      setStreamKey(Date.now());
      setMessage("\u651d\u5f71\u6a5f\u4f86\u6e90\u5df2\u5957\u7528\uff0c\u8ffd\u8e64\u8cc7\u6599\u5df2\u91cd\u7f6e\u3002");
      await refreshStatus();
    } catch (error) {
      setMessage(error.message || "\u651d\u5f71\u6a5f\u4f86\u6e90\u5957\u7528\u5931\u6557");
    } finally {
      setBusy(false);
    }
  }

  async function handleModeChange(nextMode) {
    if (nextMode === mode) return;
    const previousMode = mode;
    setMode(nextMode);
    setMessage("");
    try {
      await fetchJson("/api/cameras/overlay-mode", { method: "POST", body: JSON.stringify({ mode: nextMode }) });
      setStreamError(false);
      setStreamKey(Date.now());
      await refreshStatus();
    } catch (error) {
      setMode(previousMode);
      setMessage(error.message || "\u986f\u793a\u6a21\u5f0f\u5207\u63db\u5931\u6557");
    }
  }

  return (
    <main className="monitor-page">
      <header className="topbar">
        <div>
          <p className="eyebrow">YOLO + MediaPipe Safety Monitor</p>
          <h1>{"\u5de5\u5730\u5b89\u5168\u76e3\u63a7\u7cfb\u7d71"}</h1>
        </div>
        <div className="topbar-status">
          <StatusPill tone={message ? "warn" : "safe"}>{message ? "\u9700\u8981\u78ba\u8a8d" : "\u7cfb\u7d71\u904b\u4f5c\u4e2d"}</StatusPill>
          <span>{message || "Next.js frontend connected to Flask API"}</span>
        </div>
      </header>

      <div className="dashboard-layout">
        <MonitorDisplay
          camera={camera}
          workers={workers}
          workerStatus={workerStatus}
          mode={mode}
          onModeChange={handleModeChange}
          streamKey={streamKey}
          streamError={streamError}
          onStreamError={() => setStreamError(true)}
        />
        <SourcePanel
          camera={camera}
          draftSource={draftSource}
          setDraftSource={setDraftSource}
          busy={busy}
          onSubmit={handleSourceSubmit}
        />
      </div>

      <WorkerGrid workers={workers} loading={loading} />
    </main>
  );
}
