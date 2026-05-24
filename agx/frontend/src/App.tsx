import { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { VideoStream } from "./components/VideoStream";
import { StatusPanel } from "./components/StatusPanel";
import { ConfigModal } from "./components/ConfigModal";
import { ModelModal } from "./components/ModelModal";
import { useStatus } from "./hooks/useStatus";
import { useConfig } from "./hooks/useConfig";
import { t } from "./i18n";
import type { Lang } from "./api/types";

export default function App() {
  const status = useStatus();
  const { config, reload: reloadConfig } = useConfig();
  const [lang, setLang] = useState<Lang>("ko");
  const [showConfig, setShowConfig] = useState(false);
  const [showModels, setShowModels] = useState(false);

  // 백엔드에서 받은 초기 설정의 언어를 반영
  useEffect(() => {
    if (config?.language) setLang(config.language);
  }, [config?.language]);

  // 언어에 따른 document.title
  useEffect(() => {
    document.title = t(lang, "document_title");
  }, [lang]);

  return (
    <>
      <Header
        lang={lang}
        onOpenConfig={() => setShowConfig(true)}
        onOpenModels={() => setShowModels(true)}
      />

      <div className="container">
        <VideoStream />
        <StatusPanel lang={lang} status={status} />
      </div>

      {showConfig && config && (
        <ConfigModal
          lang={lang}
          config={config}
          onClose={() => setShowConfig(false)}
          onSaved={async (newLang) => {
            setLang(newLang);
            await reloadConfig();
          }}
        />
      )}

      {showModels && (
        <ModelModal lang={lang} onClose={() => setShowModels(false)} />
      )}
    </>
  );
}
