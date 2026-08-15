from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    repo_guess = Path(__file__).resolve().parents[2] / "GroundingDINO"
    weights_guess = Path(__file__).resolve().parents[2] / "weights/groundingdino_swint_ogc.pth"
    config_guess = repo_guess / "groundingdino/config/GroundingDINO_SwinT_OGC.py"

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "grounding_dino_repo_path",
                default_value=str(repo_guess),
                description="Path to the GroundingDINO repository.",
            ),
            DeclareLaunchArgument(
                "config_path",
                default_value=str(config_guess),
                description="GroundingDINO config file.",
            ),
            DeclareLaunchArgument(
                "weights_path",
                default_value=str(weights_guess),
                description="GroundingDINO checkpoint file.",
            ),
            DeclareLaunchArgument(
                "prompt",
                default_value="person.",
                description="Dot-separated prompt, e.g. 'black bicycle. grey umbrella.'.",
            ),
            DeclareLaunchArgument(
                "box_threshold",
                default_value="0.35",
                description="Minimum query confidence threshold.",
            ),
            DeclareLaunchArgument(
                "text_threshold",
                default_value="0.25",
                description="Phrase token threshold.",
            ),
            DeclareLaunchArgument(
                "device",
                default_value="cuda",
                description="Execution device, typically cuda on AGX Orin.",
            ),
            DeclareLaunchArgument(
                "use_fp16",
                default_value="false",
                description="Use AMP FP16 inference when available.",
            ),
            DeclareLaunchArgument(
                "publish_annotated_image",
                default_value="true",
                description="Publish /annotated_image along with detections.",
            ),
            Node(
                package="isaac_ros_grounding_dino_orin",
                executable="grounding_dino_orin_node",
                name="grounding_dino_orin_node",
                output="screen",
                parameters=[
                    {
                        "grounding_dino_repo_path": LaunchConfiguration(
                            "grounding_dino_repo_path"
                        ),
                        "config_path": LaunchConfiguration("config_path"),
                        "weights_path": LaunchConfiguration("weights_path"),
                        "prompt": LaunchConfiguration("prompt"),
                        "box_threshold": ParameterValue(
                            LaunchConfiguration("box_threshold"),
                            value_type=float,
                        ),
                        "text_threshold": ParameterValue(
                            LaunchConfiguration("text_threshold"),
                            value_type=float,
                        ),
                        "device": LaunchConfiguration("device"),
                        "use_fp16": ParameterValue(
                            LaunchConfiguration("use_fp16"),
                            value_type=bool,
                        ),
                        "publish_annotated_image": ParameterValue(
                            LaunchConfiguration("publish_annotated_image"),
                            value_type=bool,
                        ),
                    }
                ],
                remappings=[
                    ("image", "image_rect"),
                    ("detections_output", "detections_output"),
                    ("annotated_image", "annotated_image"),
                ],
            ),
        ]
    )
