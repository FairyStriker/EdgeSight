import datetime
import logging
import os
import threading
import time

from core.shared import state
from core.utils import update_deepstream_config

logger = logging.getLogger(__name__)


# Jetson(DeepStream) 외 환경에서도 백엔드가 import 가능하도록 가드
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


class DeepStreamPipeline:
    def __init__(self):
        if GST_AVAILABLE:
            Gst.init(None)
        self.pipeline = None
        self.loop = None
        self.fps_start = time.time()
        self.frame_count = 0
        self.current_fps = 0.0
        # 현재 파이프라인이 영상 파일 모드인지 (EOS 시 seek 로 무한 반복)
        self._is_video = False

    def _create_pipeline(self):
        input_source = state.config.get("input_source", "rtsp")
        rtsp = state.config.get("rtsp_url", "0")
        video_filename = state.config.get("video_filename")
        config_path = state.config.get("config_path")

        pipeline = Gst.Pipeline()

        # URI 결정 — input_source 우선, 다른 칸 값은 무시.
        is_usb = False
        self._is_video = False
        if input_source == "video":
            if not video_filename:
                logger.error("video 모드인데 video_filename 비어있음")
                return None
            vp = os.path.abspath(os.path.join(VIDEO_DIR, video_filename))
            if not os.path.exists(vp):
                logger.error("영상 파일 없음: %s", vp)
                return None
            uri = "file://" + vp
            self._is_video = True
        elif input_source == "usb":
            uri = "v4l2:///dev/video0"
            is_usb = True
        else:  # rtsp (기본)
            rtsp_str = str(rtsp)
            if rtsp_str == "0":
                # backward compat: 과거 USB 모드는 rtsp_url="0"으로 표현
                uri = "v4l2:///dev/video0"
                is_usb = True
            else:
                uri = rtsp_str

        # source element 결정:
        # - 영상 모드 : nvurisrcbin (file-loop 자체 지원 → EOS 시 무한 반복 자동)
        # - 그 외     : uridecodebin (기존 동작)
        if self._is_video:
            source = Gst.ElementFactory.make("nvurisrcbin", "uri-decode-bin")
            if source is None:
                logger.error("nvurisrcbin 생성 실패")
                return None
            source.set_property("uri", uri)
            try:
                source.set_property("file-loop", True)
            except Exception:
                logger.warning("nvurisrcbin file-loop 속성 미지원")
        else:
            source = Gst.ElementFactory.make("uridecodebin", "uri-decode-bin")
            source.set_property("uri", uri)

        streammux = Gst.ElementFactory.make("nvstreammux", "streammux")
        streammux.set_property("width", 1280)
        streammux.set_property("height", 720)
        streammux.set_property("batch-size", 1)
        # 영상 파일은 비라이브(0) — 시간 동기화 활성, 실제 fps 로 재생.
        # USB/RTSP 는 라이브(1).
        streammux.set_property("live-source", 0 if self._is_video else 1)
        streammux.set_property("nvbuf-memory-type", 0)
        if self._is_video:
            # 비라이브 file source 의 batch 형성 timeout (4 sec, DeepStream 표준)
            streammux.set_property("batched-push-timeout", 4000000)

        pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
        pgie.set_property("config-file-path", config_path)

        tracker = Gst.ElementFactory.make("nvtracker", "tracker")
        tracker.set_property("ll-lib-file", TRACKER_LIB)
        # FIX(M1): 트래커 설정은 절대경로 사용 (CWD 의존 제거)
        tracker.set_property("ll-config-file", TRACKER_CONFIG)
        tracker.set_property("tracker-width", 640)
        tracker.set_property("tracker-height", 384)
        tracker.set_property("display-tracking-id", 1)

        # FIX(USB): source(uridecodebin) → streammux 사이에 변환 단계 삽입.
        # - USB(v4l2): YUYV system → videoconvert(SW) → NV12 system →
        #              nvvideoconvert → NV12 NVMM → streammux
        # - RTSP    : NV12 NVMM 그대로 → nvvideoconvert(passthrough) → streammux
        # nvvideoconvert가 YUYV(system)→NV12(NVMM) 동시 변환에 실패하므로 USB는
        # 소프트웨어 videoconvert + capsfilter(NV12)를 먼저 거쳐야 함.
        sw_conv = None
        sw_caps = None
        if is_usb:
            sw_conv = Gst.ElementFactory.make("videoconvert", "sw_converter")
            sw_caps = Gst.ElementFactory.make("capsfilter", "sw_caps_nv12")
            sw_caps.set_property(
                "caps", Gst.Caps.from_string("video/x-raw, format=NV12")
            )

        src_conv = Gst.ElementFactory.make("nvvideoconvert", "src_converter")
        src_conv.set_property("nvbuf-memory-type", 0)
        src_conv.set_property("compute-hw", 1)

        nvvidconv1 = Gst.ElementFactory.make("nvvideoconvert", "convert1")
        nvvidconv1.set_property("nvbuf-memory-type", 0)
        nvvidconv1.set_property("compute-hw", 1)

        nvosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")
        nvosd.set_property("display-text", 1)
        nvosd.set_property("process-mode", 0)

        nvvidconv2 = Gst.ElementFactory.make("nvvideoconvert", "conv2")
        nvvidconv2.set_property("nvbuf-memory-type", 0)
        nvvidconv2.set_property("compute-hw", 1)

        jpegenc = Gst.ElementFactory.make("jpegenc", "jpegenc")
        appsink = Gst.ElementFactory.make("appsink", "appsink")
        appsink.set_property("emit-signals", True)
        # 영상 모드는 sync=True 로 실제 frame rate 따라 emit (배속 방지).
        # USB/RTSP 라이브는 sync=False (가능한 한 빨리).
        appsink.set_property("sync", True if self._is_video else False)
        appsink.set_property("max-buffers", 1)
        appsink.set_property("drop", True)

        elements = [source, src_conv, streammux, pgie, tracker, nvvidconv1,
                    nvosd, nvvidconv2, jpegenc, appsink]
        if is_usb:
            elements.extend([sw_conv, sw_caps])
        for e in elements:
            pipeline.add(e)

        # 입력 경로:
        # - USB : uridecodebin →(동적)→ sw_conv → sw_caps(NV12) → src_conv → streammux
        # - 그외 : uridecodebin →(동적)→ src_conv → streammux
        if is_usb:
            # uridecodebin은 sw_conv에 동적 연결, sw_conv→sw_caps→src_conv는 정적 연결
            source.connect("pad-added", self._on_pad_added, sw_conv)
            if not sw_conv.link(sw_caps):
                logger.error("sw_conv → sw_caps 링크 실패")
                return None
            if not sw_caps.link(src_conv):
                logger.error("sw_caps → src_conv 링크 실패")
                return None
        else:
            source.connect("pad-added", self._on_pad_added, src_conv)

        # src_conv(src) → streammux(sink_0) 는 정적/요청 패드 직접 연결
        mux_sink = streammux.get_request_pad("sink_0")
        src_conv_src = src_conv.get_static_pad("src")
        if src_conv_src.link(mux_sink) != Gst.PadLinkReturn.OK:
            logger.error("src_conv → streammux 링크 실패")
            return None

        streammux.link(pgie)
        pgie.link(tracker)
        tracker.link(nvvidconv1)
        nvvidconv1.link(nvosd)
        nvosd.link(nvvidconv2)
        nvvidconv2.link(jpegenc)
        jpegenc.link(appsink)
        appsink.connect("new-sample", self._on_new_sample, None)

        nvosd.get_static_pad("sink").add_probe(Gst.PadProbeType.BUFFER, self._probe_callback, 0)
        return pipeline

    def _on_pad_added(self, src, pad, target):
        """source(uridecodebin / nvurisrcbin) → 다음 element 동적 링크.

        nvurisrcbin은 pad-added 시 caps가 아직 None 일 수 있어 pad 이름으로 fallback:
          - nvurisrcbin: vsrc_%u (video), asrc_%u (audio)
          - uridecodebin: src_%u (caps로 판별)
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

    def _update_fps(self):
        self.frame_count += 1
        now = time.time()
        if now - self.fps_start >= 1:
            self.current_fps = self.frame_count / (now - self.fps_start)
            self.frame_count = 0
            self.fps_start = now
        return round(self.current_fps, 1)

    def _on_new_sample(self, sink, _data):
        sample = sink.emit("pull-sample")
        if sample:
            buf = sample.get_buffer()
            res, mapinfo = buf.map(Gst.MapFlags.READ)
            if res:
                state.set_frame(mapinfo.data.tobytes())
                buf.unmap(mapinfo)
        return Gst.FlowReturn.OK

    def _probe_callback(self, _pad, info, _u_data):
        gst_buffer = info.get_buffer()
        if not gst_buffer:
            return Gst.PadProbeReturn.OK

        batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
        l_frame = batch_meta.frame_meta_list

        detected_objects = []
        fps = self._update_fps()

        while l_frame is not None:
            try:
                frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
            except StopIteration:
                break

            l_obj = frame_meta.obj_meta_list
            while l_obj is not None:
                try:
                    obj = pyds.NvDsObjectMeta.cast(l_obj.data)
                    detected_objects.append({
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
            try:
                l_frame = l_frame.next
            except StopIteration:
                break

        state.set_meta({
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "fps": fps if fps > 0 else 0.0,
            "count": len(detected_objects),
            "objects": detected_objects,
        })
        return Gst.PadProbeReturn.OK

    def _bus_call(self, _bus, message, loop):
        t = message.type
        if t == Gst.MessageType.EOS:
            # 영상 파일 모드면 EOS 시 처음으로 seek 하여 무한 반복.
            if self._is_video and self.pipeline is not None:
                logger.info("[video] EOS → 영상 처음으로 seek (loop)")
                ok = self.pipeline.seek_simple(
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    0,
                )
                if not ok:
                    logger.warning("[video] seek 실패 — 파이프라인 종료")
                    loop.quit()
                return
            loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error("[Stream Error] %s — %s", err, debug)
            loop.quit()

    def run_loop(self):
        while state.is_running:
            try:
                # FIX: 활성 모델이 없으면 파이프라인 생성을 건너뛴다.
                # nvinfer set_property("config-file-path", None) 시 C++ string
                # null 생성자에서 std::logic_error로 abort 되는 문제 방지.
                config_path = state.config.get("config_path")
                if not config_path:
                    time.sleep(1)
                    continue

                logger.info("파이프라인 구동 시작")
                self.pipeline = self._create_pipeline()
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


class AIEngine(threading.Thread):
    """설정 변화를 감시하고 파이프라인을 재시작하는 백그라운드 스레드."""

    def __init__(self):
        super().__init__()
        self.daemon = True
        self.pipeline_wrapper = DeepStreamPipeline() if GST_AVAILABLE else None
        self.last_cfg = {
            "model": None, "rtsp": None, "conf": None, "iou": None,
            "input_source": None, "video_filename": None,
        }
        self._restart_lock = threading.Lock()

    def shutdown(self):
        state.is_running = False
        if self.pipeline_wrapper:
            self.pipeline_wrapper.stop_loop()

    def run(self):
        if not GST_AVAILABLE:
            logger.warning("GST 미사용 환경 — AIEngine은 동작하지 않습니다 (UI 개발용 모드).")
            return

        pipeline_thread = threading.Thread(
            target=self.pipeline_wrapper.run_loop, daemon=True
        )
        pipeline_thread.start()

        logger.info("설정 감시 시작 (model, rtsp, conf, iou, input_source, video)")

        while state.is_running:
            cur_model = state.config.get("config_path")
            cur_rtsp = state.config.get("rtsp_url")
            cur_conf = state.config.get("conf")
            cur_iou = state.config.get("iou")
            cur_src = state.config.get("input_source", "rtsp")
            cur_video = state.config.get("video_filename")

            is_changed = cur_model and (
                cur_model != self.last_cfg["model"]
                or cur_rtsp != self.last_cfg["rtsp"]
                or cur_conf != self.last_cfg["conf"]
                or cur_iou != self.last_cfg["iou"]
                or cur_src != self.last_cfg["input_source"]
                or cur_video != self.last_cfg["video_filename"]
            )

            if is_changed:
                with self._restart_lock:
                    logger.info(
                        "설정 변경 감지 — 적용 중 (conf=%s, iou=%s, src=%s, video=%s)",
                        cur_conf, cur_iou, cur_src, cur_video,
                    )
                    update_deepstream_config(cur_model, cur_conf, cur_iou)
                    self.pipeline_wrapper.stop_loop()
                    self.last_cfg.update({
                        "model": cur_model,
                        "rtsp": cur_rtsp,
                        "conf": cur_conf,
                        "iou": cur_iou,
                        "input_source": cur_src,
                        "video_filename": cur_video,
                    })
                    logger.info("설정 변경 완료")

            time.sleep(1)
