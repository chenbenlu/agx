'''
核心節點啟動檔  【由 car_sensor.launch.py / car_sensor_sim.launch.py 引入，勿直接執行】

包含所有軟體節點（與硬體無關）：
    - laser_filter_node      — /scan → /scan_filtered（過濾手臂控制箱盲區）
    - robot_state_publisher  — 靜態 TF (URDF)
    - ekf_filter_node        — 里程計融合 → /odometry/filtered（僅 sim 啟用）

Launch Arguments：
    use_sim_time  (bool, default: false)
        false → 實車：繞過 EKF，由 kinematics_node 直接發 odom→base_footprint TF
                      並讓 nav2 訂閱 /raw_odom。ekf.yaml 先保留但不啟動。
        true  → ekf_sim.yaml (Isaac Sim /odom，EKF 不發布 TF)
'''

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetParameter
from ament_index_python.packages import get_package_share_directory
import xacro


def generate_launch_description():

    pkg = get_package_share_directory('car_control')
    use_sim_time = LaunchConfiguration('use_sim_time')

    # ==========================================================
    #  Launch Arguments
    # ==========================================================
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='true = 模擬時鐘；false = 實體機器時鐘'
    )

    # ==========================================================
    #  全域注入 use_sim_time — 此 Launch 內所有節點皆繼承
    # ==========================================================
    set_sim_time = SetParameter(name='use_sim_time', value=use_sim_time)

    # ==========================================================
    #  URDF / Robot Description
    # ==========================================================
    xacro_file = os.path.join(pkg, 'urdf', 'amr_core.urdf.xacro')
    doc = xacro.process_file(xacro_file)
    robot_description = {'robot_description': doc.toxml()}

    # ==========================================================
    #  Robot State Publisher
    # ==========================================================
    rsp_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[robot_description],
    )

    # ==========================================================
    #  EKF — 僅 sim 啟用
    #
    #  實體機：改由 kinematics_node 直接發 odom→base_footprint TF，
    #         nav2 訂閱 /raw_odom，暫時繞過 EKF。ekf.yaml 先保留備用。
    #  模擬　：Isaac Sim /odom，publish_tf=false（Isaac Sim 已發布 TF）
    # ==========================================================
    ekf_node_sim = Node(
        package='robot_localization',
        executable='ekf_node',
        name='ekf_filter_node',
        output='screen',
        parameters=[os.path.join(pkg, 'config', 'ekf_sim.yaml')],
        condition=IfCondition(use_sim_time),
    )

    # ==========================================================
    #  laser_filters — 過濾後方手臂控制箱盲區
    #  sim / real 共用，確保相同盲區範圍
    #  輸入: /scan  →  輸出: /scan_filtered
    # ==========================================================
    laser_filter_config = os.path.join(pkg, 'config', 'laser_filter.yaml')

    laser_filter_node = Node(
        package='laser_filters',
        executable='scan_to_scan_filter_chain',
        name='scan_to_scan_filter_chain',
        output='screen',
        parameters=[laser_filter_config],
        remappings=[
            ('scan', 'scan'),
            ('scan_filtered', 'scan_filtered'),
        ],
    )

    # ==========================================================
    #  組合
    # ==========================================================
    return LaunchDescription([
        use_sim_time_arg,
        set_sim_time,       # ← 全域注入，後續所有節點自動繼承
        rsp_node,
        ekf_node_sim,
        laser_filter_node,
    ])
