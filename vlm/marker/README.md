# Grounding DINO Semantic Map Marker

This folder contains a standalone ROS 2 marker pipeline for showing Grounding DINO
detections on the Nav2 2D map. It does not depend on the VLA mission manager,
`/vla/current_step`, or `/vla/landmark_detection`.

## Flow

```text
Cosmos-Reason2 manual task text
  -> operator calls Grounding DINO /set_prompt
  -> Grounding DINO publishes /detections_output
  -> semantic_map_marker_node reads AMR pose from TF or /amcl_pose
  -> /semantic_map/markers appears on /map in Foxglove/RViz
```

The marker position is the AMR pose at detection time. This first version does
not estimate the object world position from camera depth.

## Manual Prompt

Single class:

```bash
ros2 service call /set_prompt isaac_ros_grounding_dino_interfaces/srv/SetPrompt \
"{prompt: 'black bicycle.'}"
```

Multiple classes:

```bash
ros2 service call /set_prompt isaac_ros_grounding_dino_interfaces/srv/SetPrompt \
"{prompt: 'black bicycle. person. chair. door.'}"
```

### RUN THIS 0430:
```bash
ros2 service call /set_prompt isaac_ros_grounding_dino_interfaces/srv/SetPrompt   "{prompt: 'black bicycle. grey umbrella.'}"
```
Each detected `class_id` gets a stable marker color.

## Run

Inside the `vlm` container:

```bash
make join c=vlm
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash

python3 /opt/vlm_marker/semantic_map_marker_node.py --ros-args   -p score_threshold:=0.65   -p map_frame:=map   -p base_frame:=base_footprint -p mark_once_per_class:=true
```

To mark only one class:

```bash
python3 /opt/vlm_marker/semantic_map_marker_node.py --ros-args \
  -p target_filter:="black bicycle" \
  -p score_threshold:=0.75
```

## Topics

Inputs:

- `/detections_output` (`vision_msgs/msg/Detection2DArray`)
- `/tf`, `/tf_static`
- `/amcl_pose` (`geometry_msgs/msg/PoseWithCovarianceStamped`) as fallback

Outputs:

- `/semantic_map/markers` (`visualization_msgs/msg/MarkerArray`)
- `/semantic_map/observation` (`std_msgs/msg/String` JSON)

## Parameters

- `detections_topic`: default `/detections_output`
- `markers_topic`: default `/semantic_map/markers`
- `observation_topic`: default `/semantic_map/observation`
- `target_filter`: default empty, which marks all classes
- `score_threshold`: default `0.75`
- `map_frame`: default `map`
- `base_frame`: default `base_footprint`
- `use_tf_first`: default `true`
- `mark_once_per_class`: default `true`, so each label is marked only the first time
- `min_distance_m`: default `0.5`
- `cooldown_sec`: default `2.0`
- `marker_lifetime_sec`: default `0.0`, meaning permanent

With the default `mark_once_per_class=true`, Grounding DINO and bbox drawing can
continue running every frame, but the map receives only the first marker for each
canonical `class_id`. Set it to `false` if you later want repeated semantic
observations along the route.

## Foxglove / RViz

Add these displays:

- Map: `/map`
- TF: `/tf`
- MarkerArray: `/semantic_map/markers`

Useful checks:

```bash
ros2 topic echo /detections_output
ros2 run tf2_ros tf2_echo map base_footprint
ros2 topic echo /amcl_pose
ros2 topic echo /semantic_map/observation
ros2 topic echo /semantic_map/markers
```
### grounding dino
```bash 
ros2 launch isaac_ros_grounding_dino isaac_ros_grounding_dino.launch.py    model_file_path:=/workspaces/isaac_ros-dev/isaac_ros_assets/models/grounding_dino/grounding_dino_model.onnx    engine_file_path:=/workspaces/isaac_ros-dev/isaac_ros_assets/models/grounding_dino/grounding_dino_model.plan    input_image_width:=640    input_image_height:=480
```

### bbox
```bash
 python3 /workspaces/isaac_ros-dev/src/bbox_visualizer.py
```