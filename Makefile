# ==============================================================================
#  AGX ROS Control Interface
# ==============================================================================

# --- [Configuration] ---
PROJECT_NAME   := agx_ros
TASK_CONTAINER := control
SERVICE_NAME   ?= control

# Docker Buildkit
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# --- [Auto-Detection] ---
CURRENT_CONTEXT := $(shell docker context show)
MODE := pc
ENV_FILE := .env

ifneq (,$(findstring agx,$(CURRENT_CONTEXT)))
    MODE := agx
    ENV_FILE := .env.agx
else ifeq ($(shell uname -m), aarch64)
    MODE := agx
    ENV_FILE := .env.agx
endif

# --- [Compose Commands] ---
# 根目錄 orchestrator (全部)
COMPOSE_CMD := docker compose --env-file $(ENV_FILE) -p $(PROJECT_NAME)
# 子目錄 (指定 service via s=xxx)
# 用法: make up-one s=planning
COMPOSE_SUB = docker compose --env-file $(CURDIR)/$(ENV_FILE) -f $(s)/docker-compose.yaml -p $(PROJECT_NAME)

TASK_EXEC   := docker exec -it $(TASK_CONTAINER) bash -ic

# --- [Make Settings] ---
.DEFAULT_GOAL := help
.SILENT:
.PHONY: help build up rebuild down join logs ps clean run plan stop view dashboard guard-%

# ==============================================================================
#  Logic Definitions (Shell Scripts inside Makefile)
# ==============================================================================

# 1. RUN SCRIPT
define SCRIPT_RUN
    echo "=========================================="
    echo " AGX Task Launcher"
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
    LIST=$$(tmux ls -F "#{session_name}" 2>/dev/null | grep -E "^(agx_|plan_)" || true)
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
    LIST=$$(tmux ls -F "#{session_name}" 2>/dev/null | grep -E "^(agx_|plan_)" || true)
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
SERVICES := control bridge planning foxglove vlm nanollm

# --- [共通選單 Header] ---
define SERVICE_MENU
    echo "1) control    - ROS 1 底層控制"
    echo "2) bridge     - ROS 1 <-> ROS 2 橋樑"
    echo "3) planning   - ROS 2 高階規劃"
    echo "4) foxglove   - 資料視覺化"
    echo "5) vlm        - Isaac ROS 視覺加速"
    echo "6) nanollm    - Nano LLM"
endef

# 5. UP SCRIPT (多選)
define SCRIPT_UP
    echo "=========================================="
    echo " AGX Service Launcher ($(MODE) mode)"
    echo "=========================================="
    $(SERVICE_MENU)
    echo "------------------------------------------"
    echo "a) Start ALL    q) Quit"
    echo "------------------------------------------"
    read -p "Select service(s) [1-6/a/q, 可多選如 1 3 5]: " INPUT
    if [ "$$INPUT" = "q" ]; then exit 0; fi
    if [ "$$INPUT" = "a" ]; then
        echo "[Info] Starting ALL services..."
        $(COMPOSE_CMD) up -d
        echo "[Info] All services started."
        exit 0
    fi
    CHOICES=$$(echo "$$INPUT" | tr ',' ' ')
    FOLDERS="control bridge planning foxglove vlm nanollm"
    COUNT=0
    for c in $$CHOICES; do
        TARGET=$$(echo "$$FOLDERS" | tr ' ' '\n' | sed -n "$${c}p")
        if [ -z "$$TARGET" ]; then echo "[Warn] Skipping invalid: $$c"; continue; fi
        echo "[Info] Starting $$TARGET..."
        docker compose --env-file $(CURDIR)/$(ENV_FILE) -f $$TARGET/docker-compose.yaml -p $(PROJECT_NAME) up -d
        COUNT=$$((COUNT + 1))
    done
    echo "[Info] $$COUNT service(s) started."
endef
export SCRIPT_UP

