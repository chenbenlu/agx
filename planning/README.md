# Planning — AGX 自主導航系統

## 系統架構

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Launch 架構                                  │
│                                                                     │
│  實體機器人                           Isaac Sim 模擬                  │
│  ─────────                           ──────────────                  │
│  car_sensor.launch.py                car_sensor_sim.launch.py       │
│    └── car_core.launch.py              └── car_core.launch.py       │
│        (use_sim_time=false)                (use_sim_time=true)       │
│        ├── robot_state_publisher          ├── robot_state_publisher  │
│        ├── ekf_node (ekf.yaml)           └── ekf_node (ekf_sim.yaml)│
│        ├── urg_node2 (LiDAR)                                        │
│        ├── serial_bridge_node                                       │
│        └── kinematics_node                                          │
│                                                                     │
│  nav2_bringup.launch.py              nav2_bringup_sim.launch.py     │
│    (use_sim_time=false)                (use_sim_time=true, 固定)      │
│    ├── nav2_params.yaml                ├── nav2_params_sim.yaml     │
│    ├── Nav2 全節點                      ├── Nav2 全節點               │
│    └── foxglove_pose_republisher       └── foxglove_pose_republisher│
└─────────────────────────────────────────────────────────────────────┘
```

### TF Tree

```
map → odom → base_footprint → base_link → {laser, camera_link}
 │      │           │
 │      │           └── Isaac Sim OmniGraph (sim) / EKF (real)
 │      └── AMCL (tf_broadcast: true)
 └── robot_state_publisher (URDF 靜態 TF)
```

### Velocity Chain (Nav2)

```
controller_server → /cmd_vel_nav → velocity_smoother → /cmd_vel → Isaac Sim / 實車
```

### 參數檔差異 (sim vs real)

| 參數 | `nav2_params.yaml` (實車) | `nav2_params_sim.yaml` (模擬) |
|---|---|---|
| `use_sim_time` | `False` | `True` |
| Controller | `RotationShimController` + RPP | RPP 直接（無 RotationShim） |
| `desired_linear_vel` | 0.6 m/s | 1.2 m/s |
| `max_angular_vel` | 1.2 rad/s | 2.0 rad/s |
| `use_regulated_linear_velocity_scaling` | true | false |
| `use_rotate_to_heading` | true | false |
| `velocity_smoother max_velocity` | [0.8, 0.0, 1.5] | [1.5, 0.0, 2.5] |

> **注意**：模擬環境關閉 `RotationShim` 與 `rotate_to_heading` 是因為 Isaac Sim 的地面摩擦
> 讓低角速度原地旋轉無法生效。實車上這些功能正常運作。

---

## Quick Start

### 實體機器人

#### 1. 網路設定（主機端，LiDAR 用）
```bash
if [ "$ARCH" = "aarch64" ]; then
    # [AGX 端]
    echo "Configuring Network for AGX (eno1)..."
    if ip link show eno1 > /dev/null 2>&1; then
        ip addr add 192.168.1.100/24 dev eno1 || echo "IP 192.168.1.100 may already be assigned to eno1."
        ip link set eno1 up
    else
        echo "WARNING: Interface eno1 not found!"
    fi

elif [ "$ARCH" = "x86_64" ]; then
    # [PC 端]
    echo "Configuring Network for PC (eno1)..."
    if ip link show eno1 > /dev/null 2>&1; then
        sudo ip addr add 192.168.1.100/24 dev eno1 || echo "IP 192.168.1.100 may already be assigned to eno1."
        sudo ip link set eno1 up
    else
        echo "WARNING: Interface eno1 not found!"
    fi
fi
```

#### 2. 啟動底盤 + 感測器
```bash
ros2 launch car_control car_sensor.launch.py
```

#### 3. 鍵盤遙控（測試用）
```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

#### 4. SLAM 建圖
```bash
ros2 launch car_control slam_bringup.launch.py
# 遙控走一圈後存檔
ros2 run nav2_map_server map_saver_cli -f /root/ros2_ws/src/car_control/config/my_map
```

#### 5. Nav2 導航
```bash
ros2 launch car_control nav2_bringup.launch.py \
map:=/abs/path/other.yaml\
params_file:=/abs/path/override.yaml

```

---

### Isaac Sim 模擬環境

#### 1. Isaac Sim 載入場景
載入 `amr_nav.usd`，按 **Play**。
Isaac Sim 會發布：`/clock` (60Hz)、`/scan`、`/odom`、`odom→base_footprint` TF，並訂閱 `/cmd_vel`。

#### 2. 啟動 car_sensor (sim)
```bash
ros2 launch car_control car_sensor_sim.launch.py
```

#### 3. SLAM 建圖（可選）
```bash
ros2 launch car_control slam_bringup.launch.py use_sim_time:=true
# 遙控走一圈後存檔
ros2 run nav2_map_server map_saver_cli -f /root/ros2_ws/src/car_control/config/sim_map
```

