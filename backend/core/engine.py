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


class DeepStreamPipeline:
    def __init__(self):
        if GST_AVAILABLE:
            Gst.init(None)
        self.pipeline = None
        self.loop = None
        self.fps_start = time.time()
        self.frame_count = 0
        self.current_fps = 0.0

    def _create_pipeline(self):
        rtsp = state.config.get("rtsp_url", "0")
        config_path = state.config.get("config_path")

        pipeline = Gst.Pipeline()

        source = Gst.ElementFactory.make("uridecodebin", "uri-decode-bin")
        # FIX(C1): rtsp 비교는 문자열 기준. DB에는 항상 문자열로 저장됨.
        if str(rtsp) == "0":
            uri = "v4l2:///dev/video0"
        elif "://" in str(rtsp):
            uri = str(rtsp)
        else:
            uri = str(rtsp)
        source.set_property("uri", uri)

        streammux = Gst.ElementFactory.make("nvstreammux", "streammux")
        streammux.set_property("width", 1280)
        streammux.set_property("height", 720)
        streammux.set_property("batch-size", 1)
        streammux.set_property("live-source", 1)
        streammux.set_property("nvbuf-memory-type", 0)

        pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
        pgie.set_property("config-file-path", config_path)

        tracker = Gst.ElementFactory.make("nvtracker", "tracker")
        tracker.set_property("ll-lib-file", TRACKER_LIB)
        # FIX(M1): 트래커 설정은 절대경로 사용 (CWD 의존 제거)
        tracker.set_property("ll-config-file", TRACKER_CONFIG)
        tracker.set_property("tracker-width", 640)
        tracker.set_property("tracker-height", 384)
        tracker.set_property("display-tracking-id", 1)

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
        appsink.set_property("sync", False)
        appsink.set_property("max-buffers", 1)
        appsink.set_property("drop", True)

        elements = [source, streammux, pgie, tracker, nvvidconv1, nvosd,
                    nvvidconv2, jpegenc, appsink]
        for e in elements:
            pipeline.add(e)

        source.connect("pad-added", self._on_pad_added, streammux)
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
        caps = pad.get_current_caps()
        name = caps.get_structure(0).get_name()
        if "video" in name:
            sink_pad = target.get_request_pad("sink_0")
            if not sink_pad.is_linked():
                pad.link(sink_pad)

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
            loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error("[Stream Error] %s — %s", err, debug)
            loop.quit()

    def run_loop(self):
        while state.is_running:
            try:
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
        self.last_cfg = {"model": None, "rtsp": None, "conf": None, "iou": None}
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

        logger.info("설정 감시 시작 (model, rtsp, conf, iou)")

        while state.is_running:
            cur_model = state.config.get("config_path")
            cur_rtsp = state.config.get("rtsp_url")
            cur_conf = state.config.get("conf")
            cur_iou = state.config.get("iou")

            is_changed = cur_model and (
                cur_model != self.last_cfg["model"]
                or cur_rtsp != self.last_cfg["rtsp"]
                or cur_conf != self.last_cfg["conf"]
                or cur_iou != self.last_cfg["iou"]
            )

            if is_changed:
                # FIX(M2): 재시작 시 락으로 config 쓰기/파이프라인 재시작 동기화
                with self._restart_lock:
                    logger.info(
                        "설정 변경 감지 — 적용 중 (conf=%s, iou=%s)", cur_conf, cur_iou
                    )
                    update_deepstream_config(cur_model, cur_conf, cur_iou)
                    self.pipeline_wrapper.stop_loop()
                    self.last_cfg.update({
                        "model": cur_model,
                        "rtsp": cur_rtsp,
                        "conf": cur_conf,
                        "iou": cur_iou,
                    })
                    logger.info("설정 변경 완료")

            time.sleep(1)
