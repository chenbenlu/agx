### Apr 13 add 4 files: landmark_logic.py, landmark_step_evaluator_node.py, route_planner_node.py, route_planning.py

### modified json_utils, prompting.py, reasoner_node, schemass, state_machine, topics

## Verified
```bash
python3 -m compileall -q /home/syslabros/agx/cosmos/VLA /home/syslabros/agx/vlm/landmark_locator_node.py /home/syslabros/agx/vlm/bbox_visualizer.py

PYTHONPATH=/home/syslabros/agx/cosmos/VLA python3 -m unittest discover -s /home/syslabros/agx/cosmos/VLA/test
```

### 可直接這樣接：
cosmos: 
`python3 -m vla_demo.route_planner_node --ros-args -p backend_mode:=cosmos_cli`
vlm: 
`python3 /opt/vlm_tools/landmark_locator_node.py`
vlm: 
`python3 /opt/vlm_tools/bbox_visualizer.py`
任一有 /opt/vla_demo 的 container: 
`python3 -m vla_demo.landmark_step_evaluator_node`

### 1.在 cosmos 啟動 Cosmos vLLM server
```bash
make join c=cosmos
source /opt/ros/humble/setup.bash
source /workspaces/cosmos_ws/.venv/bin/activate

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HOME=/data/cosmos_cache/hf
export HF_HUB_CACHE=/data/cosmos_cache/hf/hub
export VLLM_CACHE_ROOT=/data/cosmos_cache/vllm

vllm serve /data/models/Cosmos-Reason2-2B \
  --allowed-local-media-path "/" \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.6 \
  --reasoning-parser qwen3 \
  --port 8000 \
  --download-dir /data/cosmos_cache/vllm/

```
### 2. 在 nanollm 跑 route planner
```bash
docker exec -it nanollm bash

if [ -f /opt/ros/install/setup.bash ]; then
  source /opt/ros/install/setup.bash
else
  source /opt/ros/humble/setup.bash
fi

export PYTHONPATH=/opt/vla_demo:$PYTHONPATH

python3 -m vla_demo.route_planner_node --ros-args \
  -p backend_mode:=cosmos_cli \
  -p host:=localhost \
  -p port:=8000

```
### 3. 在 nanollm 啟動 mission manager
```bash
make join c=nanollm
if [ -f /opt/ros/install/setup.bash ]; then
  source /opt/ros/install/setup.bash
else
  source /opt/ros/humble/setup.bash
fi
export PYTHONPATH=/opt/vla_demo:$PYTHONPATH
python3 -m vla_demo.mission_manager
```

### 4. 在 nanollm 再開一個 shell 啟動 landmark evaluator
```bash
make join c=nanollm
if [ -f /opt/ros/install/setup.bash ]; then
  source /opt/ros/install/setup.bash
else
  source /opt/ros/humble/setup.bash
fi
export PYTHONPATH=/opt/vla_demo:$PYTHONPATH

python3 -m vla_demo.landmark_step_evaluator_node
```
### 5. 在 vlm 啟動 Grounding DINO
```bash
make join c=vlm
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
export PYTHONPATH=/opt/vla_demo:$PYTHONPATH

ros2 launch isaac_ros_grounding_dino isaac_ros_grounding_dino.launch.py \
  model_file_path:=/workspaces/isaac_ros-dev/isaac_ros_assets/models/grounding_dino/grounding_dino_model.onnx \
  engine_file_path:=/workspaces/isaac_ros-dev/isaac_ros_assets/models/grounding_dino/grounding_dino_model.plan \
  input_image_width:=640 \
  input_image_height:=480
```
### 6. 在 vlm 再開兩個 shell，分別啟動 locator 和視覺化
```bash
make join c=vlm
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
export PYTHONPATH=/opt/vla_demo:$PYTHONPATH
python3 /opt/vlm_tools/landmark_locator_node.py
```
```bash
make join c=vlm
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
python3 /opt/vlm_tools/bbox_visualizer.py
```
### 送任務
- mp4 模式：
```bash
ros2 topic pub --once /vla/route_request std_msgs/msg/String \
"{data: '{\"mission_id\":\"route_mp4_demo\",\"goal_text\":\"前往貨梯區域\",\"environment_id\":\"hallway_9f\",\"source_mode\":\"video_file\",\"video_uri\":\"file:///workspaces/cosmos_ws/video/sec_fly.mp4\",\"camera_source\":\"/camera/camera/color/image_raw\",\"clip_duration_sec\":3.0,\"inference_interval_sec\":1.5}'}"
```
- live camera 模式：
```bash
ros2 topic pub --once /vla/route_request std_msgs/msg/String \
"{data: '{\"mission_id\":\"route_live_demo\",\"goal_text\":\"前往貨梯區域\",\"environment_id\":\"hallway_9f\",\"source_mode\":\"live_camera\",\"camera_source\":\"/camera/camera/color/image_raw\",\"clip_duration_sec\":3.0,\"inference_interval_sec\":1.5}'}"
```
### 如果是 live camera，再補相機
- D455:
```bash
make join c=vlm
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
ros2 launch realsense2_camera rs_launch.py \
  enable_color:=true \
  enable_depth:=false \
  rgb_camera.profile:=640x480x30
```
### 常用監看
```bash
ros2 topic echo /vla/route_plan
ros2 topic echo /vla/current_step
ros2 topic echo /vla/landmark_detection
ros2 topic echo /vla/inference_result
ros2 topic echo /vla/mission_state
ros2 topic echo /detections_output

```
### webui
```bash
docker exec -it nanollm bash
cd /data/webui_system
uvicorn backend.app:app --host 0.0.0.0 --port 8089
```