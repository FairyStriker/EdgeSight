import { useState } from "react";
import { api } from "../api/client";
import { useJobs } from "../hooks/useJobs";
import { useModels } from "../hooks/useModels";
import type { Job, JobStatus, Lang } from "../api/types";
import { t } from "../i18n";

type Tab = "engine" | "pt";

interface Props {
  lang: Lang;
  onClose: () => void;
}

export function ModelModal({ lang, onClose }: Props) {
  const { active_model_id, models, reload: reloadModels } = useModels(true);
  const { jobs } = useJobs(true);
  const [tab, setTab] = useState<Tab>("engine");

  const onSelect = async (id: number) => {
    if (!confirm(t(lang, "confirm_change_model"))) return;
    try {
      await api.selectModel(id);
      await reloadModels();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const onDelete = async (id: number) => {
    if (!confirm(t(lang, "confirm_delete_model"))) return;
    try {
      await api.deleteModel(id);
      await reloadModels();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-content">
        <div className="modal-header">
          <span>{t(lang, "modal_model_title")}</span>
          <button className="close-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <h4 style={{ margin: "0 0 10px" }}>{t(lang, "header_model_list")}</h4>
          <ul className="model-list-container">
            {models.map((m) => {
              const isActive = m.id === active_model_id;
              return (
                <li
                  key={m.id}
                  className={`model-item ${isActive ? "active" : ""}`}
                >
                  <div>
                    <strong>{m.filename}</strong>
                    {isActive && (
                      <span
                        style={{
                          color: "green",
                          fontSize: "0.8rem",
                          fontWeight: "bold",
                          marginLeft: 5,
                        }}
                      >
                        ({t(lang, "active_badge")})
                      </span>
                    )}
                  </div>
                  <div>
                    {!isActive && (
                      <>
                        <button
                          className="btn-mini"
                          onClick={() => onSelect(m.id)}
                        >
                          {t(lang, "btn_select")}
                        </button>
                        <button
                          className="btn-mini del"
                          onClick={() => onDelete(m.id)}
                        >
                          {t(lang, "btn_delete")}
                        </button>
                      </>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          <hr style={{ margin: "20px 0", border: 0, borderTop: "1px solid #eee" }} />

          <div className="upload-tabs">
            <button
              className={`tab-btn ${tab === "engine" ? "active" : ""}`}
              onClick={() => setTab("engine")}
            >
              {t(lang, "tab_engine")}
            </button>
            <button
              className={`tab-btn ${tab === "pt" ? "active" : ""}`}
              onClick={() => setTab("pt")}
            >
              {t(lang, "tab_pt")}
            </button>
          </div>

          {tab === "engine" ? (
            <EngineUploadForm lang={lang} onUploaded={reloadModels} />
          ) : (
            <PtUploadForm lang={lang} />
          )}

          <hr style={{ margin: "20px 0", border: 0, borderTop: "1px solid #eee" }} />

          <h4 style={{ margin: "0 0 10px" }}>{t(lang, "header_jobs")}</h4>
          <JobsList lang={lang} jobs={jobs} />
        </div>
      </div>
    </div>
  );
}

function EngineUploadForm({
  lang,
  onUploaded,
}: {
  lang: Lang;
  onUploaded: () => Promise<void> | void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [classNames, setClassNames] = useState("");
  const [busy, setBusy] = useState(false);

  const onUpload = async () => {
    if (!file || !classNames.trim()) {
      alert("Check input");
      return;
    }
    if (!confirm(t(lang, "confirm_upload"))) return;
    setBusy(true);
    try {
      await api.uploadModel(file, classNames.trim());
      alert(t(lang, "alert_upload"));
      setFile(null);
      setClassNames("");
      await onUploaded();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h4 style={{ margin: "0 0 10px" }}>{t(lang, "header_model_upload")}</h4>
      <input
        type="file"
        accept=".engine"
        className="form-input"
        style={{ marginBottom: 10 }}
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <input
        type="text"
        placeholder={t(lang, "placeholder_classes")}
        className="form-input"
        value={classNames}
        onChange={(e) => setClassNames(e.target.value)}
      />
      <button
        className="btn-action btn-success"
        onClick={onUpload}
        disabled={busy}
      >
        {t(lang, "btn_upload")}
      </button>
    </>
  );
}

function PtUploadForm({ lang }: { lang: Lang }) {
  const [file, setFile] = useState<File | null>(null);
  const [classNames, setClassNames] = useState("");
  const [imgsz, setImgsz] = useState(640);
  const [busy, setBusy] = useState(false);

  const onUpload = async () => {
    if (!file || !classNames.trim()) {
      alert("Check input");
      return;
    }
    if (!confirm(t(lang, "confirm_upload"))) return;
    setBusy(true);
    try {
      const r = await api.uploadPt(file, classNames.trim(), imgsz);
      alert(t(lang, "pt_started").replace("{id}", r.job_id));
      setFile(null);
      setClassNames("");
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="form-help" style={{ marginBottom: 10 }}>
        {t(lang, "pt_upload_help")}
      </div>
      <input
        type="file"
        accept=".pt"
        className="form-input"
        style={{ marginBottom: 10 }}
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <input
        type="text"
        placeholder={t(lang, "placeholder_classes")}
        className="form-input"
        style={{ marginBottom: 10 }}
        value={classNames}
        onChange={(e) => setClassNames(e.target.value)}
      />
      <span className="form-label">{t(lang, "pt_imgsz")}</span>
      <input
        type="number"
        className="form-input"
        value={imgsz}
        min={128}
        step={32}
        onChange={(e) => setImgsz(parseInt(e.target.value, 10) || 640)}
      />
      <button
        className="btn-action btn-success"
        onClick={onUpload}
        disabled={busy}
      >
        {t(lang, "btn_upload")}
      </button>
    </>
  );
}

function statusLabel(lang: Lang, s: JobStatus): string {
  return t(lang, `job_status_${s}`);
}

function statusColor(s: JobStatus): string {
  switch (s) {
    case "pending":
      return "#888";
    case "running":
      return "#3498db";
    case "completed":
      return "#27ae60";
    case "failed":
      return "#e74c3c";
  }
}

function JobsList({ lang, jobs }: { lang: Lang; jobs: Job[] }) {
  if (jobs.length === 0) {
    return <div className="form-help">{t(lang, "no_jobs")}</div>;
  }
  return (
    <ul className="job-list">
      {jobs.map((j) => (
        <li key={j.id} className="job-item">
          <div className="job-header">
            <strong>{j.filename}</strong>
            <span style={{ color: statusColor(j.status) }}>
              {statusLabel(lang, j.status)}
            </span>
          </div>
          <div className="job-progress-bar">
            <div
              className="job-progress-fill"
              style={{
                width: `${j.progress}%`,
                background: statusColor(j.status),
              }}
            />
          </div>
          <div className="form-help">
            {j.error ? `❌ ${j.error}` : j.message || `${j.progress}%`}
          </div>
        </li>
      ))}
    </ul>
  );
}
