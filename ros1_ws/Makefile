# ==============================================================================
#  AGX ROS 1 Control Interface (ros1_ws)
# ==============================================================================

# --- [Configuration] ---
PROJECT_NAME   := agx_ros_1
TASK_CONTAINER := control
SERVICE_NAME   ?= control

# Docker Buildkit
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# --- [Auto-Detection] ---
CURRENT_CONTEXT := $(shell docker context show)
MODE := pc
ENV_FILE := ../.env
COMPOSE_FILE :=

ifneq (,$(findstring agx,$(CURRENT_CONTEXT)))
    MODE := agx
    ENV_FILE := ../.env.agx
    COMPOSE_FILE := -f docker-compose.agx.yaml
else ifeq ($(shell uname -m), aarch64)
    MODE := agx
    ENV_FILE := ../.env.agx
    COMPOSE_FILE := -f docker-compose.agx.yaml
endif

# --- [Compose Commands] ---
COMPOSE_CMD := docker compose --env-file $(ENV_FILE) -f docker-compose.yaml $(COMPOSE_FILE) -p $(PROJECT_NAME)

TASK_EXEC   := docker exec -it $(TASK_CONTAINER) bash -ic

# --- [Make Settings] ---
.DEFAULT_GOAL := help
.SILENT:
.PHONY: help build up rebuild down join logs ps clean run stop view guard-%

# ==============================================================================
#  Logic Definitions (Shell Scripts inside Makefile)
# ==============================================================================

# 1. RUN SCRIPT
define SCRIPT_RUN
    echo "=========================================="
    echo " AGX Task Launcher (ROS 1)"
    echo " Target: $(TASK_CONTAINER)"
    echo "=========================================="
    echo "1) Keyboard Control (agx_keyboard)"
    echo "2) Lidar Mapping    (agx_lidar)"
    echo "3) HDL Localization (agx_loc)"
    echo "4) Realsense Camera (agx_camera)"
    echo "------------------------------------------"
    echo "a) Launch ALL    q) Quit"
    echo "------------------------------------------"
    read -p "Select task(s) [1-4/a/q, 可多選如 1 3]: " INPUT
    if [ "$$INPUT" = "q" ]; then exit 0; fi
    if [ "$$INPUT" = "a" ]; then INPUT="1 2 3 4"; fi
    CHOICES=$$(echo "$$INPUT" | tr ',' ' ')
    LAUNCHED=0
    for choice in $$CHOICES; do
        S_NAME=""; CMD_MAIN=""; CMD_SUB=""; TYPE="single"
        case $$choice in
            1) S_NAME="agx_keyboard"; CMD_MAIN="rosrun rosserial_python serial_node.py _port:=/dev/ttyUSB0"; CMD_SUB="rosrun six_wheels_teleop imu_teletop_0908"; TYPE="split";;
            2) S_NAME="agx_lidar";    CMD_MAIN="roslaunch velodyne_pointcloud VLP16_points.launch";;
            3) S_NAME="agx_loc";      CMD_MAIN="roslaunch hdl_localization hdl_localization.launch";;
            4) S_NAME="agx_camera";   CMD_MAIN="roslaunch realsense2_camera rs_camera.launch"; CMD_SUB="rosrun imu_filter_madgwick imu_filter_node _use_mag:=false _remove_gravity_vector:=true _output_rate:=100.0 /imu/data_raw:=/camera/imu"; TYPE="split";;
            *) echo "[Warn] Skipping invalid option: $$choice"; continue;;
        esac
        if TMUX= tmux has-session -t $$S_NAME 2>/dev/null; then
            echo "[Skip] $$S_NAME already running."
            continue
        fi
        echo "[Info] Launching $$S_NAME..."
        TMUX= tmux new-session -d -s $$S_NAME
        sleep 1
        tmux set -g mouse on
        tmux send-keys -t $$S_NAME:0 "$(TASK_EXEC) '$$CMD_MAIN'" C-m
        if [ "$$TYPE" = "split" ]; then
            tmux split-window -h -t $$S_NAME:0
            sleep 0.5
            tmux send-keys -t $$S_NAME:0.1 "sleep 2" C-m
            tmux send-keys -t $$S_NAME:0.1 "$(TASK_EXEC) '$$CMD_SUB'" C-m
        fi
        LAUNCHED=$$((LAUNCHED + 1))
    done
    echo "[Info] $$LAUNCHED task(s) launched."
    echo "       Use 'make view' to monitor, 'make stop' to terminate."
