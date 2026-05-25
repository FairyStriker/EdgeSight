import { useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  Channel,
  DemoVideoItem,
  InputSource,
  Lang,
} from "../api/types";
import { t } from "../i18n";

interface Props {
  lang: Lang;
  channels: Channel[];
  maxChannels: number;
  onClose: () => void;
  onCreate: (input: Omit<Channel, "id" | "position">) => Promise<void>;
  onUpdate: (id: number, patch: Partial<Omit<Channel, "id">>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}

type Editing =
  | { mode: "new" }
  | { mode: "edit"; channel: Channel }
  | null;

export function ChannelsModal({
  lang,
  channels,
  maxChannels,
  onClose,
  onCreate,
  onUpdate,
  onDelete,
}: Props) {
  const [editing, setEditing] = useState<Editing>(null);

  const atLimit = channels.length >= maxChannels;

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-content" style={{ width: 640 }}>
        <div className="modal-header">
          <span>{t(lang, "modal_channels_title")}</span>
          <button className="close-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="channel-summary">
            <div>
              <strong>{t(lang, "channel_count_label")}:</strong>{" "}
              {channels.length} / {maxChannels}
            </div>
            <div className="form-help">
              {t(lang, "channel_max_hint").replace(
                "{max}",
                String(maxChannels)
              )}
            </div>
          </div>

          {channels.length === 0 ? (
            <div className="form-help" style={{ margin: "20px 0" }}>
              {t(lang, "no_channels")}
            </div>
          ) : (
            <ul className="channel-list">
              {channels.map((c) => (
                <li key={c.id} className="channel-row">
                  <div className="channel-row-info">
                    <div className="channel-row-title">
                      <strong>
                        [{c.id}] {c.name}
                      </strong>
                      <span className={`channel-tile-src src-${c.input_source}`}>
                        {c.input_source.toUpperCase()}
                      </span>
                      {!c.enabled && (
                        <span className="badge-disabled">
                          {t(lang, "channel_disabled")}
                        </span>
                      )}
                    </div>
                    <div className="channel-row-sub">
                      {c.input_source === "video"
                        ? c.video_filename ?? "—"
                        : c.source_uri || "—"}
                    </div>
                  </div>
                  <div className="channel-row-actions">
                    <button
                      className="btn-mini"
                      onClick={() =>
                        setEditing({ mode: "edit", channel: c })
                      }
                    >
                      {t(lang, "btn_edit")}
                    </button>
                    <button
                      className="btn-mini del"
                      onClick={async () => {
                        if (channels.length <= 1) {
                          alert(t(lang, "channel_min_one"));
                          return;
                        }
                        if (!confirm(t(lang, "confirm_delete_channel"))) return;
                        try {
                          await onDelete(c.id);
                        } catch (e) {
                          alert((e as Error).message);
                        }
                      }}
                    >
                      {t(lang, "btn_delete")}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <button
            className="btn-action btn-primary"
            disabled={atLimit}
            onClick={() => setEditing({ mode: "new" })}
            style={{ marginTop: 16 }}
          >
            {atLimit
              ? t(lang, "channel_limit_reached")
              : t(lang, "btn_add_channel")}
          </button>
        </div>
      </div>

      {editing && (
        <ChannelEditor
          lang={lang}
          editing={editing}
          nextChannelNumber={channels.length + 1}
          onCancel={() => setEditing(null)}
          onSubmit={async (data) => {
            try {
              if (editing.mode === "new") {
                await onCreate(data);
              } else {
                await onUpdate(editing.channel.id, data);
              }
              setEditing(null);
            } catch (e) {
              alert((e as Error).message);
            }
          }}
        />
      )}
    </div>
  );
}

// ----- 채널 추가/편집 패널 (모달 오버레이 위에 또 띄움) -----

interface EditorProps {
  lang: Lang;
  editing: Exclude<Editing, null>;
  nextChannelNumber: number;
  onCancel: () => void;
  onSubmit: (data: Omit<Channel, "id" | "position">) => Promise<void>;
}

function ChannelEditor({
  lang,
  editing,
  nextChannelNumber,
  onCancel,
  onSubmit,
}: EditorProps) {
  const isNew = editing.mode === "new";
  const initial: Omit<Channel, "id" | "position"> = isNew
    ? {
        name: t(lang, "new_channel_default_name").replace(
          "{n}",
          String(nextChannelNumber)
        ),
        input_source: "rtsp",
        source_uri: "",
        video_filename: null,
        enabled: true,
      }
    : {
        name: editing.channel.name,
        input_source: editing.channel.input_source,
        source_uri: editing.channel.source_uri,
        video_filename: editing.channel.video_filename,
        enabled: editing.channel.enabled,
      };

  const [name, setName] = useState(initial.name);
  const [src, setSrc] = useState<InputSource>(initial.input_source);
  const [uri, setUri] = useState(initial.source_uri);
  const [videoFilename, setVideoFilename] = useState<string | null>(
    initial.video_filename
  );
  const [enabled, setEnabled] = useState(initial.enabled);
  const [videos, setVideos] = useState<DemoVideoItem[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (src === "video") {
      api.listVideos().then((r) => setVideos(r.videos)).catch(() => {});
    }
  }, [src]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (src === "video" && !videoFilename) {
      alert(t(lang, "msg_select_video"));
      return;
    }
    setSaving(true);
    try {
      await onSubmit({
        name: name.trim() || initial.name,
        input_source: src,
        source_uri: src === "video" ? "" : uri.trim(),
        video_filename: src === "video" ? videoFilename : null,
        enabled,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="modal-overlay"
      style={{ zIndex: 2200 }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="modal-content" style={{ width: 500 }}>
        <div className="modal-header">
          <span>{isNew ? t(lang, "add_channel") : t(lang, "edit_channel")}</span>
          <button className="close-btn" onClick={onCancel}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <form onSubmit={submit}>
            <span className="form-label">{t(lang, "channel_name")}</span>
            <input
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />

            <span className="form-label">{t(lang, "label_input_source")}</span>
            <div style={{ display: "flex", gap: 12, marginBottom: 10 }}>
              {(["rtsp", "usb", "video"] as InputSource[]).map((s) => (
                <label key={s} style={{ display: "flex", gap: 4 }}>
                  <input
                    type="radio"
                    name="src"
                    value={s}
                    checked={src === s}
                    onChange={() => setSrc(s)}
                  />
                  {t(lang, `input_${s}`)}
                </label>
              ))}
            </div>

            {src === "rtsp" && (
              <>
                <span className="form-label">{t(lang, "label_source_uri")}</span>
                <input
                  className="form-input"
                  placeholder={t(lang, "placeholder_rtsp_url")}
                  value={uri}
                  onChange={(e) => setUri(e.target.value)}
                />
              </>
            )}

            {src === "usb" && (
              <>
                <span className="form-label">{t(lang, "label_source_uri")}</span>
                <input
                  className="form-input"
                  placeholder={t(lang, "placeholder_usb_dev")}
                  value={uri}
                  onChange={(e) => setUri(e.target.value)}
                />
              </>
            )}

            {src === "video" && (
              <>
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
                      <label
                        key={v.id}
                        style={{
                          display: "flex",
                          gap: 6,
                          padding: "4px 0",
                          cursor: "pointer",
                        }}
                      >
                        <input
                          type="radio"
                          name="vsel"
                          checked={videoFilename === v.filename}
                          onChange={() => setVideoFilename(v.filename)}
                        />
                        <span>{v.filename}</span>
                      </label>
                    ))}
                  </div>
                )}
              </>
            )}

            <label
              style={{
                display: "flex",
                gap: 6,
                marginTop: 12,
                alignItems: "center",
              }}
            >
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              {t(lang, "channel_enabled")}
            </label>

            <div style={{ display: "flex", gap: 8, marginTop: 20 }}>
              <button
                type="button"
                className="btn-action"
                style={{ background: "#888" }}
                onClick={onCancel}
              >
                {t(lang, "btn_cancel")}
              </button>
              <button
                type="submit"
                className="btn-action btn-primary"
                disabled={saving}
              >
                {t(lang, "btn_apply")}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
