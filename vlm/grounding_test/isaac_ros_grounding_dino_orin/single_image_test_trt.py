#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
from ctypes.util import find_library
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import torch


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE = REPO_ROOT / "data/demo.png"
DEFAULT_PLAN = REPO_ROOT / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.plan"
MAX_TEXT_LENGTH = 256
IMAGE_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGE_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


@dataclass
class ImageTransformInfo:
    original_width: int
    original_height: int
    resized_width: int
    resized_height: int
    scale_x: float
    scale_y: float
    network_width: int
    network_height: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone single-image Grounding DINO TensorRT plan test for AGX Orin."
    )
    parser.add_argument("--image-path", type=Path, default=DEFAULT_IMAGE, help="Input image path.")
    parser.add_argument(
        "--engine-path",
        type=Path,
        default=DEFAULT_PLAN,
        help="Path to Grounding DINO TensorRT plan.",
    )
    parser.add_argument(
        "--plugin-library",
        type=Path,
        default=None,
        help="Optional TensorRT plugin shared library to load before deserializing the engine.",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        required=True,
        help="Dot-separated prompt, e.g. 'person. traffic cone.'.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to the input image directory.",
    )
    parser.add_argument(
        "--box-threshold",
        type=float,
        default=0.5,
        help="Detection score threshold.",
    )
    parser.add_argument(
        "--debug-topk",
        type=int,
        default=10,
        help="Number of top query-label scores to print for debugging.",
    )
    parser.add_argument(
        "--network-width",
        type=int,
        default=960,
        help="Model input width if it cannot be inferred from the engine.",
    )
    parser.add_argument(
        "--network-height",
        type=int,
        default=544,
        help="Model input height if it cannot be inferred from the engine.",
    )
    parser.add_argument("--save-csv", action="store_true", help="Save detections to CSV.")
    return parser.parse_args()


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def candidate_engine_paths() -> list[Path]:
    candidates = [
        REPO_ROOT / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.plan",
        REPO_ROOT.parent / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.plan",
        REPO_ROOT.parent.parent / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.plan",
        Path.cwd() / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.plan",
        Path.cwd().parent / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.plan",
    ]
    unique = []
    seen = set()
    for path in candidates:
        resolved = path.expanduser().resolve()
        if str(resolved) in seen:
            continue
        seen.add(str(resolved))
        unique.append(resolved)
    return unique


def resolve_engine_path(requested_engine: Path) -> Path:
    requested_engine = requested_engine.expanduser().resolve()
    if requested_engine.exists():
        return requested_engine

    for candidate in candidate_engine_paths():
        if candidate.exists():
            return candidate

    searched = "\n".join(f"- {path}" for path in candidate_engine_paths())
    raise FileNotFoundError(
        "Could not find Grounding DINO TensorRT plan.\n"
        "Searched these locations:\n"
        f"{searched}\n"
        "Pass the correct path explicitly with --engine-path."
    )


def preprocess_caption(caption: str) -> str:
    caption = caption.lower().strip()
    return caption if caption.endswith(".") else caption + "."


def create_tokenizer():
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `transformers`. Install it in the AGX Orin environment."
        ) from exc

    try:
        tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased", local_files_only=True)
    except OSError:
        tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")

    if not getattr(tokenizer, "is_fast", False):
        raise RuntimeError("Grounding DINO requires a fast tokenizer for char_to_token alignment.")
    return tokenizer


def generate_text_token_mask_and_position_ids(
    tokenized: dict[str, np.ndarray],
    special_token_ids,
) -> tuple[np.ndarray, np.ndarray]:
    input_ids = tokenized["input_ids"].squeeze(0)
    num_token = len(input_ids)
    special_positions = np.where(np.isin(input_ids, special_token_ids))[0]

    text_token_mask = np.eye(num_token, dtype=np.uint8)
    position_ids = np.zeros(num_token, dtype=np.int64)

    previous_col = 0
    for col in special_positions:
        if col not in (0, num_token - 1):
            text_token_mask[previous_col + 1 : col + 1, previous_col + 1 : col + 1] = 1
            position_ids[previous_col + 1 : col + 1] = np.arange(col - previous_col)
            previous_col = col

    return (
        text_token_mask[np.newaxis, :MAX_TEXT_LENGTH, :MAX_TEXT_LENGTH],
        position_ids[np.newaxis, :MAX_TEXT_LENGTH],
    )