endef
export SCRIPT_RUN

# 2. JOIN SCRIPT
define SCRIPT_JOIN
    LIST=$$(docker ps --filter "label=com.docker.compose.project=$(PROJECT_NAME)" --format "{{.Names}}" || true)
    if [ -z "$$LIST" ]; then echo "[Info] No project containers are running."; exit 0; fi
    echo "=========================================="
    echo " Select container to enter"
    echo "=========================================="
    echo "$$LIST" | awk '{print NR ") " $$0}'
    echo "q) Quit"
    echo "------------------------------------------"
    read -p "Enter number: " j_choice
    if [ "$$j_choice" = "q" ]; then exit 0; fi
    TARGET=$$(echo "$$LIST" | sed -n "$${j_choice}p")
    if [ -n "$$TARGET" ]; then
        echo "[Info] Entering $$TARGET..."
        docker exec -it $$TARGET bash
    else
        echo "[Error] Invalid number."
    fi
endef
export SCRIPT_JOIN

# 3. STOP SCRIPT
define SCRIPT_STOP
    LIST=$$(tmux ls -F "#{session_name}" 2>/dev/null | grep -E "^(agx_)" || true)
    if [ -z "$$LIST" ]; then echo "[Info] No active tasks running."; exit 0; fi
    echo "=========================================="
    echo " Select task to terminate"
    echo "=========================================="
    echo "$$LIST" | awk '{print NR ") " $$0}'
    echo "a) Terminate All"
    echo "q) Quit"
    echo "------------------------------------------"
    read -p "Enter number: " k_choice
    if [ "$$k_choice" = "q" ]; then exit 0; fi
    if [ "$$k_choice" = "a" ]; then echo "$$LIST" | xargs -n 1 tmux kill-session -t; echo "[Info] All tasks terminated."; exit 0; fi
    TARGET=$$(echo "$$LIST" | sed -n "$${k_choice}p")
    if [ -n "$$TARGET" ]; then tmux kill-session -t "$$TARGET"; echo "[Info] $$TARGET terminated."; else echo "[Error] Invalid number."; fi
endef
export SCRIPT_STOP

# 4. VIEW SCRIPT
define SCRIPT_VIEW
    LIST=$$(tmux ls -F "#{session_name}" 2>/dev/null | grep -E "^(agx_)" || true)
    if [ -z "$$LIST" ]; then echo "[Info] No active tasks."; exit 0; fi
    echo "=========================================="
    echo " Select task to view"
    echo "=========================================="
    echo "$$LIST" | awk '{print NR ") " $$0}'
    echo "q) Quit"
    echo "------------------------------------------"
    read -p "Enter number: " v_choice
    if [ "$$v_choice" = "q" ]; then exit 0; fi
    TARGET=$$(echo "$$LIST" | sed -n "$${v_choice}p")
    if [ -n "$$TARGET" ]; then
        if [ -n "$$TMUX" ]; then
            echo "[Warn] Already in Tmux. Use 'Ctrl+B, s' to switch."
        else
            echo "[Info] Attaching to $$TARGET... (Press Ctrl+B, d to detach)"
            tmux attach-session -t "$$TARGET"
        fi
    else
        echo "[Error] Invalid number."
    fi
endef
export SCRIPT_VIEW

# --- [Service List] ---
SERVICES := roscore control bridge foxglove_ros1

# --- [共通選單 Header] ---
define SERVICE_MENU
    echo "--- ROS 1 ---"
    echo "1) roscore       - ROS 1 Master"
    echo "2) control       - ROS 1 底層控制"
    echo "3) bridge        - ROS 1 <-> ROS 2 橋樑"
    echo "4) foxglove_ros1 - ROS 1 資料視覺化"
