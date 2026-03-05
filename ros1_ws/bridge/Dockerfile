# 1. 使用官方支援 ARM64 的 Foxy Base Image (Ubuntu 20.04)
FROM ros:foxy-ros-base

ENV DEBIAN_FRONTEND=noninteractive

# 2. 設定 ROS 1 Noetic 的軟體來源
# (因為 Base Image 是 Foxy，裡面只有 ROS 2，我們需要補裝 ROS 1)
RUN apt-get update && apt-get install -y curl gnupg2 lsb-release \
    && sh -c 'echo "deb http://packages.ros.org/ros/ubuntu $(lsb_release -sc) main" > /etc/apt/sources.list.d/ros-latest.list' \
    && curl -s https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc | apt-key add - \
    && apt-get update

# 3. 安裝 ROS 1 通訊套件 與 ROS 1 Bridge
RUN apt-get install -y \
    ros-noetic-ros-comm \
    ros-foxy-ros1-bridge \
    && rm -rf /var/lib/apt/lists/*

COPY fastdds.xml /fastdds.xml
ENV FASTRTPS_DEFAULT_PROFILES_FILE=/fastdds.xml
ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp

RUN sed -i '1i source /opt/ros/noetic/setup.bash' /root/.bashrc && \
    sed -i '2i source /opt/ros/foxy/setup.bash' /root/.bashrc && \
    sed -i '3i export RMW_IMPLEMENTATION=rmw_fastrtps_cpp' /root/.bashrc && \
    sed -i '4i export FASTRTPS_DEFAULT_PROFILES_FILE=/fastdds.xml' /root/.bashrc

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 4. 預設指令 (也可以在 compose 覆寫)
CMD ["bash"]