def create_positive_map(tokenized_fast, class_ids: list[str], text: str) -> np.ndarray:
    pos_map = np.zeros((len(class_ids), MAX_TEXT_LENGTH), dtype=np.uint8)

    search_cursor = 0
    for idx, category in enumerate(class_ids):
        start_char = text.find(category, search_cursor)
        if start_char < 0:
            start_char = text.find(category)
        if start_char < 0:
            continue

        end_char = start_char + len(category) - 1
        search_cursor = start_char + len(category)

        start_token = tokenized_fast.char_to_token(0, start_char)
        end_token = tokenized_fast.char_to_token(0, end_char)

        if end_token is None and end_char > 0:
            end_token = tokenized_fast.char_to_token(0, end_char - 1)
        if end_token is None and end_char > 1:
            end_token = tokenized_fast.char_to_token(0, end_char - 2)

        if start_token is not None and end_token is not None and start_token <= end_token:
            pos_map[idx, start_token : end_token + 1] = 1

    return pos_map


def tokenize_prompt(tokenizer, prompt: str):
    prompt = preprocess_caption(prompt)

    tokenized_np = tokenizer(
        prompt,
        padding="max_length",
        return_tensors="np",
        max_length=MAX_TEXT_LENGTH,
        truncation=True,
    )
    tokenized_fast = tokenizer(
        prompt,
        padding="max_length",
        return_tensors="np",
        max_length=MAX_TEXT_LENGTH,
        truncation=True,
        return_offsets_mapping=True,
    )

    class_ids = [item.strip() for item in prompt.split(".") if item.strip()]
    special_token_ids = tokenizer.convert_tokens_to_ids(["[CLS]", "[SEP]", ".", "?"])
    text_token_mask, position_ids = generate_text_token_mask_and_position_ids(
        tokenized_np, special_token_ids
    )
    positive_map = create_positive_map(tokenized_fast, class_ids, prompt)

    text_inputs = {
        "input_ids": tokenized_np["input_ids"][:, :MAX_TEXT_LENGTH].astype(np.int64),
        "attention_mask": tokenized_np["attention_mask"][:, :MAX_TEXT_LENGTH].astype(np.uint8),
        "token_type_ids": tokenized_np["token_type_ids"][:, :MAX_TEXT_LENGTH].astype(np.int64),
        "position_ids": position_ids.astype(np.int64),
        "text_token_mask": text_token_mask.astype(np.uint8),
    }
    return text_inputs, positive_map.astype(np.float32), class_ids, prompt


def resize_and_pad_image(
    image_bgr: np.ndarray,
    network_width: int,
    network_height: int,
) -> tuple[np.ndarray, ImageTransformInfo]:
    original_height, original_width = image_bgr.shape[:2]
    scale = min(network_width / original_width, network_height / original_height)
    resized_width = max(1, int(round(original_width * scale)))
    resized_height = max(1, int(round(original_height * scale)))

    resized_bgr = cv2.resize(
        image_bgr,
        (resized_width, resized_height),
        interpolation=cv2.INTER_LINEAR,
    )

    # keep_aspect_ratio + bottom-right padding
    canvas_bgr = np.zeros((network_height, network_width, 3), dtype=np.uint8)
    canvas_bgr[:resized_height, :resized_width] = resized_bgr

    info = ImageTransformInfo(
        original_width=original_width,
        original_height=original_height,
        resized_width=resized_width,
        resized_height=resized_height,
        scale_x=resized_width / original_width,
        scale_y=resized_height / original_height,
        network_width=network_width,
        network_height=network_height,
    )
    return canvas_bgr, info


