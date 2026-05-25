"""다채널 DeepStream 파이프라인.

파이프라인 구조 (예: 3채널):

    src_0 ─→ (옵션:sw_conv+caps) ─→ src_conv_0 ─┐
    src_1 ─→ (옵션:sw_conv+caps) ─→ src_conv_1 ─┤
    src_2 ─→ (옵션:sw_conv+caps) ─→ src_conv_2 ─┤
                                                 ↓
                          nvstreammux(batch=N) → pgie(nvinfer) → nvtracker → nvdsosd
                                                                                   ↓
                                                                          nvstreamdemux
                                                  ┌─── src_0 ──→ nvvc → caps(NVMM I420) → nvjpegenc → appsink_0
                                                  ├─── src_1 ──→ nvvc → caps(NVMM I420) → nvjpegenc → appsink_1
                                                  └─── src_2 ──→ nvvc → caps(NVMM I420) → nvjpegenc → appsink_2

- nvinfer/nvtracker/nvdsosd 는 batched buffer 한 번에 처리.
- nvstreamdemux 가 batch → 채널별 single-stream 으로 분리.
- 각 채널 appsink 의 new-sample 콜백에서 channel_id 를 closure 로 캡처해 state.set_frame.
- probe_callback 은 osd 의 sink pad (batched) 에 붙여 frame_meta.source_id 로 채널 분류.
"""

import datetime
import logging
import os
import threading
import time

from core.shared import state
from core.utils import update_deepstream_config

logger = logging.getLogger(__name__)


# Jetson(DeepStream) 외 환경에서도 백엔드 import 가능하도록 가드
try:
    import gi  # type: ignore

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst  # type: ignore
    import pyds  # type: ignore

    GST_AVAILABLE = True
except Exception as exc:  # pragma: no cover - 비-Jetson 개발환경 대응
    logger.warning("GStreamer/pyds 사용 불가: %s — 엔진은 기동되지 않습니다.", exc)
    GST_AVAILABLE = False
    Gst = GLib = pyds = None  # type: ignore


TRACKER_LIB = "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so"
TRACKER_CONFIG = "/opt/nvidia/deepstream/deepstream/samples/configs/deepstream-app/config_tracker_IOU.yml"

# 데모 영상 저장 디렉토리 (routes.py 의 VIDEO_DIR 와 동일)
VIDEO_DIR = os.environ.get("EDGESIGHT_VIDEO_DIR", "./videos")

# 모든 채널의 입력은 streammux 에서 이 해상도로 통일된다 (DeepStream 표준 batch 형성 요건).
MUX_WIDTH = 1280
MUX_HEIGHT = 720


def _channel_uri(channel: dict) -> tuple[str | None, bool]:
    """채널 설정에서 (gst URI, is_usb) 결정. URI 만들 수 없으면 None."""
    src_type = channel.get("input_source")
    if src_type == "video":
        fn = channel.get("video_filename")
        if not fn:
            return None, False
        vp = os.path.abspath(os.path.join(VIDEO_DIR, fn))
        if not os.path.exists(vp):
            logger.error("영상 파일 없음: %s (채널 %s)", vp, channel.get("id"))
            return None, False
        return "file://" + vp, False
    if src_type == "usb":
        dev = (channel.get("source_uri") or "/dev/video0").strip() or "/dev/video0"
        return f"v4l2://{dev}" if dev.startswith("/dev/") else "v4l2:///dev/video0", True
    # rtsp (기본)
    uri = (channel.get("source_uri") or "").strip()
    if not uri or uri == "0":
        return None, False  # 빈 RTSP — 채널 skip
    return uri, False


def _enabled_channels(channels: list[dict]) -> list[dict]:
    """enabled=True 채널만 position 정렬해 반환."""
    return sorted(
        [c for c in channels if c.get("enabled")],
        key=lambda c: (c.get("position", 0), c.get("id", 0)),
    )


def channels_signature(channels: list[dict]) -> tuple:
    """채널 리스트 변경 감지용 시그니처.
    enabled / source 변화 시에만 파이프라인을 재시작한다."""
    enabled = _enabled_channels(channels)
    return tuple(
        (
            c.get("id"),
            c.get("input_source"),
            c.get("source_uri") or "",
            c.get("video_filename") or "",
            c.get("position", 0),
        )
        for c in enabled
    )


