# Grounding DINO 測試指令

## 啟動 Grounding DINO pipeline
```bash
ros2 launch isaac_ros_grounding_dino isaac_ros_grounding_dino.launch.py \
	model_file_path:=/workspaces/isaac_ros-dev/isaac_ros_assets/models/grounding_dino/grounding_dino_model.onnx \
	engine_file_path:=/workspaces/isaac_ros-dev/isaac_ros_assets/models/grounding_dino/grounding_dino_model.plan \
	input_image_width:=1280 \
	input_image_height:=720
```

## 發佈單張測試影像
```bash
python3 /opt/vlm_tools/grounding_test/src/benchmark_tools/benchmark_media_publisher.py \
	--image /opt/vlm_tools/grounding_test/src/demo.png \
	--image-topic /camera/camera/color/image_raw \
	--camera-info-topic /camera/camera/color/camera_info \
	--image-rate 15.0
```

## 發佈測試影片
```bash
python3 /workspaces/isaac_ros-dev/src/vlm_mp4_player.py --ros-args \
	-p video:=/opt/vlm_tools/grounding_test/src/raw_frame_1s.mp4
```

## 更新文字提示詞
```bash
ros2 service call /set_prompt isaac_ros_grounding_dino_interfaces/srv/SetPrompt \
	"{prompt: 'umbrellas.'}"
```

## 顯示偵測結果
```bash
python3 /workspaces/isaac_ros-dev/src/bbox_visualizer.py
```