# 6. DOWN SCRIPT (多選)
define SCRIPT_DOWN
    echo "=========================================="
    echo " AGX Service Stopper"
    echo "=========================================="
    $(SERVICE_MENU)
    echo "------------------------------------------"
    echo "a) Stop ALL    q) Quit"
    echo "------------------------------------------"
    read -p "Select service(s) [1-6/a/q, 可多選如 1 3 5]: " INPUT
    if [ "$$INPUT" = "q" ]; then exit 0; fi
    if [ "$$INPUT" = "a" ]; then
        echo "[Info] Stopping ALL services..."
        $(COMPOSE_CMD) down --remove-orphans
        echo "[Info] All services stopped."
        exit 0
    fi
    CHOICES=$$(echo "$$INPUT" | tr ',' ' ')
    FOLDERS="control bridge planning foxglove vlm nanollm"
    COUNT=0
    for c in $$CHOICES; do
        TARGET=$$(echo "$$FOLDERS" | tr ' ' '\n' | sed -n "$${c}p")
        if [ -z "$$TARGET" ]; then echo "[Warn] Skipping invalid: $$c"; continue; fi
        echo "[Info] Stopping $$TARGET..."
        docker compose --env-file $(CURDIR)/$(ENV_FILE) -f $$TARGET/docker-compose.yaml -p $(PROJECT_NAME) down --remove-orphans
        COUNT=$$((COUNT + 1))
    done
    echo "[Info] $$COUNT service(s) stopped."
endef
export SCRIPT_DOWN

# 7. BUILD SCRIPT (多選)
define SCRIPT_BUILD
    echo "=========================================="
    echo " AGX Image Builder ($(MODE) mode)"
    echo "=========================================="
    $(SERVICE_MENU)
    echo "------------------------------------------"
    echo "a) Build ALL    q) Quit"
    echo "------------------------------------------"
    read -p "Select service(s) [1-6/a/q, 可多選如 1 3 5]: " INPUT
    if [ "$$INPUT" = "q" ]; then exit 0; fi
    if [ "$$INPUT" = "a" ]; then
        echo "[Info] Building ALL images..."
        $(COMPOSE_CMD) build
        echo "[Info] All images built."
        exit 0
    fi
    CHOICES=$$(echo "$$INPUT" | tr ',' ' ')
    FOLDERS="control bridge planning foxglove vlm nanollm"
    COUNT=0
    for c in $$CHOICES; do
        TARGET=$$(echo "$$FOLDERS" | tr ' ' '\n' | sed -n "$${c}p")
        if [ -z "$$TARGET" ]; then echo "[Warn] Skipping invalid: $$c"; continue; fi
        echo "[Info] Building $$TARGET..."
        docker compose --env-file $(CURDIR)/$(ENV_FILE) -f $$TARGET/docker-compose.yaml -p $(PROJECT_NAME) build
        COUNT=$$((COUNT + 1))
    done
    echo "[Info] $$COUNT image(s) built."
endef
export SCRIPT_BUILD

# 8. REBUILD SCRIPT (多選)
define SCRIPT_REBUILD
    echo "=========================================="
    echo " AGX Service Rebuilder ($(MODE) mode)"
    echo "=========================================="
    $(SERVICE_MENU)
    echo "------------------------------------------"
    echo "a) Rebuild ALL    q) Quit"
    echo "------------------------------------------"
    read -p "Select service(s) [1-6/a/q, 可多選如 1 3 5]: " INPUT
    if [ "$$INPUT" = "q" ]; then exit 0; fi
    if [ "$$INPUT" = "a" ]; then
        echo "[Info] Rebuilding ALL services..."
        $(COMPOSE_CMD) up -d --build --force-recreate
        echo "[Info] All services rebuilt."
        exit 0
    fi
    CHOICES=$$(echo "$$INPUT" | tr ',' ' ')
    FOLDERS="control bridge planning foxglove vlm nanollm"
    COUNT=0
    for c in $$CHOICES; do
        TARGET=$$(echo "$$FOLDERS" | tr ' ' '\n' | sed -n "$${c}p")
        if [ -z "$$TARGET" ]; then echo "[Warn] Skipping invalid: $$c"; continue; fi
        echo "[Info] Rebuilding $$TARGET..."
        docker compose --env-file $(CURDIR)/$(ENV_FILE) -f $$TARGET/docker-compose.yaml -p $(PROJECT_NAME) up -d --build --force-recreate
        COUNT=$$((COUNT + 1))
    done
    echo "[Info] $$COUNT service(s) rebuilt."
