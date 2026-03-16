'''
啟動 C++ 車控節點 (Serial Bridge + Kinematics)
啟動命令：
    ros2 launch car_control car_sensor_cpp.launch.py

架構說明：
    serial_bridge_node — 獨佔 Serial Port，負責 ROS topics ↔ UART JSON 雙向轉換
    kinematics_node    — 處理 cmd_vel→輪速 與 encoder→Odom/TF

Data Flow：
    /cmd_vel → [kinematics_node] → /serial_tx → [serial_bridge_node] → UART TX
    UART RX → [serial_bridge_node] → /serial_rx → [kinematics_node] → /odom + TF
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

    return LaunchDescription([
        serial_bridge_node,
        kinematics_node,
    ])