def preprocess_image(
    image_bgr: np.ndarray,
    network_width: int,
    network_height: int,
) -> tuple[np.ndarray, np.ndarray, ImageTransformInfo]:
    canvas_bgr, info = resize_and_pad_image(image_bgr, network_width, network_height)

    rgb = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - IMAGE_MEAN) / IMAGE_STD
    rgb = np.transpose(rgb, (2, 0, 1))
    tensor = np.expand_dims(rgb, axis=0).astype(np.float32)

    return tensor, canvas_bgr, info


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def decode_scores(pred_logits: np.ndarray, positive_map: np.ndarray) -> np.ndarray:
    prob_to_token = sigmoid(pred_logits)
    row_sums = positive_map.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    pos_map_normalized = positive_map / row_sums
    return prob_to_token @ pos_map_normalized.T


def convert_boxes_to_network(pred_boxes: np.ndarray, info: ImageTransformInfo) -> np.ndarray:
    cx = pred_boxes[:, 0] * info.network_width
    cy = pred_boxes[:, 1] * info.network_height
    bw = pred_boxes[:, 2] * info.network_width
    bh = pred_boxes[:, 3] * info.network_height

    x1 = cx - bw / 2.0
    y1 = cy - bh / 2.0
    x2 = cx + bw / 2.0
    y2 = cy + bh / 2.0

    x1 = np.clip(x1, 0, info.network_width - 1)
    y1 = np.clip(y1, 0, info.network_height - 1)
    x2 = np.clip(x2, 0, info.network_width - 1)
    y2 = np.clip(y2, 0, info.network_height - 1)

    return np.stack([x1, y1, x2, y2], axis=1).astype(np.float32)


def convert_network_boxes_to_original(
    boxes_network_xyxy: np.ndarray,
    info: ImageTransformInfo,
) -> np.ndarray:
    x1 = np.clip(boxes_network_xyxy[:, 0], 0, info.resized_width)
    y1 = np.clip(boxes_network_xyxy[:, 1], 0, info.resized_height)
    x2 = np.clip(boxes_network_xyxy[:, 2], 0, info.resized_width)
    y2 = np.clip(boxes_network_xyxy[:, 3], 0, info.resized_height)

    x1 = x1 / info.scale_x
    y1 = y1 / info.scale_y
    x2 = x2 / info.scale_x
    y2 = y2 / info.scale_y

    x1 = np.clip(x1, 0, info.original_width - 1)
    y1 = np.clip(y1, 0, info.original_height - 1)
    x2 = np.clip(x2, 0, info.original_width - 1)
    y2 = np.clip(y2, 0, info.original_height - 1)

    return np.stack([x1, y1, x2, y2], axis=1).astype(np.float32)