endef

# 5. UP SCRIPT (多選)
define SCRIPT_UP
    echo "=========================================="
    echo " AGX Service Launcher (ROS 1 - $(MODE) mode)"
    echo "=========================================="
    $(SERVICE_MENU)
    echo "------------------------------------------"
    echo "a) Start ALL    q) Quit"
    echo "------------------------------------------"
    read -p "Select service(s) [1-4/a/q, 可多選如 1 3]: " INPUT
    if [ "$$INPUT" = "q" ]; then exit 0; fi
    if [ "$$INPUT" = "a" ]; then
        echo "[Info] Starting ALL services..."
        $(COMPOSE_CMD) up -d
        echo "[Info] All services started."
        exit 0
    fi
    CHOICES=$$(echo "$$INPUT" | tr ',' ' ')
    FOLDERS="roscore control bridge foxglove_ros1"
    TARGETS=""
    for c in $$CHOICES; do
        T=$$(echo "$$FOLDERS" | tr ' ' '\n' | sed -n "$${c}p")
        if [ -z "$$T" ]; then echo "[Warn] Skipping invalid: $$c"; continue; fi
        TARGETS="$$TARGETS $$T"
    done
    if [ -n "$$TARGETS" ]; then
        echo "[Info] Starting services:$$TARGETS"
        $(COMPOSE_CMD) up -d $$TARGETS
    fi
endef
export SCRIPT_UP

# 6. DOWN SCRIPT (多選)
define SCRIPT_DOWN
    echo "=========================================="
    echo " AGX Service Stopper (ROS 1)"
    echo "=========================================="
    $(SERVICE_MENU)
    echo "------------------------------------------"
    echo "a) Stop ALL    q) Quit"
    echo "------------------------------------------"
    read -p "Select service(s) [1-4/a/q, 可多選如 1 3]: " INPUT
    if [ "$$INPUT" = "q" ]; then exit 0; fi
    if [ "$$INPUT" = "a" ]; then
        echo "[Info] Stopping ALL services..."
        $(COMPOSE_CMD) down --remove-orphans
        echo "[Info] All services stopped."
        exit 0
    fi
    CHOICES=$$(echo "$$INPUT" | tr ',' ' ')
    FOLDERS="roscore control bridge foxglove_ros1"
    TARGETS=""
    for c in $$CHOICES; do
        T=$$(echo "$$FOLDERS" | tr ' ' '\n' | sed -n "$${c}p")
        if [ -z "$$T" ]; then echo "[Warn] Skipping invalid: $$c"; continue; fi
        TARGETS="$$TARGETS $$T"
    done
    if [ -n "$$TARGETS" ]; then
        echo "[Info] Stopping services:$$TARGETS"
        $(COMPOSE_CMD) rm -s -v -f $$TARGETS
    fi
endef
export SCRIPT_DOWN

# 7. BUILD SCRIPT (多選)
define SCRIPT_BUILD
    echo "=========================================="
    echo " AGX Image Builder (ROS 1 - $(MODE) mode)"
    echo "=========================================="
    $(SERVICE_MENU)
    echo "------------------------------------------"
    echo "a) Build ALL    q) Quit"
    echo "------------------------------------------"
    read -p "Select service(s) [1-4/a/q, 可多選如 1 3]: " INPUT
    if [ "$$INPUT" = "q" ]; then exit 0; fi
    if [ "$$INPUT" = "a" ]; then
        echo "[Info] Building ALL images..."
        $(COMPOSE_CMD) build
        echo "[Info] All images built."
        exit 0
    fi
    CHOICES=$$(echo "$$INPUT" | tr ',' ' ')
    FOLDERS="roscore control bridge foxglove_ros1"
    TARGETS=""
    for c in $$CHOICES; do
        T=$$(echo "$$FOLDERS" | tr ' ' '\n' | sed -n "$${c}p")
        if [ -z "$$T" ]; then echo "[Warn] Skipping invalid: $$c"; continue; fi
        TARGETS="$$TARGETS $$T"
    done
    if [ -n "$$TARGETS" ]; then
        echo "[Info] Building services:$$TARGETS"
        $(COMPOSE_CMD) build $$TARGETS
    fi
