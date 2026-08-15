#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <model.onnx> [model.plan]"
  exit 1
fi

MODEL_PATH="$(realpath "$1")"
ENGINE_PATH="${2:-${MODEL_PATH%.onnx}.plan}"
TRTEXEC_BIN="${TRTEXEC_BIN:-/usr/src/tensorrt/bin/trtexec}"

if [[ ! -f "${MODEL_PATH}" ]]; then
  echo "ONNX model not found: ${MODEL_PATH}"
  exit 1
fi

"${TRTEXEC_BIN}" \
  --onnx="${MODEL_PATH}" \
  --saveEngine="${ENGINE_PATH}" \
  --fp16 \
  --builderOptimizationLevel=5

echo "TensorRT engine saved to: ${ENGINE_PATH}"