def draw_detections(
    image_bgr: np.ndarray,
    detections: list[dict],
    coord_prefix: str,
) -> np.ndarray:
    annotated = image_bgr.copy()
    for det in detections:
        x1 = int(round(det[f"{coord_prefix}_x1"]))
        y1 = int(round(det[f"{coord_prefix}_y1"]))
        x2 = int(round(det[f"{coord_prefix}_x2"]))
        y2 = int(round(det[f"{coord_prefix}_y2"]))
        label = f"{det['label']} {float(det['score']):.2f}"

        cv2.rectangle(annotated, (x1, y1), (x2, y2), (40, 220, 120), 2)
        cv2.putText(
            annotated,
            label,
            (x1, max(y1 - 8, 0)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (40, 220, 120),
            2,
            cv2.LINE_AA,
        )
    return annotated


def candidate_plugin_libraries() -> list[Path]:
    names = [
        "libnvinfer_plugin.so",
        "libnvinfer_plugin.so.10",
        "libnvinfer_plugin.so.9",
        "libnvinfer_plugin.so.8",
    ]
    candidates: list[Path] = []
    seen = set()

    found = find_library("nvinfer_plugin")
    if found:
        path = Path(found)
        if str(path) not in seen:
            seen.add(str(path))
            candidates.append(path)

    search_dirs = [
        Path("/usr/lib"),
        Path("/usr/lib/aarch64-linux-gnu"),
        Path("/usr/local/lib"),
        Path("/usr/local/tensorrt/lib"),
        Path("/usr/lib/x86_64-linux-gnu"),
    ]
    for search_dir in search_dirs:
        for name in names:
            for match in search_dir.glob(name + "*"):
                resolved = match.resolve()
                if str(resolved) in seen:
                    continue
                seen.add(str(resolved))
                candidates.append(resolved)
    return candidates


def try_load_plugin_library(plugin_library: Path) -> bool:
    try:
        ctypes.CDLL(str(plugin_library), mode=ctypes.RTLD_GLOBAL)
        return True
    except OSError:
        return False


def create_engine(engine_path: Path, plugin_library: Path | None = None):
    try:
        import tensorrt as trt
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `tensorrt`. Run this script inside the AGX/TensorRT environment."
        ) from exc

    logger = trt.Logger(trt.Logger.WARNING)
    loaded_plugin_paths: list[Path] = []

    if plugin_library is not None:
        plugin_library = plugin_library.expanduser().resolve()
        ensure_exists(plugin_library, "TensorRT plugin library")
        if not try_load_plugin_library(plugin_library):
            raise RuntimeError(f"Failed to dlopen TensorRT plugin library: {plugin_library}")
        loaded_plugin_paths.append(plugin_library)
    else:
        for candidate in candidate_plugin_libraries():
            if try_load_plugin_library(candidate):
                loaded_plugin_paths.append(candidate)
                break

    try:
        trt.init_libnvinfer_plugins(logger, "")
    except Exception:
        pass

    if plugin_library is not None:
        try:
            registry = trt.get_plugin_registry()
            if registry is not None and hasattr(registry, "load_library"):
                registry.load_library(str(plugin_library))
        except Exception as exc:
            raise RuntimeError(f"Failed to register TensorRT plugin library: {plugin_library}") from exc

    runtime = trt.Runtime(logger)
    engine_bytes = engine_path.read_bytes()
    engine = runtime.deserialize_cuda_engine(engine_bytes)
    if engine is None:
        loaded_desc = (
            "\n".join(f"- {path}" for path in loaded_plugin_paths)
            if loaded_plugin_paths
            else "(none auto-loaded)"
        )
        raise RuntimeError(
            "Failed to deserialize TensorRT engine.\n"
            f"Engine: {engine_path}\n"
            "Loaded plugin libraries:\n"
            f"{loaded_desc}\n"
            "This usually means one of these:\n"
            "1. The required TensorRT plugin creator is not registered.\n"
            "2. The TensorRT OSS plugin library for MultiscaleDeformableAttnPlugin_TRT is missing.\n"
            "3. The engine was built on a different device / TensorRT stack and should be rebuilt on this AGX.\n"
            "Try again with --plugin-library if you know the plugin .so path, or rebuild the engine locally."
        )
    return trt, logger, runtime, engine


def get_tensor_names(engine) -> list[str]:
    if hasattr(engine, "num_io_tensors"):
        return [engine.get_tensor_name(i) for i in range(engine.num_io_tensors)]
    return [engine.get_binding_name(i) for i in range(engine.num_bindings)]


def resolve_tensor_name(actual_names: list[str], aliases: list[str]) -> str:
    lowered = {name.lower(): name for name in actual_names}
    for alias in aliases:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    raise KeyError(f"Could not resolve tensor name from aliases: {aliases}")


def infer_network_size_from_engine(engine, fallback_width: int, fallback_height: int) -> tuple[int, int]:
    names = get_tensor_names(engine)
    image_name = resolve_tensor_name(names, ["inputs", "images", "image", "input"])
    if hasattr(engine, "get_tensor_shape"):
        shape = engine.get_tensor_shape(image_name)
    else:
        shape = engine.get_binding_shape(image_name)
    if len(shape) == 4 and shape[2] > 0 and shape[3] > 0:
        return int(shape[3]), int(shape[2])
    return fallback_width, fallback_height


