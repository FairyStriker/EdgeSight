import type { Lang, StatusMeta } from "../api/types";
import { t } from "../i18n";
import { ObjectTable } from "./ObjectTable";

interface Props {
  lang: Lang;
  status: StatusMeta;
}

export function StatusPanel({ lang, status }: Props) {
  return (
    <div className="data-panel">
      <div className="panel-header">{t(lang, "panel_realtime")}</div>

      <div className="status-grid">
        <div className="info-box">
          <div className="info-label">{t(lang, "label_time")}</div>
          <div className="info-value">{status.timestamp}</div>
        </div>
        <div className="info-box">
          <div className="info-label">FPS</div>
          <div className="info-value">{status.fps.toFixed(1)}</div>
        </div>
        <div className="count-box">
          <div className="info-label">{t(lang, "label_obj_count")}</div>
          <div className="info-value" style={{ fontSize: "2rem" }}>
            {status.count}
          </div>
        </div>
      </div>

      <ObjectTable lang={lang} objects={status.objects} />
    </div>
  );
}