#### 4. Nav2 導航
```bash
ros2 launch car_control nav2_bringup_sim.launch.py
```

#### 5. 設定初始位姿
透過 RViz **2D Pose Estimate** 或指令：
```bash
ros2 topic pub -1 /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: map},
    pose: {pose: {position: {x: 0.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}},
           covariance: [0.25,0,0,0,0,0, 0,0.25,0,0,0,0, 0,0,0,0,0,0,
                        0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0.068]}}'
```

#### 6. 下目標點
透過 RViz **Nav2 Goal** 或 action：
```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map},
           pose: {position: {x: 1.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}}"
```

---

## Foxglove 整合

Nav2 launch 會一併啟動 `foxglove_pose_republisher`，訂閱 `/initialpose_fox` 與 `/goal_pose_fox`，把 `header.stamp` 改為當下 clock 再轉發到 `/initialpose` 與 `/goal_pose`。
在 Foxglove 3D panel 把 click-to-publish 目標設成 `_fox` topic，就能用拖拉設定 AMCL 初始位姿與 Nav2 目標。

---

## RealSense D455 (IMU + RGB)
```bash
ros2 launch realsense2_camera rs_launch.py \
  enable_gyro:=true \
  enable_accel:=true \
  unite_imu_method:=2 \
  enable_sync:=true
```

## EKF 感測器融合
融合 `/raw_odom`（輪式里程計）與 `/camera/camera/imu`（IMU Yaw 角速度），輸出 `/odometry/filtered` 並發布 `odom → base_footprint` TF：
```bash
ros2 launch car_control ekf.launch.py
```

---

## 診斷工具

### use_sim_time 診斷腳本
確認所有節點的 `use_sim_time` 參數與 TF 時間戳是否對齊：
```bash
bash /root/ros2_ws/install/car_control/lib/car_control/diagnose_sim_time.sh
```

### 殺 Nav2 所有進程
```bash
docker exec planning bash -lc '
  pkill -9 -f "ros2 launch car_control nav2" 2>/dev/null
  pkill -9 -f "component_container_isolated" 2>/dev/null
  pkill -9 -f "nav2_container" 2>/dev/null
  pkill -9 -f "lifecycle_manager" 2>/dev/null
  pkill -9 -f "foxglove_pose_republisher" 2>/dev/null
  pkill -9 -f "map_server" 2>/dev/null
  pkill -9 -f "amcl" 2>/dev/null
  pkill -9 -f "bt_navigator" 2>/dev/null
  pkill -9 -f "controller_server" 2>/dev/null
  sleep 0.5
  pgrep -af "nav2|component_container|foxglove_pose_republisher|lifecycle_manager" || echo CLEAN
'
ps -ef | grep -E "ros2 launch car_control nav2" | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null; echo "host clean"
```

---

## 檔案總覽

```
planning/src/car_control/
├── config/
│   ├── ekf.yaml                # EKF — 實體機 (encoder + IMU)
│   ├── ekf_sim.yaml            # EKF — Isaac Sim (publish_tf=false)
│   ├── nav2_params.yaml        # Nav2 — 實體機 (rotation_shim + RPP)
│   ├── nav2_params_sim.yaml    # Nav2 — Isaac Sim (RPP 直接, 高速)
│   └── sim_map.yaml            # 預設模擬地圖
├── launch/
│   ├── car_core.launch.py      # 共用核心 (rsp + ekf), SetParameter 注入
│   ├── car_sensor.launch.py    # 實體機 = car_core + LiDAR + 車控
│   ├── car_sensor_sim.launch.py # 模擬 = car_core (use_sim_time=true)
│   ├── nav2_bringup.launch.py  # Nav2 啟動 (sim/real 通用, SetParameter 注入)
│   ├── nav2_bringup_sim.launch.py # Nav2 — sim 專用 (固定 use_sim_time=true)
│   ├── slam_bringup.launch.py  # SLAM 啟動
│   └── ekf.launch.py           # 獨立 EKF 測試用
├── scripts/
│   ├── foxglove_pose_republisher.py
│   ├── diagnose_sim_time.sh    # use_sim_time 診斷腳本
│   ├── odom_recorder_node.py
│   └── plot_trajectory.py
├── urdf/
│   └── amr_core.urdf.xacro
└── src/
    ├── serial_bridge_node.cpp
    └── kinematics_node.cpp
```

---

## 接實車前確認清單

- [ ] `nav2_bringup.launch.py` 的 `use_sim_time` 預設值是 `false` ✓
- [ ] `nav2_params.yaml`（實車用）保留 `RotationShimController`、低速設定
- [ ] `car_sensor.launch.py` 未被修改，`use_sim_time=false`
- [ ] `ekf.yaml` 未被修改，`publish_tf: true`
- [ ] 實車啟動指令用 `nav2_bringup.launch.py`（非 `_sim` 版）
- [ ] 確認 LiDAR 連線正常、Serial Port 可用