def torch_dtype_from_trt(dtype_name: str):
    mapping = {
        "DataType.FLOAT": torch.float32,
        "DataType.HALF": torch.float16,
        "DataType.INT8": torch.int8,
        "DataType.INT32": torch.int32,
        "DataType.INT64": torch.int64,
        "DataType.BOOL": torch.bool,
        "DataType.UINT8": torch.uint8,
    }
    if dtype_name not in mapping:
        raise KeyError(f"Unsupported TensorRT dtype: {dtype_name}")
    return mapping[dtype_name]


def numpy_dtype_from_torch(torch_dtype: torch.dtype):
    mapping = {
        torch.float32: np.float32,
        torch.float16: np.float16,
        torch.int8: np.int8,
        torch.int32: np.int32,
        torch.int64: np.int64,
        torch.uint8: np.uint8,
        torch.bool: np.bool_,
    }
    if torch_dtype not in mapping:
        raise KeyError(f"Unsupported torch dtype: {torch_dtype}")
    return mapping[torch_dtype]


def get_tensor_dtype(engine, name: str):
    if hasattr(engine, "get_tensor_dtype"):
        return engine.get_tensor_dtype(name)
    return engine.get_binding_dtype(name)


def get_tensor_shape(engine_or_context, name: str):
    if hasattr(engine_or_context, "get_tensor_shape"):
        return tuple(int(dim) for dim in engine_or_context.get_tensor_shape(name))
    return tuple(int(dim) for dim in engine_or_context.get_binding_shape(name))


def set_tensor_shape(context, name: str, shape: tuple[int, ...]) -> None:
    if hasattr(context, "set_input_shape"):
        context.set_input_shape(name, shape)
    else:
        index = context.engine.get_binding_index(name)
        context.set_binding_shape(index, shape)


def set_tensor_address(context, name: str, address: int) -> None:
    if hasattr(context, "set_tensor_address"):
        context.set_tensor_address(name, address)


def execute_context(context, bindings: list[int], stream) -> None:
    if hasattr(context, "execute_async_v3"):
        context.execute_async_v3(stream.cuda_stream)
    elif hasattr(context, "execute_async_v2"):
        context.execute_async_v2(bindings=bindings, stream_handle=stream.cuda_stream)
    else:
        context.execute_v2(bindings=bindings)


def cast_numpy_for_engine_input(np_value: np.ndarray, expected_torch_dtype: torch.dtype) -> np.ndarray:
    target_np_dtype = numpy_dtype_from_torch(expected_torch_dtype)
    return np_value.astype(target_np_dtype, copy=False)


