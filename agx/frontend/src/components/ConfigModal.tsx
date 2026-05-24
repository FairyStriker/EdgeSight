import { useEffect, useState } from "react";
import { api, tokenStore } from "../api/client";
import type {
  DemoVideoItem,
  InputSource,
  Lang,
  SystemConfigDTO,
} from "../api/types";
import { t } from "../i18n";

interface Props {
  lang: Lang;
  config: SystemConfigDTO;
  onClose: () => void;
  onSaved: (newLang: Lang) => void;
}

export function ConfigModal({ lang, config, onClose, onSaved }: Props) {
  const [language, setLanguage] = useState<Lang>(config.language);
  const [rtsp, setRtsp] = useState(config.rtsp_url);
  const [conf, setConf] = useState(config.conf_threshold);
  const [iou, setIou] = useState(config.iou_threshold);
  const [port, setPort] = useState(config.server_port);
  const [token, setToken] = useState(tokenStore.get() ?? "");
  const [saving, setSaving] = useState(false);

  const [inputSource, setInputSource] = useState<InputSource>(
    config.input_source ?? "rtsp"
  );
  const [videoFilename, setVideoFilename] = useState<string>(
    config.video_filename ?? ""
  );
  const [videos, setVideos] = useState<DemoVideoItem[]>([]);
  const [uploadingVideo, setUploadingVideo] = useState(false);

  useEffect(() => {
    setLanguage(config.language);
    setRtsp(config.rtsp_url);
    setConf(config.conf_threshold);
    setIou(config.iou_threshold);
    setPort(config.server_port);
    setInputSource(config.input_source ?? "rtsp");
    setVideoFilename(config.video_filename ?? "");
  }, [config]);

  const refreshVideos = async () => {
    try {
      const r = await api.listVideos();
      setVideos(r.videos);
    } catch (e) {
      console.warn("video list 조회 실패:", (e as Error).message);
    }
  };

  useEffect(() => {
    refreshVideos();
  }, []);

  const onUploadVideo = async (file: File) => {
    setUploadingVideo(true);
    try {
      const r = await api.uploadVideo(file);
      alert(
        `${t(language, "alert_video_upload_start")}\nJob ID: ${r.job_id}\n${t(language, "video_upload_wait")}`
      );
      // 변환 완료까지 polling (60초 timeout)
      for (let i = 0; i < 60; i++) {
        await new Promise((res) => setTimeout(res, 2000));
        try {
          const j = await api.getJob(r.job_id);
          if (j.status === "completed") {
            await refreshVideos();
            alert(t(language, "alert_video_upload_done"));
            return;
          }
          if (j.status === "failed") {
            alert(`${t(language, "alert_video_upload_fail")}: ${j.error ?? ""}`);
            return;
          }
        } catch {
          /* ignore polling error */
        }
      }
      alert(t(language, "alert_video_upload_timeout"));
      await refreshVideos();
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setUploadingVideo(false);
    }
  };

  const onDeleteVideo = async (v: DemoVideoItem) => {
    const isActive = videoFilename === v.filename;
    const msg = isActive
      ? `${t(language, "confirm_delete_video")}\n${t(language, "warn_delete_active_video")}`
      : t(language, "confirm_delete_video");
    if (!confirm(msg)) return;
    try {
      await api.deleteVideo(v.id);
      if (isActive) setVideoFilename("");
      await refreshVideos();
    } catch (err) {
      alert((err as Error).message);
    }
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (inputSource === "video" && !videoFilename) {
      alert(t(language, "msg_select_video"));
      return;
    }
    setSaving(true);
    try {
      if (token) tokenStore.set(token);
      else tokenStore.clear();

      const fd = new FormData();
      fd.append("rtsp", rtsp);
      fd.append("conf", String(conf));
      fd.append("iou", String(iou));
      fd.append("port", String(port));
      fd.append("language", language);
      fd.append("input_source", inputSource);
      fd.append("video_filename", inputSource === "video" ? videoFilename : "");
      await api.updateConfig(fd);
      alert(t(language, "alert_save"));
      onSaved(language);
      onClose();
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setSaving(false);
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
          <span>{t(lang, "modal_config_title")}</span>
          <button className="close-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <form onSubmit={onSubmit}>
            <span className="form-label">{t(lang, "label_lang")}</span>
            <select
              className="form-select"
              value={language}
              onChange={(e) => setLanguage(e.target.value as Lang)}
            >
              <option value="ko">한국어 (Korean)</option>
              <option value="en">English</option>
            </select>

            <span className="form-label">{t(lang, "label_input_source")}</span>
            <div style={{ display: "flex", gap: 12, marginBottom: 10 }}>
              {(["rtsp", "usb", "video"] as InputSource[]).map((src) => (
                <label key={src} style={{ display: "flex", gap: 4 }}>
                  <input
                    type="radio"
                    name="input_source"
                    value={src}
                    checked={inputSource === src}
                    onChange={() => setInputSource(src)}
                  />
                  {t(lang, `input_${src}`)}
                </label>
              ))}
            </div>

            {inputSource === "rtsp" && (
              <>
                <span className="form-label">{t(lang, "label_rtsp")}</span>
                <input
                  className="form-input"
                  value={rtsp}
                  onChange={(e) => setRtsp(e.target.value)}
                />
              </>
            )}

            {inputSource === "video" && (
              <>
                <span className="form-label">
                  {t(lang, "label_video_upload")}
                </span>
                <div className="form-help" style={{ marginBottom: 6 }}>
                  {t(lang, "video_upload_help")}
                </div>
                <input
                  type="file"
                  accept="video/*"
                  className="form-input"
                  disabled={uploadingVideo}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                      onUploadVideo(f);
                      e.target.value = "";
                    }
                  }}
                />

                <span className="form-label">
                  {t(lang, "label_video_select")}
                </span>
                {videos.length === 0 ? (
                  <div className="form-help" style={{ marginBottom: 10 }}>
                    {t(lang, "no_videos")}
                  </div>
                ) : (
                  <div style={{ marginBottom: 10 }}>
                    {videos.map((v) => (
                      <div
                        key={v.id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          padding: "4px 0",
                        }}
                      >
                        <input
                          type="radio"
                          name="video_select"
                          checked={videoFilename === v.filename}
                          onChange={() => setVideoFilename(v.filename)}
                        />
                        <span style={{ flex: 1 }}>
                          {v.filename}
                          <span
                            style={{
                              color: "#888",
                              marginLeft: 6,
                              fontSize: 12,
                            }}
                          >
                            ({v.uploaded_at})
                          </span>
                        </span>
                        <button
                          type="button"
                          className="btn-action btn-danger btn-inline"
                          onClick={() => onDeleteVideo(v)}
                        >
                          {t(lang, "btn_delete")}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            <span className="form-label">{t(lang, "label_conf")}</span>
            <input
              type="number"
              step="0.01"
              className="form-input"
              value={conf}
              onChange={(e) => setConf(parseFloat(e.target.value))}
            />

            <span className="form-label">{t(lang, "label_iou")}</span>
            <input
              type="number"
              step="0.01"
              className="form-input"
              value={iou}
              onChange={(e) => setIou(parseFloat(e.target.value))}
            />

            <span className="form-label">{t(lang, "label_port")}</span>
            <input
              type="number"
              className="form-input"
              value={port}
              onChange={(e) => setPort(parseInt(e.target.value, 10))}
            />

            <span className="form-label">{t(lang, "label_token")}</span>
            <input
              type="password"
              className="form-input"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Bearer ..."
            />
            <div className="form-help">{t(lang, "token_help")}</div>

            <button
              type="submit"
              className="btn-action btn-primary"
              disabled={saving}
            >
              {t(lang, "btn_save")}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
