FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip uv

WORKDIR /opt
RUN git clone --depth=1 https://github.com/NVlabs/alpamayo.git /opt/alpamayo

WORKDIR /opt/alpamayo
RUN uv venv /opt/ar1_venv
ENV VIRTUAL_ENV=/opt/ar1_venv
ENV PATH="/opt/ar1_venv/bin:${PATH}"
RUN uv sync --active

RUN pip install huggingface_hub

ENV HF_HOME=/data/hf \
    TRANSFORMERS_CACHE=/data/hf

CMD ["bash", "-lc", "sleep infinity"]