def run_inference(engine, trt_module, image_tensor: np.ndarray, text_inputs: dict[str, np.ndarray]):
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required to execute this TensorRT plan.")

    context = engine.create_execution_context()
    tensor_names = get_tensor_names(engine)

    image_name = resolve_tensor_name(tensor_names, ["inputs", "images", "image", "input"])
    input_names = {
        "image": image_name,
        "input_ids": resolve_tensor_name(tensor_names, ["input_ids"]),
        "attention_mask": resolve_tensor_name(tensor_names, ["attention_mask"]),
        "position_ids": resolve_tensor_name(tensor_names, ["position_ids"]),
        "token_type_ids": resolve_tensor_name(tensor_names, ["token_type_ids"]),
        "text_token_mask": resolve_tensor_name(tensor_names, ["text_token_mask"]),
    }
    output_names = {
        "pred_logits": resolve_tensor_name(tensor_names, ["pred_logits", "scores"]),
        "pred_boxes": resolve_tensor_name(tensor_names, ["pred_boxes", "boxes"]),
    }

    set_tensor_shape(context, input_names["image"], tuple(image_tensor.shape))
    for key in ["input_ids", "attention_mask", "position_ids", "token_type_ids", "text_token_mask"]:
        set_tensor_shape(context, input_names[key], tuple(text_inputs[key].shape))

    print("=== Engine input dtypes / shapes ===")
    for key, name in input_names.items():
        print(
            f"{key}: tensor_name={name}, "
            f"shape={get_tensor_shape(context, name)}, "
            f"dtype={get_tensor_dtype(engine, name)}"
        )

    print("=== Engine output dtypes / shapes ===")
    for key, name in output_names.items():
        print(
            f"{key}: tensor_name={name}, "
            f"shape={get_tensor_shape(context, name)}, "
            f"dtype={get_tensor_dtype(engine, name)}"
        )

    stream = torch.cuda.Stream()
    with torch.cuda.stream(stream):
        buffers: dict[str, torch.Tensor] = {}

        image_expected_dtype = torch_dtype_from_trt(str(get_tensor_dtype(engine, input_names["image"])))
        image_np = cast_numpy_for_engine_input(image_tensor, image_expected_dtype)
        buffers[input_names["image"]] = torch.as_tensor(
            image_np,
            dtype=image_expected_dtype,
            device="cuda",
        )

        for key in ["input_ids", "attention_mask", "position_ids", "token_type_ids", "text_token_mask"]:
            name = input_names[key]
            expected_torch_dtype = torch_dtype_from_trt(str(get_tensor_dtype(engine, name)))
            np_value = cast_numpy_for_engine_input(text_inputs[key], expected_torch_dtype)
            buffers[name] = torch.as_tensor(
                np_value,
                dtype=expected_torch_dtype,
                device="cuda",
            )

        for output_name in output_names.values():
            output_shape = get_tensor_shape(context, output_name)
            output_dtype = torch_dtype_from_trt(str(get_tensor_dtype(engine, output_name)))
            buffers[output_name] = torch.empty(
                output_shape,
                dtype=output_dtype,
                device="cuda",
            )

        bindings: list[int] = []
        if hasattr(engine, "num_io_tensors"):
            ordered_names = tensor_names
        else:
            ordered_names = [engine.get_binding_name(i) for i in range(engine.num_bindings)]

        for name in ordered_names:
            tensor = buffers[name]
            if hasattr(context, "set_tensor_address"):
                set_tensor_address(context, name, tensor.data_ptr())
            bindings.append(tensor.data_ptr())

        execute_context(context, bindings, stream)

    stream.synchronize()

    pred_logits = buffers[output_names["pred_logits"]].detach().float().cpu().numpy()[0]
    pred_boxes = buffers[output_names["pred_boxes"]].detach().float().cpu().numpy()[0]
    return pred_logits, pred_boxes, input_names, output_names


def summarize_top_scores(
    label_scores: np.ndarray,
    class_ids: list[str],
    boxes_original_xyxy: np.ndarray,
    topk: int,
) -> list[dict]:
    summaries: list[dict] = []
    if label_scores.size == 0 or not class_ids:
        return summaries

    for query_idx in range(label_scores.shape[0]):
        for label_idx, class_name in enumerate(class_ids):
            summaries.append(
                {
                    "query_idx": query_idx,
                    "label_idx": label_idx,
                    "label": class_name,
                    "score": float(label_scores[query_idx, label_idx]),
                    "x1": float(boxes_original_xyxy[query_idx, 0]),
                    "y1": float(boxes_original_xyxy[query_idx, 1]),
                    "x2": float(boxes_original_xyxy[query_idx, 2]),
                    "y2": float(boxes_original_xyxy[query_idx, 3]),
                }
            )
    summaries.sort(key=lambda item: float(item["score"]), reverse=True)
    return summaries[: max(0, topk)]


