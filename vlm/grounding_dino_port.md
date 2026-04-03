# Grounding DINO 跨版本移植紀錄 (4.x → JP6/release-3.2)

> **環境：** Jetson AGX Orin / JetPack 6 / Isaac ROS release-3.2 容器
> **日期：** 2026-04-02

## 概要

`isaac_ros_grounding_dino` 是 Isaac ROS **4.x (main)** 新增的 open-vocabulary 物件偵測套件，
原本不支援 JetPack 6 的 `release-3.2` 環境。本文件記錄跨版本移植的所有修補。

## 移植路徑

```
src/isaac_ros_grounding_dino_port/    ← 從 main 分支 sparse-checkout
├── isaac_ros_grounding_dino          ← 主套件 (已修補)
├── isaac_ros_grounding_dino_interfaces  ← srv 定義 (無需修改)
└── isaac_ros_grounding_dino_models_install  ← 模型下載腳本
```

## 修補清單

### 1. package.xml — 移除不相容依賴

```diff
-  <depend>isaac_ros_nitros_bridge_interfaces</depend>
-  <depend>isaac_ros_grounding_dino_models_install</depend>
-  <exec_depend>python3-transformers-pip-shim</exec_depend>
```

| 被移除的依賴 | 原因 |
|---|---|
| `isaac_ros_nitros_bridge_interfaces` | 4.x 才有，**原始碼完全沒用到** |
| `isaac_ros_grounding_dino_models_install` | 模型下載腳本，不影響編譯 |
| `python3-transformers-pip-shim` | JP6 沒有此 shim，改為手動 `pip3 install transformers` |

### 2. CMakeLists.txt — CUDA nvtx3 連結修復

原始 CMake 使用全局 `link_libraries("CUDA::nvtx3")`，在 3.2 環境下 ament_cmake_auto 無法正確解析。

**修補方案：** 移除 NVTX、將 `find_package(CUDAToolkit)` 移到 `ament_auto_find_build_dependencies()` 之前，改用 `CUDA::cudart`。

### 3. cuda_stream.hpp — 相容性 Shim

4.x 新增的 `isaac_ros_common/cuda_stream.hpp` 在 3.2 不存在。

**修補方案：** 建立 inline shim 到 install 目錄：
```
/workspaces/isaac_ros-dev/install/isaac_ros_common/include/isaac_ros_common/cuda_stream.hpp
```

提供：
- `CHECK_CUDA_ERROR` macro
- `initNamedCudaStream()` → 封裝 `cudaStreamCreate()`
- `nameExistingCudaStream()` → no-op

### 4. ROS 2 Humble API 修補

`create_client()` 和 `create_service()` 在 Humble 版的 QoS 參數型別不同：

```diff
- rclcpp::ServicesQoS()     // ROS 2 Jazzy+ (4.x)
+ rmw_qos_profile_services_default  // ROS 2 Humble (3.2)
```

修補檔案：
- `grounding_dino_preprocessor_node.cpp`
- `grounding_dino_decoder_node.cpp`

## 使用方式

```bash
# 進入 vlm 容器
make join  # 選擇 vlm

# Source 環境
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash

# 確認安裝
ros2 pkg list | grep grounding
# isaac_ros_grounding_dino
# isaac_ros_grounding_dino_interfaces

# 需要先手動安裝 transformers
pip3 install transformers
```

## ⚠️ 注意事項

1. **容器重建時**需重新安裝 `cuda_stream.hpp` shim（已加進 Dockerfile 自動化）。
2. **NVTX profiling** 已因編譯相容性停用，但不影響任何推論功能。

## ✅ 關鍵底層相容性修補 (已解決)

### 1. VPI_ERROR_DEVICE (12) 與 EGL Headless 問題
**症狀：** JP6/3.2 中，`isaac_ros_image_proc` 裡的 ResizeNode 在容器內初始化 TensorStream 失敗，拋出 VPI 無法取得硬體資源（無法存取 VIC）。
**解法：** 
- 指派 CDI 檔案：建立 `/etc/cdi/nvidia.yaml` 將 `/dev/nvhost-vic`、`/dev/nvhost-msenc` 等 Tegra 設備節點 map 進入容器。
- 設置 Headless EGL：於 `docker-compose.yaml` 中注入 `EGL_PLATFORM=device`。

### 2. TensorRT kBOOL DataType 解析錯誤
**症狀：** Grounding DINO 模型包含 `attention_mask` (Boolean 型)。但在 `gxf_isaac_tensor_rt` 中，尚未支援 `nvinfer1::DataType::kBOOL` 映射。
**解法：** 
修改 `/workspaces/isaac_ros-dev/src/isaac_ros_dnn_inference/isaac_ros_gxf_extensions/gxf_isaac_tensor_rt/gxf/extensions/tensor_rt/tensor_rt_inference.cpp`：
支援 `kBOOL` 並映射為 `kUnsigned8`，解決 Unsupported DataType 崩潰。

---

## 🚀 測試與執行指南

此版本支援雙模式推論驗證：

### 模式 A：影片回放測試 (MP4 Player)

不依賴實體相機，直接將準備好的 `.mp4` 影片推流到 DINO 管線進行推論驗證。
開啟兩個終端機並運行：

**Terminal 1 (啟動 Grounding DINO)**
```bash
source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash
ros2 launch isaac_ros_grounding_dino isaac_ros_grounding_dino.launch.py \
   model_file_path:=/workspaces/isaac_ros-dev/isaac_ros_assets/models/grounding_dino/grounding_dino_model.onnx \
   engine_file_path:=/workspaces/isaac_ros-dev/isaac_ros_assets/models/grounding_dino/grounding_dino_model.plan \
   text_prompt:="a man. a cat."
```

**Terminal 2 (啟動影片播放器)**
```bash
source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash
python3 /workspaces/isaac_ros-dev/src/vlm_mp4_player.py --ros-args -p video:=/workspaces/isaac_ros-dev/test_man_cat.mp4
```

### 模式 B：RealSense D455 實機測試

使用實體相機的 `/camera/camera/color/image_raw` 作為輸入：

**Terminal 1 (啟動 Grounding DINO)**
```bash
# ...同模式A，請自行更改 text_prompt
```

**Terminal 2 (啟動 RealSense)**
```bash
source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash
ros2 launch realsense2_camera rs_launch.py \
   enable_color:=true \
   enable_depth:=false \
   rgb_camera.profile:=640x480x30
```

> **提示：** 可以在 Foxglove 中訂閱 `/image_rect_out` 主題，即可即時觀看已上好 bbox 的合成影像。