class DeepStreamPipeline:
    def __init__(self):
        if GST_AVAILABLE:
            Gst.init(None)
        self.pipeline = None
        self.loop = None
        self._has_video_source = False
        # source_id (streammux sink index) → channel_id
        self._source_to_channel: dict[int, int] = {}
        # 채널별 FPS 카운터
        self._frame_counts: dict[int, int] = {}
        self._fps_start: dict[int, float] = {}
        self._fps_value: dict[int, float] = {}

    # ---------- public ----------

    def run_loop(self):
        while state.is_running:
            try:
                config_path = state.config.get("config_path")
                if not config_path:
                    time.sleep(1)
                    continue

                active_channels = _enabled_channels(state.get_channels())
                if not active_channels:
                    time.sleep(1)
                    continue

                logger.info(
                    "파이프라인 구동 시작 (채널 %d개)", len(active_channels)
                )
                self.pipeline = self._create_pipeline(active_channels, config_path)
                if not self.pipeline:
                    time.sleep(2)
                    continue

                self.loop = GLib.MainLoop()
                bus = self.pipeline.get_bus()
                bus.add_signal_watch()
                bus.connect("message", self._bus_call, self.loop)

                self.pipeline.set_state(Gst.State.PLAYING)
                self.loop.run()
                self.pipeline.set_state(Gst.State.NULL)
                logger.info("파이프라인 정리 및 재가동 준비")
            except Exception as e:
                logger.exception("파이프라인 오류: %s", e)
                time.sleep(2)

    def stop_loop(self):
        if self.loop:
            self.loop.quit()

    # ---------- pipeline construction ----------

    def _create_pipeline(self, channels: list[dict], config_path: str):
        """채널 리스트 + 모델 config 로부터 다채널 파이프라인을 빌드.
        실패 시 None."""
        pipeline = Gst.Pipeline()

        # 채널 유효성 1차 필터링 — URI 못 만드는 채널은 제외.
        prepared: list[tuple[dict, str, bool]] = []  # (channel, uri, is_usb)
        for ch in channels:
            uri, is_usb = _channel_uri(ch)
            if uri is None:
                logger.warning(
                    "채널 %s (%s) URI 결정 실패 — 스킵", ch.get("id"), ch.get("name")
                )
                continue
            prepared.append((ch, uri, is_usb))

        if not prepared:
            logger.warning("유효한 채널이 없어 파이프라인 생성 중단")
            return None

        n = len(prepared)
        self._has_video_source = any(c["input_source"] == "video" for c, _, _ in prepared)
        self._source_to_channel = {i: c["id"] for i, (c, _, _) in enumerate(prepared)}

        # 채널 삭제로 남은 잔여 메타/프레임 정리
        active_ids = {c["id"] for c, _, _ in prepared}
        for ch_id in list(state.frames.keys()):
            if ch_id not in active_ids:
                state.drop_frame(ch_id)
        for ch_id in list(state.metas.keys()):
            if ch_id not in active_ids:
                state.drop_meta(ch_id)

        # ----- streammux -----
        streammux = Gst.ElementFactory.make("nvstreammux", "streammux")
        streammux.set_property("width", MUX_WIDTH)
        streammux.set_property("height", MUX_HEIGHT)
        streammux.set_property("batch-size", max(1, n))
        # 영상 모드 1개라도 섞이면 live-source=0 (비라이브, 시간 동기화).
        # 모두 RTSP/USB 라이브면 live-source=1.
        streammux.set_property("live-source", 0 if self._has_video_source else 1)
        streammux.set_property("nvbuf-memory-type", 0)
        if self._has_video_source:
            streammux.set_property("batched-push-timeout", 4000000)
        pipeline.add(streammux)

        # ----- 채널별 source chain -----
        for idx, (ch, uri, is_usb) in enumerate(prepared):
            ok = self._build_source_chain(pipeline, streammux, idx, ch, uri, is_usb)
            if not ok:
                logger.error("채널 %s source chain 실패 — 전체 중단", ch.get("id"))
                return None

        # ----- pgie / tracker / osd -----
        pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
        pgie.set_property("config-file-path", config_path)
        pipeline.add(pgie)

        tracker = Gst.ElementFactory.make("nvtracker", "tracker")
        tracker.set_property("ll-lib-file", TRACKER_LIB)
        tracker.set_property("ll-config-file", TRACKER_CONFIG)
        tracker.set_property("tracker-width", 640)
        tracker.set_property("tracker-height", 384)
        tracker.set_property("display-tracking-id", 1)
        pipeline.add(tracker)

        nvvidconv_pre_osd = Gst.ElementFactory.make("nvvideoconvert", "nvvc_pre_osd")
        nvvidconv_pre_osd.set_property("nvbuf-memory-type", 0)
        nvvidconv_pre_osd.set_property("compute-hw", 1)
        pipeline.add(nvvidconv_pre_osd)

        nvosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")
        nvosd.set_property("display-text", 1)
        nvosd.set_property("process-mode", 0)
        pipeline.add(nvosd)

        # ----- demux -----
        demux = Gst.ElementFactory.make("nvstreamdemux", "streamdemux")
        pipeline.add(demux)

        # streammux → pgie → tracker → nvvc_pre_osd → osd → demux
        if not streammux.link(pgie):
            logger.error("streammux → pgie 링크 실패")
            return None
        if not pgie.link(tracker):
            logger.error("pgie → tracker 링크 실패")
            return None
        if not tracker.link(nvvidconv_pre_osd):
            logger.error("tracker → nvvc_pre_osd 링크 실패")
            return None
        if not nvvidconv_pre_osd.link(nvosd):
            logger.error("nvvc_pre_osd → osd 링크 실패")
            return None
        if not nvosd.link(demux):
            logger.error("osd → demux 링크 실패")
            return None

        # ----- 채널별 post-demux: nvvc → capsfilter(NVMM I420) → nvjpegenc → appsink -----
        for idx, (ch, _, _) in enumerate(prepared):
            ok = self._build_sink_chain(pipeline, demux, idx, ch["id"])
            if not ok:
                logger.error("채널 %s sink chain 실패", ch.get("id"))
                return None

        # ----- probe (batched meta) -----
        nvosd.get_static_pad("sink").add_probe(
            Gst.PadProbeType.BUFFER, self._probe_callback, 0
        )

        return pipeline

    def _build_source_chain(
        self,
        pipeline,
        streammux,
        idx: int,
        ch: dict,
        uri: str,
        is_usb: bool,
    ) -> bool:
        """채널 1개의 source → src_conv → streammux.sink_{idx} 체인 구축."""
        is_video = ch["input_source"] == "video"

        if is_video:
            source = Gst.ElementFactory.make("nvurisrcbin", f"src_{idx}")
            if source is None:
                logger.error("nvurisrcbin 생성 실패 (채널 %s)", ch.get("id"))
                return False
            source.set_property("uri", uri)
            try:
                source.set_property("file-loop", True)
            except Exception:
                logger.warning("nvurisrcbin file-loop 미지원 (idx=%s)", idx)
        else:
            source = Gst.ElementFactory.make("uridecodebin", f"src_{idx}")
            source.set_property("uri", uri)
        pipeline.add(source)

        sw_conv = None
        sw_caps = None
        if is_usb:
            sw_conv = Gst.ElementFactory.make("videoconvert", f"sw_conv_{idx}")
            sw_caps = Gst.ElementFactory.make("capsfilter", f"sw_caps_{idx}")
            sw_caps.set_property(
                "caps", Gst.Caps.from_string("video/x-raw, format=NV12")
            )
            pipeline.add(sw_conv)
            pipeline.add(sw_caps)

        src_conv = Gst.ElementFactory.make("nvvideoconvert", f"src_conv_{idx}")
        src_conv.set_property("nvbuf-memory-type", 0)
        src_conv.set_property("compute-hw", 1)
        pipeline.add(src_conv)

        # USB: source → sw_conv → sw_caps → src_conv
        # 그 외: source → src_conv
        if is_usb:
            source.connect("pad-added", self._on_pad_added, sw_conv)
            if not sw_conv.link(sw_caps):
                logger.error("sw_conv → sw_caps 링크 실패 (idx=%s)", idx)
                return False
            if not sw_caps.link(src_conv):
                logger.error("sw_caps → src_conv 링크 실패 (idx=%s)", idx)
                return False
        else:
            source.connect("pad-added", self._on_pad_added, src_conv)

        # src_conv → streammux.sink_{idx}
        mux_sink = streammux.get_request_pad(f"sink_{idx}")
        src_conv_src = src_conv.get_static_pad("src")
        if src_conv_src.link(mux_sink) != Gst.PadLinkReturn.OK:
            logger.error("src_conv → streammux.sink_%d 링크 실패", idx)
            return False
        return True

    def _build_sink_chain(self, pipeline, demux, idx: int, channel_id: int) -> bool:
        """demux.src_{idx} → nvvc → caps(NVMM I420) → nvjpegenc → appsink."""
        post_nvvc = Gst.ElementFactory.make("nvvideoconvert", f"post_nvvc_{idx}")
        post_nvvc.set_property("nvbuf-memory-type", 0)
        post_nvvc.set_property("compute-hw", 1)
        pipeline.add(post_nvvc)

        # nvjpegenc (NVJPG 하드웨어). 미지원 시 jpegenc(SW) fallback.
        jpegenc = Gst.ElementFactory.make("nvjpegenc", f"jpegenc_{idx}")
        jpeg_caps = None
        if jpegenc is not None:
            jpeg_caps = Gst.ElementFactory.make("capsfilter", f"jpeg_caps_{idx}")
            jpeg_caps.set_property(
                "caps",
                Gst.Caps.from_string("video/x-raw(memory:NVMM), format=(string)I420"),
            )
            pipeline.add(jpeg_caps)
        else:
            logger.warning("채널 %s: nvjpegenc 사용 불가 — jpegenc(SW) fallback", idx)
            jpegenc = Gst.ElementFactory.make("jpegenc", f"jpegenc_{idx}")
        pipeline.add(jpegenc)

        appsink = Gst.ElementFactory.make("appsink", f"appsink_{idx}")
        appsink.set_property("emit-signals", True)
        appsink.set_property("sync", True if self._has_video_source else False)
        appsink.set_property("max-buffers", 1)
        appsink.set_property("drop", True)
        pipeline.add(appsink)

        # demux.src_{idx} 는 request pad
        demux_src = demux.get_request_pad(f"src_{idx}")
        if demux_src.link(post_nvvc.get_static_pad("sink")) != Gst.PadLinkReturn.OK:
            logger.error("demux.src_%d → nvvc 링크 실패", idx)
            return False

        if jpeg_caps is not None:
            if not post_nvvc.link(jpeg_caps):
                logger.error("post_nvvc → jpeg_caps 링크 실패 (idx=%s)", idx)
                return False
            if not jpeg_caps.link(jpegenc):
                logger.error("jpeg_caps → jpegenc 링크 실패 (idx=%s)", idx)
                return False
        else:
            if not post_nvvc.link(jpegenc):
                logger.error("post_nvvc → jpegenc 링크 실패 (idx=%s)", idx)
                return False
        if not jpegenc.link(appsink):
            logger.error("jpegenc → appsink 링크 실패 (idx=%s)", idx)
            return False

        # closure 로 channel_id 캡처
        appsink.connect("new-sample", self._on_new_sample, channel_id)
        return True

    # ---------- callbacks ----------

    def _on_pad_added(self, _src, pad, target):
        """source(uridecodebin/nvurisrcbin) 의 dynamic src 패드를 다음 element 의 sink 에 연결.

        nvurisrcbin 은 pad-added 시점에 caps 가 None 일 수 있어 pad 이름으로 fallback:
          - nvurisrcbin: vsrc_%u (video), asrc_%u (audio)
          - uridecodebin: src_%u (caps 로 판별)
        """
        is_video = False
        caps = pad.get_current_caps()
        if caps is not None:
            try:
                is_video = "video" in caps.get_structure(0).get_name()
            except Exception:
                is_video = False
        if not is_video:
            pad_name = pad.get_name() or ""
            if pad_name.startswith("vsrc"):
                is_video = True
            elif pad_name.startswith("asrc"):
                is_video = False

        if not is_video:
            return

        sink_pad = target.get_static_pad("sink")
        if sink_pad and not sink_pad.is_linked():
            ret = pad.link(sink_pad)
            if ret != Gst.PadLinkReturn.OK:
                logger.error("source → 다음 element 링크 실패: %s", ret)

    def _on_new_sample(self, sink, channel_id):
        sample = sink.emit("pull-sample")
        if sample:
            buf = sample.get_buffer()
            res, mapinfo = buf.map(Gst.MapFlags.READ)
            if res:
                state.set_frame(channel_id, mapinfo.data.tobytes())
                buf.unmap(mapinfo)
        return Gst.FlowReturn.OK

    def _update_channel_fps(self, channel_id: int) -> float:
        self._frame_counts[channel_id] = self._frame_counts.get(channel_id, 0) + 1
        now = time.time()
        start = self._fps_start.get(channel_id)
        if start is None:
            self._fps_start[channel_id] = now
            return round(self._fps_value.get(channel_id, 0.0), 1)
        if now - start >= 1:
            self._fps_value[channel_id] = self._frame_counts[channel_id] / (now - start)
            self._frame_counts[channel_id] = 0
            self._fps_start[channel_id] = now
        return round(self._fps_value.get(channel_id, 0.0), 1)

    def _probe_callback(self, _pad, info, _u_data):
        gst_buffer = info.get_buffer()
        if not gst_buffer:
            return Gst.PadProbeReturn.OK

        batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
        l_frame = batch_meta.frame_meta_list

        per_channel_objs: dict[int, list[dict]] = {}

        while l_frame is not None:
            try:
                frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
            except StopIteration:
                break

            src_id = frame_meta.source_id
            channel_id = self._source_to_channel.get(src_id)
            if channel_id is None:
                try:
                    l_frame = l_frame.next
                except StopIteration:
                    break
                continue

            objs: list[dict] = []
            l_obj = frame_meta.obj_meta_list
            while l_obj is not None:
                try:
                    obj = pyds.NvDsObjectMeta.cast(l_obj.data)
                    objs.append({
                        "id": obj.object_id,
                        "label": obj.obj_label,
                        "confidence": round(obj.confidence, 2),
                        "bbox": [
                            int(obj.rect_params.left),
                            int(obj.rect_params.top),
                            int(obj.rect_params.width),
                            int(obj.rect_params.height),
                        ],
                    })
                except StopIteration:
                    break
                try:
                    l_obj = l_obj.next
                except StopIteration:
                    break
            per_channel_objs[channel_id] = objs

            try:
                l_frame = l_frame.next
            except StopIteration:
                break

        # state push
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        for channel_id, objs in per_channel_objs.items():
            fps = self._update_channel_fps(channel_id)
            state.set_meta(channel_id, {
                "timestamp": ts,
                "fps": fps if fps > 0 else 0.0,
                "count": len(objs),
                "objects": objs,
            })
        return Gst.PadProbeReturn.OK

    def _bus_call(self, _bus, message, loop):
        t = message.type
        if t == Gst.MessageType.EOS:
            # 영상 모드 source 가 섞여있으면 nvurisrcbin file-loop 가 자동 반복.
            # 그래도 batched EOS 가 올라온다면 (모든 source 종료) 루프 종료.
            logger.info("[Bus] EOS → 파이프라인 종료/재가동")
            loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error("[Stream Error] %s — %s", err, debug)
            loop.quit()


