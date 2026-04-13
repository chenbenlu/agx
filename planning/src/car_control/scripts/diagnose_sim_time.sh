#!/bin/bash
# ============================================================
#  diagnose_sim_time.sh — 診斷 use_sim_time 與 TF 時間戳
#
#  Usage:
#      bash diagnose_sim_time.sh
#
#  需要在 Isaac Sim + Nav2 都啟動的環境下執行
# ============================================================

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo " Step 1: 檢查 Nav2 節點 use_sim_time 參數"
echo "============================================"

NAV2_NODES=(
    /amcl
    /controller_server
    /planner_server
    /bt_navigator
    /behavior_server
    /velocity_smoother
    /collision_monitor
    /global_costmap/global_costmap
    /local_costmap/local_costmap
    /map_server
    /waypoint_follower
    /smoother_server
    /lifecycle_manager_navigation
    /lifecycle_manager_localization
)

ALL_OK=true
for n in "${NAV2_NODES[@]}"; do
    printf '%-50s ' "$n"
    result=$(ros2 param get "$n" use_sim_time 2>/dev/null || echo "N/A")
    if echo "$result" | grep -qi "true"; then
        echo -e "${GREEN}True${NC}"
    elif echo "$result" | grep -qi "false"; then
        echo -e "${RED}False ← 問題！${NC}"
        ALL_OK=false
    else
        echo -e "${YELLOW}N/A (節點未啟動或不存在)${NC}"
    fi
done

echo ""
echo "============================================"
echo " Step 2: 檢查 car_core 節點 use_sim_time"
echo "============================================"

CORE_NODES=(/robot_state_publisher /ekf_filter_node)
for n in "${CORE_NODES[@]}"; do
    printf '%-50s ' "$n"
    result=$(ros2 param get "$n" use_sim_time 2>/dev/null || echo "N/A")
    if echo "$result" | grep -qi "true"; then
        echo -e "${GREEN}True${NC}"
    elif echo "$result" | grep -qi "false"; then
        echo -e "${RED}False ← 問題！${NC}"
        ALL_OK=false
    else
        echo -e "${YELLOW}N/A${NC}"
    fi
done

echo ""
echo "============================================"
echo " Step 3: 檢查 /clock 時間"
echo "============================================"

echo "取得 /clock 當前時間..."
ros2 topic echo /clock --once 2>/dev/null || echo -e "${RED}/clock topic 無法讀取${NC}"

echo ""
echo "============================================"
echo " Step 3b: 檢查 TF 時間戳"
echo "============================================"
echo "以下 TF 時間戳應與 /clock 對齊（量級 ~數百秒，而非 ~1.7e9）"
echo ""

echo "--- map → odom ---"
timeout 3 ros2 run tf2_ros tf2_echo map odom 2>/dev/null | head -5 || echo -e "${YELLOW}無法查詢 map→odom TF${NC}"

echo ""
echo "--- odom → base_footprint ---"
timeout 3 ros2 run tf2_ros tf2_echo odom base_footprint 2>/dev/null | head -5 || echo -e "${YELLOW}無法查詢 odom→base_footprint TF${NC}"

echo ""
echo "--- base_footprint → base_link ---"
timeout 3 ros2 run tf2_ros tf2_echo base_footprint base_link 2>/dev/null | head -5 || echo -e "${YELLOW}無法查詢 base_footprint→base_link TF${NC}"

echo ""
echo "============================================"
echo " 診斷摘要"
echo "============================================"
if $ALL_OK; then
    echo -e "${GREEN}✓ 所有已檢查的節點 use_sim_time 均為 True${NC}"
else
    echo -e "${RED}✗ 有節點 use_sim_time 為 False，請參考企劃 Step 5 修正${NC}"
fi
echo ""
echo "若 TF 時間戳出現 ~1.7e9 量級，表示該 publisher 使用 wall time。"
echo "請參考企劃 Step 4 檢查 Isaac Sim OmniGraph 設定。"
