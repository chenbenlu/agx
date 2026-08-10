# ============================================================
#  Arduino Flasher — 專用燒錄容器
#  用途：編譯 + 燒錄 ros2_com.ino 到 Arduino Mega (ATmega2560)
#  以 root 執行，繞過 host /dev/ttyACM0 需要 dialout 群組的限制
# ============================================================
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ARG ARDUINO_CLI_VERSION=1.5.1

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
        | BINDIR=/usr/local/bin sh -s v${ARDUINO_CLI_VERSION}

RUN arduino-cli config init \
    && arduino-cli core update-index \
    && arduino-cli core install arduino:avr \
    && arduino-cli lib install ArduinoJson mcp_can

COPY flash.sh /usr/local/bin/flash.sh
RUN chmod +x /usr/local/bin/flash.sh

ENTRYPOINT ["/usr/local/bin/flash.sh"]