endef
export SCRIPT_BUILD

# 8. REBUILD SCRIPT (多選)
define SCRIPT_REBUILD
    echo "=========================================="
    echo " AGX Service Rebuilder (ROS 1 - $(MODE) mode)"
    echo "=========================================="
    $(SERVICE_MENU)
    echo "------------------------------------------"
    echo "a) Rebuild ALL    q) Quit"
    echo "------------------------------------------"
    read -p "Select service(s) [1-4/a/q, 可多選如 1 3]: " INPUT
    if [ "$$INPUT" = "q" ]; then exit 0; fi
    if [ "$$INPUT" = "a" ]; then
        echo "[Info] Rebuilding ALL services..."
        $(COMPOSE_CMD) up -d --build --force-recreate
        echo "[Info] All services rebuilt."
        exit 0
    fi
    CHOICES=$$(echo "$$INPUT" | tr ',' ' ')
    FOLDERS="roscore control bridge foxglove_ros1"
    TARGETS=""
    for c in $$CHOICES; do
        T=$$(echo "$$FOLDERS" | tr ' ' '\n' | sed -n "$${c}p")
        if [ -z "$$T" ]; then echo "[Warn] Skipping invalid: $$c"; continue; fi
        TARGETS="$$TARGETS $$T"
    done
    if [ -n "$$TARGETS" ]; then
        echo "[Info] Rebuilding services:$$TARGETS"
        $(COMPOSE_CMD) up -d --build --force-recreate $$TARGETS
    fi
endef
export SCRIPT_REBUILD

# ==============================================================================
#  Targets
# ==============================================================================

help: ## Show available commands
	echo "AGX ROS 1 Control Interface"
	echo "   Task Target: $(TASK_CONTAINER)"
	echo "   Context:     $(CURRENT_CONTEXT)"
	echo "   Mode:        $(MODE)"
	echo "   Compose:     $(COMPOSE_FILE)"
	echo "================================================"
	echo ""
	echo "--- Docker 服務 (互動式選單) ---"
	echo "  make up                 啟動服務"
	echo "  make down               停止服務"
	echo "  make build              Build 映像檔"
	echo "  make rebuild            強制重建服務"
	echo ""
	echo "--- 狀態 ---"
	echo "  make logs               Follow all logs"
	echo "  make ps                 View container status"
	echo "  make clean              Remove all containers & images"
	echo ""
	echo "--- 任務管理 ---"
	echo "  make join               Enter container shell"
	echo "  make run                Launch control task"
	echo "  make stop               Terminate running tasks"
	echo "  make view               Attach to task session"

check-env:
	if [ ! -f $(ENV_FILE) ]; then echo "[Error] Config file '$(ENV_FILE)' not found."; exit 1; fi

guard-%:
	if [ -z "$$(docker ps -q -f name=$*)" ]; then \
		echo "[Error] Container '$*' is not running. Run 'make up' first."; \
		exit 1; \
	fi

# --- Docker 服務 (互動式選單) ---
build: check-env ## Build images (interactive)
	bash -c "$$SCRIPT_BUILD"

up: check-env ## Start services (interactive)
	bash -c "$$SCRIPT_UP"

rebuild: check-env ## Force rebuild (interactive)
	bash -c "$$SCRIPT_REBUILD"

down: ## Stop services (interactive)
	bash -c "$$SCRIPT_DOWN"

logs: ## Follow all logs
	$(COMPOSE_CMD) logs -f

ps: ## View all container status
	$(COMPOSE_CMD) ps

clean: ## Remove all containers and images
	$(COMPOSE_CMD) down --rmi local -v --remove-orphans

join: ## Enter container shell (Interactive)
	bash -c "$$SCRIPT_JOIN"

run: guard-$(TASK_CONTAINER) ## Launch ROS task in control (Background)
	bash -c "$$SCRIPT_RUN"

stop: ## Terminate running tasks
	bash -c "$$SCRIPT_STOP"

view: ## Attach to task session
	bash -c "$$SCRIPT_VIEW"
