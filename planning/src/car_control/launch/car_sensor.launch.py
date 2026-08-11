'''
感測器啟動檔  【實體機器人】
啟動命令：
    ros2 launch car_control car_sensor.launch.py

架構說明：
    引入 car_core.launch.py (robot_state_publisher + ekf_filter_node)，
    再疊加實體硬體節點 (urg_node2 + serial_bridge_node + kinematics_node)。

    第三方套件 (urg_node2) 保持唯讀，其參數透過
    car_control/config/urg_node2_override.yaml 注入覆寫。

Data Flow (下行)：
    /cmd_vel_nav (nav2) ─┐
                          ├─► [twist_mux] ─► /cmd_vel ─► [kinematics_node] ─► /motor_cmd ─► [serial_bridge_node] → UART TX {"ls":x,"rs":y}
    /cmd_vel_teleop ─────┘  (priority: teleop > nav, timeout 0.5s)
    /charge_cmd → [serial_bridge_node] → UART TX {"charge":1}

Data Flow (上行)：
    UART RX {"p1":x,"p2":y}          → [serial_bridge_node] → /raw_odom
    UART RX {"pow":24.5}             → [serial_bridge_node] → /battery_state  → [kinematics_node] → /battery_voltage
    UART RX {"can_v":x,"can_w":y...} → [serial_bridge_node] → /charge_status → [kinematics_node] → /charging_state

LiDAR：
    urg_node2 (LifecycleNode) → /scan (sensor_msgs/LaserScan)
    → [laser_filter_node] → /scan_filtered (過濾後方手臂控制箱)

模擬環境請改用：
    ros2 launch car_control car_sensor_sim.launch.py
'''

import os
import yaml
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    IncludeLaunchDescription,
    RegisterEventHandler,
)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessStart
from launch.events import matches_action
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode, Node
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():

    pkg = get_package_share_directory('car_control')

    # ==========================================================
    #  參數檔路徑
    # ==========================================================
    car_control_config = os.path.join(pkg, 'config', 'car_controller_cpp.yaml')
    urg_override_config = os.path.join(pkg, 'config', 'urg_node2_override.yaml')
    twist_mux_config = os.path.join(pkg, 'config', 'twist_mux.yaml')

    with open(urg_override_config, 'r') as f:
        urg_params = yaml.safe_load(f)['urg_node2']['ros__parameters']

    # ==========================================================
    #  Launch Arguments
    # ==========================================================
    auto_start_arg = DeclareLaunchArgument(
        'auto_start', default_value='true',
        description='自動將 urg_node2 LifecycleNode 轉換到 Active 狀態'
    )

    # ==========================================================
    #  引入共用核心 (ekf + rsp)，固定 use_sim_time=false
    # ==========================================================
    core_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg, 'launch', 'car_core.launch.py')
        ),
        launch_arguments={'use_sim_time': 'false'}.items(),
    )

    # ==========================================================
    #  urg_node2 — LifecycleNode
    # ==========================================================
    urg_lifecycle_node = LifecycleNode(
        package='urg_node2',
        executable='urg_node2_node',
        name='urg_node2',
        namespace='',
        output='screen',
        emulate_tty=True,
        parameters=[urg_params],
        remappings=[('scan', 'scan')],
    )

    # Unconfigured → Inactive (configure)
    configure_handler = RegisterEventHandler(
        event_handler=OnProcessStart(
            target_action=urg_lifecycle_node,
            on_start=[
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=matches_action(urg_lifecycle_node),
                        transition_id=Transition.TRANSITION_CONFIGURE,
                    ),
                ),
            ],
        ),
        condition=IfCondition(LaunchConfiguration('auto_start')),
    )

    # Inactive → Active (activate)
    activate_handler = RegisterEventHandler(
        event_handler=OnStateTransition(
            target_lifecycle_node=urg_lifecycle_node,
            start_state='configuring',
            goal_state='inactive',
            entities=[
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=matches_action(urg_lifecycle_node),
                        transition_id=Transition.TRANSITION_ACTIVATE,
                    ),
                ),
            ],
        ),
        condition=IfCondition(LaunchConfiguration('auto_start')),
    )

    # ==========================================================
    #  car_control — C++ 車控節點
    # ==========================================================
    serial_bridge_node = Node(
        package='car_control',
        executable='serial_bridge_node',
        name='serial_bridge_node',
        output='screen',
        emulate_tty=True,
        parameters=[car_control_config],
    )

    kinematics_node = Node(
        package='car_control',
        executable='kinematics_node',
        name='kinematics_node',
        output='screen',
        emulate_tty=True,
        parameters=[car_control_config],
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
        parameters=[twist_mux_config],
        remappings=[('cmd_vel_out', 'cmd_vel')],
    )

    # ==========================================================
    #  組合啟動
    # ==========================================================
    return LaunchDescription([
        auto_start_arg,

        # 共用核心 (ekf + rsp + laser_filter)
        core_launch,

        # 實體 LiDAR
        urg_lifecycle_node,
        configure_handler,
        activate_handler,

        # 實體車控
        serial_bridge_node,
        kinematics_node,

        # 速度多工器
        twist_mux_node,
    ])
