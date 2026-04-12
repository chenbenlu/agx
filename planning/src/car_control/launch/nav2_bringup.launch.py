import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    car_control_share = get_package_share_directory('car_control')
    nav2_bringup_share = get_package_share_directory('nav2_bringup')

    default_map = os.path.join(car_control_share, 'config', 'sim_map.yaml')
    default_params = os.path.join(car_control_share, 'config', 'nav2_params.yaml')

    use_sim_time = LaunchConfiguration('use_sim_time')
    map_yaml = LaunchConfiguration('map')
    params_file = LaunchConfiguration('params_file')

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation clock from /clock (set true for Isaac Sim)'
    )
    declare_map = DeclareLaunchArgument(
        'map',
        default_value=default_map,
        description='Full path to map yaml file to load'
    )
    declare_params = DeclareLaunchArgument(
        'params_file',
        default_value=default_params,
        description='Full path to the ROS2 parameters file for Nav2'
    )

    nav2_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup_share, 'launch', 'bringup_launch.py')
        ),
        launch_arguments={
            'use_sim_time': use_sim_time,
            'map': map_yaml,
            'params_file': params_file,
        }.items()
    )

    return LaunchDescription([
        declare_use_sim_time,
        declare_map,
        declare_params,
        nav2_launch,
    ])
