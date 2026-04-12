'''
感測器啟動檔  【Isaac Sim 模擬環境】
啟動命令：
    ros2 launch car_control car_sensor_sim.launch.py

架構說明：
    引入 car_core.launch.py (robot_state_publisher + ekf_filter_node)，
    以 use_sim_time=true 與 ekf_sim.yaml 運行。

    不啟動任何硬體節點：
        × urg_node2        — /scan 由 Isaac Sim LiDAR Bridge 提供
        × serial_bridge    — 馬達指令由 Isaac Sim OmniGraph DifferentialController 處理
        × kinematics_node  — /cmd_vel 直接接入 Isaac Sim

Data Flow (模擬)：
    /cmd_vel → [Isaac Sim DifferentialController OmniGraph] → 輪速模擬
    Isaac Sim Encoder OmniGraph → /odom → [ekf_filter_node] → /odometry/filtered
    Isaac Sim LiDAR Bridge → /scan

實體機器人請改用：
    ros2 launch car_control car_sensor.launch.py
'''

import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():

    pkg = get_package_share_directory('car_control')

    # ==========================================================
    #  引入共用核心 (ekf_sim.yaml + rsp)，固定 use_sim_time=true
    # ==========================================================
    core_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg, 'launch', 'car_core.launch.py')
        ),
        launch_arguments={'use_sim_time': 'true'}.items(),
    )

    return LaunchDescription([
        core_launch,
    ])