def main() -> None:
    args = parse_args()

    image_path = args.image_path.expanduser().resolve()
    engine_path = resolve_engine_path(args.engine_path)
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else image_path.parent
    )

    ensure_exists(image_path, "Input image")
    output_dir.mkdir(parents=True, exist_ok=True)

    image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise RuntimeError(f"Failed to read image: {image_path}")

    tokenizer = create_tokenizer()
    text_inputs, positive_map, class_ids, normalized_prompt = tokenize_prompt(tokenizer, args.prompt)

    trt_module, _logger, _runtime, engine = create_engine(
        engine_path, plugin_library=args.plugin_library
    )

    network_width, network_height = infer_network_size_from_engine(
        engine,
        fallback_width=args.network_width,
        fallback_height=args.network_height,
    )

    image_tensor, processed_canvas_bgr, transform_info = preprocess_image(
        image_bgr,
        network_width=network_width,
        network_height=network_height,
    )

    pred_logits, pred_boxes, input_names, output_names = run_inference(
        engine,
        trt_module,
        image_tensor,
        text_inputs,
    )

    label_scores = decode_scores(pred_logits, positive_map)

    boxes_network_xyxy = convert_boxes_to_network(pred_boxes, transform_info)
    boxes_original_xyxy = convert_network_boxes_to_original(boxes_network_xyxy, transform_info)

    top_score_debug = summarize_top_scores(
        label_scores,
        class_ids,
        boxes_original_xyxy,
        args.debug_topk,
    )

    detections: list[dict] = []
    if label_scores.size and class_ids:
        for query_idx in range(label_scores.shape[0]):
            for label_idx, label in enumerate(class_ids):
                score = float(label_scores[query_idx, label_idx])
                if score <= args.box_threshold:
                    continue

                box_net = boxes_network_xyxy[query_idx]
                box_org = boxes_original_xyxy[query_idx]

                detections.append(
                    {
                        "query_idx": query_idx,
                        "label_idx": label_idx,
                        "label": label,
                        "score": score,
                        "network_x1": float(box_net[0]),
                        "network_y1": float(box_net[1]),
                        "network_x2": float(box_net[2]),
                        "network_y2": float(box_net[3]),
                        "original_x1": float(box_org[0]),
                        "original_y1": float(box_org[1]),
                        "original_x2": float(box_org[2]),
                        "original_y2": float(box_org[3]),
                    }
                )

    detections.sort(key=lambda item: float(item["score"]), reverse=True)

    processed_annotated = draw_detections(
        processed_canvas_bgr,
        detections,
        coord_prefix="network",
    )
    original_annotated = draw_detections(
        image_bgr,
        detections,
        coord_prefix="original",
    )

    processed_path = output_dir / f"{image_path.stem}_grounding_dino_processed.jpg"
    original_path = output_dir / f"{image_path.stem}_grounding_dino_original.jpg"

    cv2.imwrite(str(processed_path), processed_annotated)
    cv2.imwrite(str(original_path), original_annotated)

    print(f"Image: {image_path}")
    print(f"Engine: {engine_path}")
    print(f"Prompt: {normalized_prompt}")
    print(f"Network size: {network_width}x{network_height}")
    print(f"Threshold: {args.box_threshold}")
    print(f"Input tensors: {input_names}")
    print(f"Output tensors: {output_names}")
    print(f"Detections: {len(detections)}")

    if top_score_debug:
        print(f"Top {len(top_score_debug)} query-label scores:")
        for idx, item in enumerate(top_score_debug, start=1):
            print(
                f"  {idx}. q={int(item['query_idx'])} label_idx={int(item['label_idx'])} "
                f"label={item['label']} score={float(item['score']):.3f} "
                f"bbox(original)=[{float(item['x1']):.1f}, {float(item['y1']):.1f}, "
                f"{float(item['x2']):.1f}, {float(item['y2']):.1f}]"
            )

    for idx, det in enumerate(detections, start=1):
        print(
            f"{idx}. q={det['query_idx']} label_idx={det['label_idx']} "
            f"{det['label']} score={float(det['score']):.3f} "
            f"bbox(network)=[{float(det['network_x1']):.1f}, {float(det['network_y1']):.1f}, "
            f"{float(det['network_x2']):.1f}, {float(det['network_y2']):.1f}] "
            f"bbox(original)=[{float(det['original_x1']):.1f}, {float(det['original_y1']):.1f}, "
            f"{float(det['original_x2']):.1f}, {float(det['original_y2']):.1f}]"
        )

    print(f"Processed annotated image saved to: {processed_path}")
    print(f"Original annotated image saved to: {original_path}")

    if args.save_csv:
        csv_path = output_dir / f"{image_path.stem}_grounding_dino_trt.csv"
        pd.DataFrame(detections).to_csv(csv_path, index=False)
        print(f"Detection CSV saved to: {csv_path}")


if __name__ == "__main__":
    main()