# ./cosmos/Dockerfile

# 1. 基底映像檔 - 使用與 NanoLLM 同體系的 Jetson 基底，但切到 JP6 / CUDA 12.6 相容版本
#    Cosmos-Reason2 的 jp6 extra 需要 CUDA 12.6 + cuDNN 9；
#    實測 nano_llm:humble-r36.3.0 只有 CUDA 12.2，會導致 torch 載入失敗。
FROM dustynv/l4t-pytorch:r36.4.0

ENV DEBIAN_FRONTEND=noninteractive

# 2. 更新 ROS 2 GPG key (解決過期問題)
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg

# 2.1 修正 PyPI 設定 - JetPack 6 / CUDA 12.6
# 保留 NGC，加入 Jetson AI Lab jp6/cu126 index
ENV PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_EXTRA_INDEX_URL="https://pypi.jetson-ai-lab.io/jp6/cu126 https://pypi.ngc.nvidia.com"
ENV PIP_TRUSTED_HOST="pypi.jetson-ai-lab.io jetson.webredirect.org pypi.ngc.nvidia.com"

# 2.2 Jetson Orin / vLLM / Triton 所需 CUDA 環境
ENV CUDA_HOME=/usr/local/cuda \
    PATH=/usr/local/cuda/bin:${PATH} \
    CPATH=/usr/local/cuda/include \
    LD_LIBRARY_PATH=/usr/local/cuda-12.6/lib64:/usr/local/cuda-12.6/targets/aarch64-linux/lib:/usr/lib/aarch64-linux-gnu/libcudss/12 \
    TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas \
    HF_HOME=/data/hf \
    TRANSFORMERS_CACHE=/data/hf \
    UV_LINK_MODE=copy

# 3. 安裝 cuDSS runtime (Jetson Orin 安裝指南)
#    `dustynv/l4t-pytorch:r36.4.0` 已內建 python3.10 / git / curl / wget / unzip，
#    這裡只補 torch 需要的 cuDSS runtime，避免額外 apt 升級造成 build 失敗。
RUN wget -q https://developer.download.nvidia.com/compute/cudss/0.7.1/local_installers/cudss-local-repo-ubuntu2204-0.7.1_0.7.1-1_arm64.deb \
    && dpkg -i cudss-local-repo-ubuntu2204-0.7.1_0.7.1-1_arm64.deb \
    && dpkg -i /var/cudss-local-repo-ubuntu2204-0.7.1/libcudss0-cuda-12_0.7.1.4-1_arm64.deb \
    && echo '/usr/lib/aarch64-linux-gnu/libcudss/12' > /etc/ld.so.conf.d/cudss.conf \
    && ldconfig \
    && rm -f cudss-local-repo-ubuntu2204-0.7.1_0.7.1-1_arm64.deb \
    && rm -rf /var/cudss-local-repo-ubuntu2204-0.7.1

# 4. 安裝 uv 與 Jetson 監控工具
RUN pip3 install --no-cache-dir -U pip uv jetson-stats

# 5. 取得 Jetson AGX Orin 支援分支
WORKDIR /opt
RUN git clone --depth=1 --branch feature/jetson-agx-orin-support https://github.com/Sn0wl3r0ker/cosmos-reason2.git /opt/cosmos-reason2

# 6. 依 README / Jetson Orin 指南安裝 jp6 extra (Python 3.10)
WORKDIR /opt/cosmos-reason2
RUN uv sync --extra jp6 --python 3.10

# 7. 進容器後自動啟用環境
RUN echo 'export CUDA_HOME=/usr/local/cuda' >> /root/.bashrc \
    && echo 'export PATH=/usr/local/cuda/bin:$PATH' >> /root/.bashrc \
    && echo 'export CPATH=/usr/local/cuda/include:$CPATH' >> /root/.bashrc \
    && echo 'export LD_LIBRARY_PATH=/usr/local/cuda-12.6/lib64:/usr/local/cuda-12.6/targets/aarch64-linux/lib:/usr/lib/aarch64-linux-gnu/libcudss/12:$LD_LIBRARY_PATH' >> /root/.bashrc \
    && echo 'export TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas' >> /root/.bashrc \
    && echo 'export HF_HOME=/data/hf' >> /root/.bashrc \
    && echo 'export TRANSFORMERS_CACHE=/data/hf' >> /root/.bashrc \
    && echo 'source /opt/cosmos-reason2/.venv/bin/activate' >> /root/.bashrc

# 8. 預設工作目錄
WORKDIR /opt/cosmos-reason2

# 9. 預設指令
CMD ["bash", "-lc", "sleep infinity"]