endef
export SCRIPT_REBUILD

# ==============================================================================
#  Targets
# ==============================================================================

help: ## Show available commands
	echo "AGX ROS Control Interface"
	echo "   Task Target: $(TASK_CONTAINER)"
	echo "   Context:     $(CURRENT_CONTEXT)"
	echo "   Mode:        $(MODE)"
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
	echo "  make plan               Launch planning task"
	echo "  make stop               Terminate running tasks"
	echo "  make view               Attach to task session"
	echo ""
	echo "--- Web Dashboard ---"
	echo "  make dashboard          啟動 Web 控制面板 (port 8080)"

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

dashboard: ## Launch Web Dashboard (port 8080)
	python3 dashboard.py

clean: ## Remove all containers and images
	$(COMPOSE_CMD) down --rmi local -v --remove-orphans

# ==============================================================================
#  Task Actions
# ==============================================================================

PLAN_EXEC := docker exec -it planning bash -ic

# 9. PLANNING TASK SCRIPT
define SCRIPT_PLAN
    echo "=========================================="
    echo " Planning Task Launcher"
    echo " Target: planning"
    echo "=========================================="
    echo "1) Lidar 啟動測試     (urg_node2)"
    echo "2) SLAM Bringup       (slam_bringup)"
    echo "3) Keyboard Control   (teleop_twist_keyboard)"
    echo "4) Save Map           (map_saver)"
    echo "------------------------------------------"
    echo "a) Launch ALL    q) Quit"
    echo "------------------------------------------"
    read -p "Select task(s) [1-4/a/q, 可多選如 1 2]: " INPUT
    if [ "$$INPUT" = "q" ]; then exit 0; fi
    if [ "$$INPUT" = "a" ]; then INPUT="1 2 3 4"; fi
    CHOICES=$$(echo "$$INPUT" | tr ',' ' ')
    LAUNCHED=0
    for choice in $$CHOICES; do
        S_NAME=""; CMD_MAIN=""
        case $$choice in
            1) S_NAME="plan_lidar";    CMD_MAIN="ros2 launch urg_node2 urg_node2.launch.py";;
            2) S_NAME="plan_slam";     CMD_MAIN="ros2 launch car_control slam_bringup.launch.py";;
            3) S_NAME="plan_keyboard"; CMD_MAIN="ros2 run teleop_twist_keyboard teleop_twist_keyboard";;
            4) S_NAME="plan_savemap";  CMD_MAIN="ros2 run nav2_map_server map_saver_cli -f /root/ros2_ws/src/car_control/config/my_map";;
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
        tmux send-keys -t $$S_NAME:0 "$(PLAN_EXEC) '$$CMD_MAIN'" C-m
        LAUNCHED=$$((LAUNCHED + 1))
    done
    echo "[Info] $$LAUNCHED task(s) launched."
    echo "       Use 'make view' to monitor, 'make stop' to terminate."
endef
export SCRIPT_PLAN

join: ## Enter container shell (Interactive)
	bash -c "$$SCRIPT_JOIN"

run: guard-$(TASK_CONTAINER) ## Launch ROS task in control (Background)
	bash -c "$$SCRIPT_RUN"

plan: guard-planning ## Launch ROS task in planning (Background)
	bash -c "$$SCRIPT_PLAN"

stop: ## Terminate running tasks
	bash -c "$$SCRIPT_STOP"

view: ## Attach to task session
	bash -c "$$SCRIPT_VIEW"