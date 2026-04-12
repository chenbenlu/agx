### 2d lidar
主機須先設定ethernet ip:
```bash
if [ "$ARCH" = "aarch64" ]; then
    # [AGX 端]
    echo "Configuring Network for AGX (eno1)..."
    # 檢查 eno1 是否存在，避免報錯
    if ip link show eno1 > /dev/null 2>&1; then
        # 嘗試設定 IP，如果已經存在則忽略錯誤 (|| true)
        ip addr add 192.168.1.100/24 dev eno1 || echo "IP 192.168.1.100 may already be assigned to eno1."
        ip link set eno1 up
    else
        echo "WARNING: Interface eno1 not found!"
    fi

elif [ "$ARCH" = "x86_64" ]; then
    # [PC 端]
    echo "Configuring Network for PC (eno1)..."
    # 檢查 eno1 是否存在
    if ip link show eno1 > /dev/null 2>&1; then
        sudo ip addr add 192.168.1.100/24 dev eno1 || echo "IP 192.168.1.100 may already be assigned to eno1."
        sudo ip link set eno1 up
    else
        echo "WARNING: Interface eno1 not found! Trying to find generic ethernet..."
        # (選用) 如果 PC 不叫 eno1 (例如叫 eno1 或 enp3s0)，可以在這裡加入備用邏輯
    fi
fi
```
### Sensor Bringup (底盤控制 + 雷達)
```bash
ros2 launch car_control car_sensor.launch.py
```
### keyboard control
```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

### save map
```bash
ros2 run nav2_map_server map_saver_cli -f /root/ros2_ws/src/car_control/config/my_map
```

---

### RealSense D455 (IMU + RGB)
啟動相機並開啟 IMU 融合模式（加速度計 + 陀螺儀合併為單一 `/camera/camera/imu` Topic）：
```bash
ros2 launch realsense2_camera rs_launch.py \
  enable_gyro:=true \
  enable_accel:=true \
  unite_imu_method:=2 \
  enable_sync:=true
```

### EKF 感測器融合 (robot_localization)
融合 `/raw_odom`（輪式里程計 X 速度）與 `/camera/camera/imu`（IMU Yaw 角速度），輸出 `/odometry/filtered` 並發布 `odom → base_footprint` TF：
```bash
ros2 launch car_control ekf.launch.py
```

### SLAM 建圖
實車：
```bash
ros2 launch car_control slam_bringup.launch.py
```
Isaac Sim：
```bash
ros2 launch car_control slam_bringup.launch.py use_sim_time:=true
```

### Nav2 導航
Isaac Sim（預設載入 `config/sim_map.yaml`）：
```bash
ros2 launch car_control nav2_bringup.launch.py use_sim_time:=true
```
實車需指定地圖：
```bash
ros2 launch car_control nav2_bringup.launch.py \
  map:=/root/ros2_ws/src/car_control/config/my_map.yaml
```
可選參數：`map:=<path>.yaml`、`params_file:=<path>.yaml`

設定 AMCL 初始位姿（通常透過 RViz 的 **2D Pose Estimate**，也可用指令直接發到 `(0,0,0)`）：
```bash
ros2 topic pub -1 /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: map},
    pose: {pose: {position: {x: 0.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}},
           covariance: [0.25,0,0,0,0,0, 0,0.25,0,0,0,0, 0,0,0,0,0,0,
                        0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0.068]}}'
```

下目標點（通常透過 RViz 的 **Nav2 Goal**，也可用 action 直接送）：
```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map},
           pose: {position: {x: 2.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}}"
```
殺進程
```bash
docker exec planning bash -lc 'pkill -9 -f "ros2 launch car_control nav2"; pkill -9 -f component_container_isolated; pkill -9 -f "nav2_container"' 2>&1; sleep 1 ; kill -9 1223489 1223491 1223515 2>/dev/null; docker exec planning bash -lc 'pgrep -af nav2' 2>&1; echo "---host---"; ps -ef | grep -E "nav2|component_container" | grep -v grep
```

---

### Isaac Sim 完整流程（建圖 → 導航）
1. Isaac Sim 載入 `amr_nav.usd` 按 **Play**（發 `/clock`、`/scan`、`/odom`、`odom→base_footprint` TF，訂閱 `/cmd_vel`）
2. 開 RViz，fixed frame 設 `map`
3. **建圖**：`ros2 launch car_control slam_bringup.launch.py use_sim_time:=true`，用 `teleop_twist_keyboard` 遙控走一圈，完成後 `map_saver_cli` 存檔
4. **導航**：關 slam，改跑 `ros2 launch car_control nav2_bringup.launch.py use_sim_time:=true`，用 **2D Pose Estimate** 給初始位姿，**Nav2 Goal** 下目標點
