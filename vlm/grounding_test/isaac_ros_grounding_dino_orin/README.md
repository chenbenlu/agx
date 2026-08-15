# isaac_ros_grounding_dino_orin

這個套件把目前資料夾裡的開源 `GroundingDINO` 程式碼，整理成一個比較適合 `Jetson AGX Orin + ROS 2 / Isaac ROS` 流程使用的版本。

## 為什麼要另外做這個版本

- 你目前的專案只有 notebook / Python 推論流程，還沒有 ROS 2 package。
- NVIDIA 官方 `isaac_ros_grounding_dino` 已經存在，但它是在 2025-10-24 之後加入 `isaac_ros_object_detection` 主線，官方最新文件也改以 Thor / ROS 2 Jazzy 為主。
- AGX Orin 常見的 Isaac ROS 部署仍多落在 `release-3.1` 這類 JetPack 6.0 / ROS 2 Humble 工作流，因此直接用這份 repo 做一個能在 Orin 上先跑起來的 ROS 2 版會比較穩。

## 這個套件提供什麼

1. `grounding_dino_orin_node`
   - 訂閱 `image_rect`
   - 執行 GroundingDINO 推論
   - 發布 `vision_msgs/Detection2DArray` 到 `detections_output`
   - 可選擇發布 `annotated_image`

2. `export_grounding_dino_isaac_onnx`
   - 把開源 `GroundingDINO_SwinT_OGC` 權重包成 Isaac ROS 風格的 6-input ONNX 介面
   - 輸出 binding 名稱對齊官方 Grounding DINO TensorRT launch 習慣：
     - inputs
     - input_ids
     - attention_mask
     - position_ids
     - token_type_ids
     - text_token_mask
   - outputs:
     - pred_logits
     - pred_boxes

3. `scripts/build_trt_engine.sh`
   - 在 AGX Orin 上用 `trtexec` 把 ONNX 轉成 `.plan`

## 目錄假設

這個 package 預設假設你的資料夾長這樣：

- `GroundingDINO/`
- `weights/groundingdino_swint_ogc.pth`
- `isaac_ros_grounding_dino_orin/`

如果你的路徑不同，可以在 launch 時覆蓋：

- `grounding_dino_repo_path`
- `config_path`
- `weights_path`

## 在 AGX Orin 上安裝依賴

至少需要：

- ROS 2 Humble
- `cv_bridge`
- `vision_msgs`
- `torch`
- `torchvision`
- `transformers`
- `timm`
- `addict`
- `yapf`
- `opencv-python`

`GroundingDINO/requirements.txt` 已經列出大部分 Python 依賴。

## 建置

假設你把這個 repo 放在 Isaac ROS workspace 底下：

```bash
cd ${ISAAC_ROS_WS}
colcon build --packages-select isaac_ros_grounding_dino_orin
source install/setup.bash
```

## 啟動

```bash
ros2 launch isaac_ros_grounding_dino_orin grounding_dino_orin.launch.py \
  prompt:="black bicycle. grey umbrella." \
  box_threshold:=0.35 \
  text_threshold:=0.25 \
  use_fp16:=true
```

預設 remap:

- input: `image_rect`
- output: `detections_output`
- output: `annotated_image`

你可以直接 remap 到 Isaac ROS camera pipeline 的 rectified image topic。

## 動態改 prompt

這個版本先用 ROS parameter 做動態更新：

```bash
ros2 param set /grounding_dino_orin_node prompt "person. traffic cone. pallet."
```

## 單張圖片測試

如果你只是要做單張圖片偵測測試，不想接 live topic，可以直接跑：

```bash
ros2 run isaac_ros_grounding_dino_orin detect_grounding_dino_image \
  --image-path /home/syslabros/Documents/grounding/data/demo.png \
  --prompt "white umbrella. light blue umbrella. dark blue umbrella. folded umbrella." \
  --use-fp16 \
  --save-csv
```

這個指令會：

- 直接讀取圖片檔
- 跑 GroundingDINO 推論
- 在終端機列出偵測結果
- 輸出標註圖：`demo_grounding_dino.jpg`
- 可選擇輸出 CSV：`demo_grounding_dino.csv`

如果不想經過 `ros2 run`，也可以在 package source 目錄直接執行對應的 Python 入口。

## 匯出 Isaac ROS 風格 ONNX

注意：

- 這一步需要 `onnx` Python 套件
- 也需要你的 GroundingDINO 環境已經能正常 import `torchvision` 與自訂 op
- 這條路徑是為了後續接近官方 `isaac_ros_grounding_dino + TensorRTNode` 的模型介面

```bash
ros2 run isaac_ros_grounding_dino_orin export_grounding_dino_isaac_onnx \
  --weights-path /path/to/groundingdino_swint_ogc.pth \
  --output-path /path/to/grounding_dino_swint_ogc_isaac.onnx \
  --width 960 \
  --height 544
```

## 在 AGX Orin 上建立 TensorRT engine

```bash
${ISAAC_ROS_WS}/src/grounding/isaac_ros_grounding_dino_orin/scripts/build_trt_engine.sh \
  /path/to/grounding_dino_swint_ogc_isaac.onnx \
  /path/to/grounding_dino_swint_ogc_isaac.plan
```

## 已知限制

- 目前 ROS node 走的是 PyTorch 推論，不是 NITROS / TensorRT graph。
- ONNX 匯出腳本是為了和 Isaac ROS 官方 Grounding DINO 介面對齊，但我還沒有在這台機器上完成實際 export 驗證，因為目前本機缺少 `torchvision` 與 `onnx` 完整環境。
- 如果你要追求 Orin 上更高 FPS，下一步建議是在 AGX Orin 目標機上完成 ONNX 匯出與 TensorRT engine 生成，然後再接 `isaac_ros_tensor_rt`。

## demo.png benchmark

如果你要重跑 notebook 那套 `demo.png` benchmark，不用再手動開 notebook，直接跑 repo 根目錄的 [run_demo_benchmark.py](/home/syslabros/Documents/grounding/run_demo_benchmark.py:1)：

```bash
cd /home/syslabros/Documents/grounding
python3 run_demo_benchmark.py
```

預設會讀：

- `data/demo.png`
- `yolov8n.pt`
- `GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py`
- `weights/groundingdino_swint_ogc.pth`

並輸出和 notebook 相同類型的檔案：

- `ground_truth_boxes.csv`
- `yolo_predictions.csv`
- `grounding_dino_predictions.csv`
- `strict_colored_benchmark_summary.csv`
- `proposal_colored_benchmark_summary.csv`
- `object_only_benchmark_summary.csv`
- `yolo_predictions.png`
- `grounding_dino_predictions.png`
- `yolo_gt_vs_pred.png`
- `gdino_gt_vs_pred.png`
