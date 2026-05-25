import { useEffect, useState } from "react";
import { api, tokenStore } from "../api/client";
import type { Lang, SystemConfigDTO } from "../api/types";
import { t } from "../i18n";

interface Props {
  lang: Lang;
  config: SystemConfigDTO;
  onClose: () => void;
  onSaved: (newLang: Lang) => void;
}

/** 다채널 버전 — 입력 소스 관련 필드는 채널 모달로 이전됨.
 *  ConfigModal 은 전역 설정(언어/conf/iou/port/토큰)만 다룬다. */
export function ConfigModal({ lang, config, onClose, onSaved }: Props) {
  const [language, setLanguage] = useState<Lang>(config.language);
  const [conf, setConf] = useState(config.conf_threshold);
  const [iou, setIou] = useState(config.iou_threshold);
  const [port, setPort] = useState(config.server_port);
  const [token, setToken] = useState(tokenStore.get() ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLanguage(config.language);
    setConf(config.conf_threshold);
    setIou(config.iou_threshold);
    setPort(config.server_port);
  }, [config]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (token) tokenStore.set(token);
      else tokenStore.clear();

      const fd = new FormData();
      fd.append("conf", String(conf));
      fd.append("iou", String(iou));
      fd.append("port", String(port));
      fd.append("language", language);
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
