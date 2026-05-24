import logging
import os

logger = logging.getLogger(__name__)


ENGINE_CONFIG_TEMPLATE = """
[property]
gpu-id=0
net-scale-factor=0.0039215697906911373
model-color-format=0
{onnx_line}
model-engine-file={engine_path}
#int8-calib-file=calib.table
labelfile-path={label_path}
batch-size=1
network-mode=2
num-detected-classes={num_classes}
interval=0
gie-unique-id=1
process-mode=1
network-type=0
cluster-mode=2
maintain-aspect-ratio=1
symmetric-padding=1
#workspace-size=2000
parse-bbox-func-name=NvDsInferParseYolo
#parse-bbox-func-name=NvDsInferParseYoloCuda
custom-lib-path={custom_lib_path}
engine-create-func-name=NvDsInferYoloCudaEngineGet

[class-attrs-all]
nms-iou-threshold={iou}
pre-cluster-threshold={conf}
topk=300
"""


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def custom_lib_path() -> str:
    return os.path.join(_project_root(), "libnvdsinfer_custom_impl_Yolo.so")


def create_engine_config(
    model_filename: str,
    model_dir: str,
    config_dir: str,
    class_names_str: str,
    conf: float,
    iou: float,
    onnx_path: str | None = None,
):
    """모델 업로드 시 nvinfer config 파일과 라벨 파일을 동시에 생성한다.

    onnx_path가 주어지면 nvinfer가 해당 ONNX로부터 .engine을 자동 빌드하도록 설정한다.
    None이면 사전 빌드된 .engine만 사용 (onnx-file 라인은 주석 처리).
    """
    name_no_ext = os.path.splitext(model_filename)[0]
    engine_path = os.path.abspath(os.path.join(model_dir, model_filename))

    so_file_path = custom_lib_path()
    if not os.path.exists(so_file_path):
        logger.warning("커스텀 라이브러리를 찾지 못했습니다: %s", so_file_path)

    classes = [c.strip() for c in class_names_str.split(",") if c.strip()]
    label_filename = f"labels_{name_no_ext}.txt"
    label_path = os.path.abspath(os.path.join(config_dir, label_filename))

    with open(label_path, "w", encoding="utf-8") as f:
        f.write("\n".join(classes))

    config_filename = f"config_infer_{name_no_ext}.txt"
    config_path = os.path.abspath(os.path.join(config_dir, config_filename))

    if onnx_path:
        onnx_line = f"onnx-file={os.path.abspath(onnx_path)}"
    else:
        onnx_line = "#onnx-file=  (not provided — pre-built engine)"

    content = ENGINE_CONFIG_TEMPLATE.format(
        engine_path=engine_path,
        label_path=label_path,
        num_classes=len(classes),
        conf=conf,
        iou=iou,
        custom_lib_path=so_file_path,
        onnx_line=onnx_line,
    )
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)

    return config_path, config_filename


def update_deepstream_config(config_path: str, conf: float, iou: float) -> bool:
    """기존 nvinfer config 파일에서 conf/iou 값만 갱신한다(주석 라인은 보존)."""
    if not config_path or not os.path.exists(config_path):
        logger.warning("config 파일을 찾지 못해 갱신을 건너뜁니다: %s", config_path)
        return False

    try:
        with open(config_path, "r") as f:
            lines = f.readlines()

        new_lines = []
        for line in lines:
            stripped = line.strip()
            if "pre-cluster-threshold" in line and not stripped.startswith("#"):
                new_lines.append(f"pre-cluster-threshold={conf}\n")
            elif "nms-iou-threshold" in line and not stripped.startswith("#"):
                new_lines.append(f"nms-iou-threshold={iou}\n")
            else:
                new_lines.append(line)

        with open(config_path, "w") as f:
            f.writelines(new_lines)
        logger.info("config 갱신 완료 (conf=%s, iou=%s)", conf, iou)
        return True
    except Exception as e:
        logger.exception("config 갱신 중 오류: %s", e)
        return False


def delete_generated_files(config_path: str) -> None:
    """모델 삭제 시 config + 연결된 라벨/ONNX/PT 파일을 함께 정리한다."""
    if not config_path or not os.path.exists(config_path):
        return

    label_path = None
    onnx_path = None
    try:
        with open(config_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "labelfile-path=" in line:
                    label_path = line.split("=", 1)[1].strip()
                elif "onnx-file=" in line:
                    onnx_path = line.split("=", 1)[1].strip()
    except Exception:
        pass

    try:
        os.remove(config_path)
        logger.info("config 파일 삭제: %s", config_path)
    except Exception as e:
        logger.warning("config 파일 삭제 실패: %s", e)

    for label, p in (("라벨", label_path), ("ONNX", onnx_path)):
        if p and os.path.exists(p):
            try:
                os.remove(p)
                logger.info("%s 파일 삭제: %s", label, p)
            except Exception as e:
                logger.warning("%s 파일 삭제 실패: %s", label, e)

    # 동일 베이스명의 .pt 파일도 함께 정리 (PT 업로드 경로 보관용)
    if onnx_path:
        pt_candidate = os.path.splitext(onnx_path)[0] + ".pt"
        if os.path.exists(pt_candidate):
            try:
                os.remove(pt_candidate)
                logger.info("PT 파일 삭제: %s", pt_candidate)
            except Exception as e:
                logger.warning("PT 파일 삭제 실패: %s", e)