class AIEngine(threading.Thread):
    """설정 / 채널 변화를 감시하고 파이프라인을 재시작하는 백그라운드 스레드."""

    def __init__(self):
        super().__init__()
        self.daemon = True
        self.pipeline_wrapper = DeepStreamPipeline() if GST_AVAILABLE else None
        self.last_cfg = {
            "model": None,
            "conf": None,
            "iou": None,
            "channels_sig": None,
        }
        self._restart_lock = threading.Lock()

    def shutdown(self):
        state.is_running = False
        if self.pipeline_wrapper:
            self.pipeline_wrapper.stop_loop()

    def run(self):
        if not GST_AVAILABLE:
            logger.warning("GST 미사용 환경 — AIEngine 동작 안 함 (UI 개발용 모드)")
            return

        pipeline_thread = threading.Thread(
            target=self.pipeline_wrapper.run_loop, daemon=True
        )
        pipeline_thread.start()

        logger.info("설정 감시 시작 (model, conf, iou, channels)")

        while state.is_running:
            cur_model = state.config.get("config_path")
            cur_conf = state.config.get("conf")
            cur_iou = state.config.get("iou")
            cur_sig = channels_signature(state.get_channels())

            is_changed = cur_model and (
                cur_model != self.last_cfg["model"]
                or cur_conf != self.last_cfg["conf"]
                or cur_iou != self.last_cfg["iou"]
                or cur_sig != self.last_cfg["channels_sig"]
            )

            if is_changed:
                with self._restart_lock:
                    logger.info(
                        "설정 변경 감지 — conf=%s, iou=%s, channels=%d",
                        cur_conf,
                        cur_iou,
                        len(cur_sig),
                    )
                    update_deepstream_config(cur_model, cur_conf, cur_iou)
                    self.pipeline_wrapper.stop_loop()
                    self.last_cfg.update({
                        "model": cur_model,
                        "conf": cur_conf,
                        "iou": cur_iou,
                        "channels_sig": cur_sig,
                    })
                    logger.info("설정 변경 적용 완료")

            time.sleep(1)
