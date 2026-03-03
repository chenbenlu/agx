import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():

    # 1. 啟動底盤車控 (使用您原本寫好的 car_sensor.launch.py)
    car_sensor_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('car_control'),
                'launch',
                'car_sensor.launch.py'
            )
        )
    )

    # 2. 啟動光達 (urg_node2)
    # 注意: 這裡假設 urg_node2 的標準啟動檔叫做 urg_node2.launch.py
    # 如果您的環境有不同名稱，請自行修改。
    urg_node_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('urg_node2'),
                'launch',
                'urg_node2.launch.py'
            )
        )
    )

    # 3. 建立靜態 TF: base_link -> laser
    #    格式: [x, y, z, yaw, pitch, roll, frame_id, child_frame_id]
    #    請根據實際雷達裝設的位置自行微調數值(如向前挪 15 公分、墊高 20 公分等)
    base_to_laser_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='base_to_laser_broadcaster',
        arguments=['0.15', '0.0', '0.20', '0.0', '0.0', '0.0', 'base_link', 'laser'],
        output='screen'
    )

    # 4. 啟動 SLAM Toolbox
    slam_toolbox_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('slam_toolbox'),
                'launch',
                'online_async_launch.py'
            )
        ),
        launch_arguments={
            'use_sim_time': 'false',
            'slam_params_file': os.path.join(
                get_package_share_directory('car_control'),
                'config',
                'mapper_params_online_async.yaml'
            )
        }.items()
    )

    return LaunchDescription([
        car_sensor_launch,
        urg_node_launch,
        base_to_laser_tf,
        slam_toolbox_launch
    ])
