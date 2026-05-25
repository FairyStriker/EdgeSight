import type { Channel, Lang, StatusMeta } from "../api/types";
import { t } from "../i18n";
import { ObjectTable } from "./ObjectTable";

interface Props {
  lang: Lang;
  channel: Channel | null;
  meta: StatusMeta | null;
}

export function StatusPanel({ lang, channel, meta }: Props) {
  return (
    <div className="data-panel">
      <div className="panel-header">
        {t(lang, "panel_realtime")}
        {channel && (
          <span className="panel-sub">
            — {t(lang, "selected_channel")}: [{channel.id}] {channel.name}
          </span>
        )}
      </div>

      {!channel || !meta ? (
        <div className="form-help" style={{ padding: 20, textAlign: "center" }}>
          {t(lang, "msg_waiting")}
        </div>
      ) : (
        <>
          <div className="status-grid">
            <div className="info-box">
              <div className="info-label">{t(lang, "label_time")}</div>
              <div className="info-value">{meta.timestamp}</div>
            </div>
            <div className="info-box">
              <div className="info-label">FPS</div>
              <div className="info-value">{meta.fps.toFixed(1)}</div>
            </div>
            <div className="count-box">
              <div className="info-label">{t(lang, "label_obj_count")}</div>
              <div className="info-value" style={{ fontSize: "2rem" }}>
                {meta.count}
              </div>
            </div>
          </div>

          <ObjectTable lang={lang} objects={meta.objects} />
        </>
      )}
    </div>
  );
}
