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
"{data: '{\"mission_id\":\"route_live_demo\",\"goal_text\":\"離開室內區域\",\"environment_id\":\"hallway_9f\",\"source_mode\":\"live_camera\",\"camera_source\":\"/camera/camera/color/image_raw\",\"clip_duration_sec\":3.0,\"inference_interval_sec\":1.5}'}"
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
rgb_camera.profile:=1280x720x30
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
要看當下 buffer，可以用這幾種方式：
在 webui 直接看
右側現在有 Live Buffer 預覽 卡片。
只要送 live_camera route request，buffer 一準備好就會顯示最新 clip。
訂閱 ROS topic 看 metadata
`ros2 topic echo /vla/route_buffer_status`

會看到像這些欄位：
- status
- media_type
- frame_count
- fps
- local_path
- file_uri
- 直接打 backend API
- 先啟 webui backend：
```bash
docker exec -it nanollm bash
cd /data/webui_system
uvicorn backend.app:app --host 0.0.0.0 --port 8089
```
查狀態：
`curl http://127.0.0.1:8089/api/route_buffer/status`

直接拿最新 buffer 檔：
`curl -O http://127.0.0.1:8089/api/route_buffer/latest`
在 container 內直接看檔案
route_planner_node 現在會把最新 live buffer 留在：
/workspaces/vla_route_media/latest_live_buffer.mp4
或 /workspaces/vla_route_media/latest_live_buffer.jpg

可先看：
`ls -lh /workspaces/vla_route_media`

要套用這次變更，你至少要重啟這兩個 process：
```bash
docker exec -it nanollm bash
if [ -f /opt/ros/install/setup.bash ]; then
  source /opt/ros/install/setup.bash
else
  source /opt/ros/humble/setup.bash
fi
export PYTHONPATH=/opt/vla_demo:$PYTHONPATH
python3 -m vla_demo.route_planner_node --ros-args -p backend_mode:=cosmos_cli -p host:=localhost -p port:=8000

docker exec -it nanollm bash
cd /data/webui_system
uvicorn backend.app:app --host 0.0.0.0 --port 8089
```

#### 目前策略:
#### nanollm 不直接呼叫 /set_prompt
#### nanollm 只發布一般 ROS topic，例如 /vla/current_step
#### vlm 裡的 landmark_locator_node.py (line 58) 訂閱 /vla/current_step
#### 然後由 vlm 本地去呼叫 isaac_ros_grounding_dino_interfaces/srv/SetPrompt：
#### landmark_locator_node.py (line 50) 到 landmark_locator_node.py (line 99)
#### 所以架構上是：
#### nanollm：任務/mission orchestration
#### vlm：Isaac ROS / Grounding DINO 相依、/set_prompt service client


#### [ERROR] [vla_route_planner]: Route planning failed: No buffered frames available on /camera/camera/color/image_raw for live route planning, 使用live會出現這樣的錯誤
把 route_planner_node.py 改成：
用 qos_profile_sensor_data 訂閱 /camera/camera/color/image_raw
補上 frames_received / buffer_size / last_frame_stamp /

