'''
啟動 C++ 車控節點 (Serial Bridge + Kinematics)
啟動命令：
    ros2 launch car_control car_sensor_cpp.launch.py

架構說明：
    serial_bridge_node — 獨佔 Serial Port，獨立 Reader Thread 讀取，
                         根據 JSON Key 分流發布到 /raw_odom, /battery_state, /charge_status
    kinematics_node    — 處理 cmd_vel→輪速 與 encoder→Odom/TF，
                         電量→/battery_voltage，充電站→/charging_state

Data Flow (下行)：
    /cmd_vel → [kinematics_node] → /motor_cmd → [serial_bridge_node] → UART TX {"ls":x,"rs":y}
    /charge_cmd → [serial_bridge_node] → UART TX {"charge":1}

Data Flow (上行)：
    UART RX {"p1":x,"p2":y}          → [serial_bridge_node] → /raw_odom      → [kinematics_node] → /odom + TF
    UART RX {"pow":24.5}             → [serial_bridge_node] → /battery_state  → [kinematics_node] → /battery_voltage
    UART RX {"can_v":x,"can_w":y...} → [serial_bridge_node] → /charge_status → [kinematics_node] → /charging_state
'''

from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():

    # ---------- 取得參數檔路徑 ----------
    config_file = os.path.join(
        get_package_share_directory('car_control'),
        'config',
        'car_controller_cpp.yaml'
    )

    # ---------- Serial Bridge Node ----------
    serial_bridge_node = Node(
        package='car_control',
        executable='serial_bridge_node',
        name='serial_bridge_node',
        output='screen',
        emulate_tty=True,
        parameters=[config_file],
    )

    # ---------- Kinematics Node ----------
    kinematics_node = Node(
        package='car_control',
        executable='kinematics_node',
        name='kinematics_node',
        output='screen',
        emulate_tty=True,
        parameters=[config_file],
    )

    base_to_laser_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='base_to_laser_broadcaster',
        arguments=['0.15', '0.0', '0.20', '0.0', '0.0', '0.0', 'base_link', 'laser'],
        output='screen'
    )

    return LaunchDescription([
        serial_bridge_node,
        kinematics_node,
        base_to_laser_tf,
    ])
