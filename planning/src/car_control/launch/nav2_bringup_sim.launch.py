'''
Nav2 導航啟動檔  【Isaac Sim 模擬環境專用】
啟動命令：
    ros2 launch car_control nav2_bringup_sim.launch.py

架構說明：
    引入 nav2_bringup.launch.py，固定 use_sim_time=true，
    載入 sim 專用參數檔 nav2_params_sim.yaml。

    搭配 car_sensor_sim.launch.py 使用：
        Terminal 1: ros2 launch car_control car_sensor_sim.launch.py
        Terminal 2: ros2 launch car_control nav2_bringup_sim.launch.py

實體機器人請改用：
    ros2 launch car_control nav2_bringup.launch.py
'''

import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, SetLaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import SetParameter
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():

    pkg = get_package_share_directory('car_control')

    # sim 專用參數檔 — 所有節點的 use_sim_time 已設為 True
    sim_params = os.path.join(pkg, 'config', 'nav2_params_sim.yaml')

    # ==========================================================
    #  全域注入 use_sim_time=true
    # ==========================================================
    set_sim_time = SetParameter(name='use_sim_time', value=True)

    # ==========================================================
    #  引入 nav2_bringup.launch.py，覆寫 use_sim_time + params_file
    # ==========================================================
    nav2_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg, 'launch', 'nav2_bringup.launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'true',
            'params_file': sim_params,
        }.items(),
    )

    # ==========================================================
    #  縮短 shutdown 超時 — 避免 Nav2 進程卡死
    # ==========================================================
    sigterm_timeout = SetLaunchConfiguration('sigterm_timeout', '5')
    sigkill_timeout = SetLaunchConfiguration('sigkill_timeout', '2')

    return LaunchDescription([
        sigterm_timeout,
        sigkill_timeout,
        set_sim_time,
        nav2_launch,
    ])
