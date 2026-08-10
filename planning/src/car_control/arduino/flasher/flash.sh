#!/bin/bash
# 容器 entrypoint：編譯並燒錄 sketch 到 Arduino Mega
# 環境變數：
#   FQBN       - 開發板 FQBN，預設 arduino:avr:mega
#   PORT       - 序列埠，預設 /dev/ttyACM0
#   SKETCH_DIR - sketch 資料夾（資料夾名須與 .ino 檔名相同），預設 /sketch/ros2_com
set -euo pipefail

FQBN="${FQBN:-arduino:avr:mega}"
PORT="${PORT:-/dev/ttyACM0}"
SKETCH_DIR="${SKETCH_DIR:-/sketch/ros2_com}"

echo "[flasher] compiling for ${FQBN} ..."
arduino-cli compile --fqbn "${FQBN}" "${SKETCH_DIR}"

echo "[flasher] uploading to ${PORT} ..."
arduino-cli upload -p "${PORT}" --fqbn "${FQBN}" "${SKETCH_DIR}"

echo "[flasher] done."
