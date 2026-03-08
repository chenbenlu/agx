#!/bin/bash
# ros1_bridge entrypoint: 同時設定 noetic + foxy 環境

# 保存 compose 傳入的環境變數（source setup.bash 會覆蓋掉）
SAVED_ROS_MASTER_URI="$ROS_MASTER_URI"
SAVED_ROS_HOSTNAME="$ROS_HOSTNAME"

# 先設定 ROS 1 (noetic)
source /opt/ros/noetic/setup.bash

# 疊加 ROS 2 (foxy) 的路徑
export LD_LIBRARY_PATH="/opt/ros/foxy/lib:$LD_LIBRARY_PATH"
export PYTHONPATH="/opt/ros/foxy/lib/python3.8/site-packages:$PYTHONPATH"
export PATH="/opt/ros/foxy/bin:$PATH"
export AMENT_PREFIX_PATH="/opt/ros/foxy"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE=/fastdds.xml

# 還原 compose 傳入的環境變數
export ROS_MASTER_URI="$SAVED_ROS_MASTER_URI"
export ROS_HOSTNAME="$SAVED_ROS_HOSTNAME"

echo "[bridge] Waiting for roscore at $ROS_MASTER_URI ..."
# 由於 Foxy 和 Noetic 混用 PYTHONPATH 會導致 rostopic list 報錯，改用簡單延遲或交給 ros1_bridge 自行檢查
sleep 3

echo "[bridge] roscore is up! Starting ros1_bridge ..."

exec ros2 run ros1_bridge dynamic_bridge --bridge-all-1to2-topics --bridge-all-2to1-topics
