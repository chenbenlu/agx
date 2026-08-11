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

    twist_mux 與 real 一致掛載，sim 通常無人按鍵，nav2 直通；保留通道以利 debug。

Data Flow (模擬)：
    /cmd_vel_nav (nav2) ─┐
                          ├─► [twist_mux] ─► /cmd_vel → [Isaac Sim DifferentialController OmniGraph] → 輪速模擬
    /cmd_vel_teleop ─────┘
    Isaac Sim Encoder OmniGraph → /odom → [ekf_filter_node] → /odometry/filtered
    Isaac Sim LiDAR Bridge → /scan

實體機器人請改用：
    ros2 launch car_control car_sensor.launch.py
'''

import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():

    pkg = get_package_share_directory('car_control')
    twist_mux_config = os.path.join(pkg, 'config', 'twist_mux.yaml')

    # ==========================================================
    #  引入共用核心 (ekf_sim.yaml + rsp)，固定 use_sim_time=true
    # ==========================================================
    core_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg, 'launch', 'car_core.launch.py')
        ),
        launch_arguments={'use_sim_time': 'true'}.items(),
    )

    # ==========================================================
    #  twist_mux — 速度多工器（nav2 ↔ teleop_twist_keyboard）
    # ==========================================================
    twist_mux_node = Node(
        package='twist_mux',
        executable='twist_mux',
        name='twist_mux',
        output='screen',
        emulate_tty=True,
        parameters=[twist_mux_config, {'use_sim_time': True}],
        remappings=[('cmd_vel_out', 'cmd_vel')],
    )

    return LaunchDescription([
        core_launch,
        twist_mux_node,
    ])
