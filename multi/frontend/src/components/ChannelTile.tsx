import { useEffect, useRef, useState } from "react";
import type { Channel, Lang, StatusMeta } from "../api/types";
import { USE_MOCK } from "../api/client";
import { mockFrameDataUrl } from "../api/mock";
import { t } from "../i18n";

interface Props {
  channel: Channel;
  meta: StatusMeta;
  lang: Lang;
  selected: boolean;
  onSelect: () => void;
}

/** 채널 1개 = 비디오 + 오버레이(이름/입력소스/FPS/객체수). 클릭 시 선택. */
export function ChannelTile({ channel, meta, lang, selected, onSelect }: Props) {
  const [mockSrc, setMockSrc] = useState<string>("");

  // mock 모드: setInterval 로 canvas 프레임 갱신 (실 MJPEG 대체)
  useEffect(() => {
    if (!USE_MOCK || !channel.enabled) return;
    const tick = () => setMockSrc(mockFrameDataUrl(channel));
    tick();
    const h = window.setInterval(tick, 200); // 5 fps (mock 시각화용)
    return () => clearInterval(h);
  }, [channel]);

  // 실 모드: MJPEG /video_feed/{id} — onError 시 캐시버스터 갱신
  const [realSrc, setRealSrc] = useState(
    `/video_feed/${channel.id}?t=${Date.now()}`
  );
  const retryRef = useRef<number | null>(null);
  const handleError = () => {
    if (USE_MOCK) return;
    if (retryRef.current) clearTimeout(retryRef.current);
    retryRef.current = window.setTimeout(() => {
      setRealSrc(`/video_feed/${channel.id}?t=${Date.now()}`);
    }, 1500);
  };
  useEffect(() => () => {
    if (retryRef.current) clearTimeout(retryRef.current);
  }, []);

  const srcUriShort =
    channel.input_source === "video"
      ? channel.video_filename ?? "—"
      : channel.source_uri || "—";

  return (
    <div
      className={`channel-tile ${selected ? "selected" : ""} ${
        channel.enabled ? "" : "disabled"
      }`}
      onClick={onSelect}
    >
      <div className="channel-tile-video">
        {channel.enabled ? (
          <img
            src={USE_MOCK ? mockSrc : realSrc}
            alt={channel.name}
            onError={handleError}
          />
        ) : (
          <div className="channel-tile-off">
            <div>{t(lang, "channel_disabled_overlay")}</div>
          </div>
        )}
      </div>

      <div className="channel-tile-overlay-top">
        <span className="channel-tile-name">
          [{channel.id}] {channel.name}
        </span>
        <span className={`channel-tile-src src-${channel.input_source}`}>
          {channel.input_source.toUpperCase()}
        </span>
      </div>

      <div className="channel-tile-overlay-bottom">
        <span title={srcUriShort}>
          {srcUriShort.length > 36 ? srcUriShort.slice(0, 33) + "…" : srcUriShort}
        </span>
        <span className="channel-tile-stats">
          <span>FPS {meta.fps.toFixed(1)}</span>
          <span>OBJ {meta.count}</span>
        </span>
      </div>
    </div>
  );
}
