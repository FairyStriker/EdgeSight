import { useEffect, useMemo, useState } from "react";
import { Header } from "./components/Header";
import { ChannelGrid } from "./components/ChannelGrid";
import { StatusPanel } from "./components/StatusPanel";
import { ConfigModal } from "./components/ConfigModal";
import { ModelModal } from "./components/ModelModal";
import { ChannelsModal } from "./components/ChannelsModal";
import { useStatus, getChannelMeta } from "./hooks/useStatus";
import { useConfig } from "./hooks/useConfig";
import { useChannels } from "./hooks/useChannels";
import { USE_MOCK } from "./api/client";
import { t } from "./i18n";
import type { Lang } from "./api/types";

export default function App() {
  const status = useStatus();
  const { config, reload: reloadConfig } = useConfig();
  const {
    channels,
    maxChannels,
    create,
    update,
    remove,
  } = useChannels();
  const [lang, setLang] = useState<Lang>("ko");
  const [showConfig, setShowConfig] = useState(false);
  const [showModels, setShowModels] = useState(false);
  const [showChannels, setShowChannels] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  useEffect(() => {
    if (config?.language) setLang(config.language);
  }, [config?.language]);

  useEffect(() => {
    document.title = t(lang, "document_title");
  }, [lang]);

  // 채널 목록 변경 시 selectedId 동기화 — 없거나 사라졌으면 첫 채널로
  useEffect(() => {
    if (channels.length === 0) {
      setSelectedId(null);
      return;
    }
    if (selectedId == null || !channels.some((c) => c.id === selectedId)) {
      setSelectedId(channels[0].id);
    }
  }, [channels, selectedId]);

  const selectedChannel = useMemo(
    () => channels.find((c) => c.id === selectedId) ?? null,
    [channels, selectedId]
  );

  const selectedMeta = useMemo(
    () => (selectedId != null ? getChannelMeta(status, selectedId) : null),
    [status, selectedId]
  );

  return (
    <>
      {USE_MOCK && (
        <div className="mock-banner">{t(lang, "mock_mode_badge")}</div>
      )}

      <Header
        lang={lang}
        onOpenConfig={() => setShowConfig(true)}
        onOpenModels={() => setShowModels(true)}
        onOpenChannels={() => setShowChannels(true)}
        channelCount={channels.length}
        maxChannels={maxChannels}
      />

      <div className="container">
        <ChannelGrid
          channels={channels}
          status={status}
          lang={lang}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <StatusPanel
          lang={lang}
          channel={selectedChannel}
          meta={selectedMeta}
        />
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

      {showChannels && (
        <ChannelsModal
          lang={lang}
          channels={channels}
          maxChannels={maxChannels}
          onClose={() => setShowChannels(false)}
          onCreate={create}
          onUpdate={update}
          onDelete={remove}
        />
      )}
    </>
  );
}
