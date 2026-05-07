import type { Lang } from "../api/types";
import { t } from "../i18n";

interface Props {
  lang: Lang;
  onOpenConfig: () => void;
  onOpenModels: () => void;
}

export function Header({ lang, onOpenConfig, onOpenModels }: Props) {
  return (
    <header className="app-header">
      <h1>
        <span>{t(lang, "title")}</span>
        <span className="live-badge">LIVE</span>
      </h1>
      <div style={{ display: "flex", gap: 10 }}>
        <button className="btn-header" onClick={onOpenConfig}>
          {t(lang, "btn_config")}
        </button>
        <button className="btn-header" onClick={onOpenModels}>
          {t(lang, "btn_model")}
        </button>
      </div>
    </header>
  );
}
