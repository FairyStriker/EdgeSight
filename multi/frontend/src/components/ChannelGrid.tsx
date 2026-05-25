import type { Channel, Lang, MultiChannelStatus } from "../api/types";
import { getChannelMeta } from "../hooks/useStatus";
import { ChannelTile } from "./ChannelTile";
import { t } from "../i18n";

interface Props {
  channels: Channel[];
  status: MultiChannelStatus;
  lang: Lang;
  selectedId: number | null;
  onSelect: (id: number) => void;
}

/** 채널 수에 따라 자동으로 grid-template-columns 결정. */
function gridCols(n: number): number {
  if (n <= 1) return 1;
  if (n <= 2) return 2;
  if (n <= 4) return 2;
  if (n <= 6) return 3;
  return 3; // 7~9
}

export function ChannelGrid({ channels, status, lang, selectedId, onSelect }: Props) {
  if (channels.length === 0) {
    return <div className="grid-empty">{t(lang, "grid_no_active")}</div>;
  }

  const cols = gridCols(channels.length);

  return (
    <div
      className="channel-grid"
      style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
    >
      {channels.map((ch) => (
        <ChannelTile
          key={ch.id}
          channel={ch}
          meta={getChannelMeta(status, ch.id)}
          lang={lang}
          selected={selectedId === ch.id}
          onSelect={() => onSelect(ch.id)}
        />
      ))}
    </div>
  );
}
