from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.substitutions import LaunchConfiguration


def _launch_setup(context, *args, **kwargs):
    return [
        ExecuteProcess(
            cmd=[
                "python3",
                "/opt/vlm_marker/semantic_map_marker_node.py",
                "--ros-args",
                "-p",
                f"target_filter:={LaunchConfiguration('target_filter').perform(context)}",
                "-p",
                f"score_threshold:={LaunchConfiguration('score_threshold').perform(context)}",
                "-p",
                f"map_frame:={LaunchConfiguration('map_frame').perform(context)}",
                "-p",
                f"base_frame:={LaunchConfiguration('base_frame').perform(context)}",
            ],
            output="screen",
        )
    ]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("target_filter", default_value=""),
            DeclareLaunchArgument("score_threshold", default_value="0.75"),
            DeclareLaunchArgument("map_frame", default_value="map"),
            DeclareLaunchArgument("base_frame", default_value="base_footprint"),
            OpaqueFunction(function=_launch_setup),
        ]
    )
