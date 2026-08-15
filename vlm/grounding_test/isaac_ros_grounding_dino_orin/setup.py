from setuptools import find_packages, setup

package_name = "isaac_ros_grounding_dino_orin"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", ["launch/grounding_dino_orin.launch.py"]),
        (f"share/{package_name}/scripts", ["scripts/build_trt_engine.sh"]),
        (f"share/{package_name}", ["README.md"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="syslab",
    maintainer_email="syslab@example.com",
    description="GroundingDINO ROS 2 package for Jetson AGX Orin / Isaac ROS style pipelines.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "grounding_dino_orin_node = isaac_ros_grounding_dino_orin.grounding_dino_node:main",
            "export_grounding_dino_isaac_onnx = isaac_ros_grounding_dino_orin.export_onnx:main",
            "detect_grounding_dino_image = isaac_ros_grounding_dino_orin.detect_image:main",
        ],
    },
)
