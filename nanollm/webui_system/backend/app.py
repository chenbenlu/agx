import asyncio
import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

import requests
import rclpy
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rclpy.node import Node
from std_msgs.msg import Bool, String


# =========================
# 工具函式
# =========================
def extract_location(text: str) -> str:
    known_places = [
        "後花園", "前庭", "大門口", "停車場", "中庭",
        "行政大樓", "實驗室", "倉庫", "操場", "屋頂"
    ]
    for place in known_places:
        if place in text:
            return place

    match = re.search(r"到(.+?)(去|做|進行|巡檢|查看|確認|$)", text)
    if match:
        return match.group(1).strip()
    return "未指定區域"


def pick_asset(text: str) -> str:
    if any(k in text for k in ["巡檢", "空拍", "俯視"]):
        return "UAV"
    if any(k in text for k in ["前往", "走過去", "到現場"]):
        return "UGV"
    return "UAV"


def build_task_payload(text: str) -> dict:
    location = extract_location(text)
    asset = pick_asset(text)
    mission_type = "inspection" if "巡檢" in text else "dispatch"
    return {
        "raw_text": text,
        "mission_type": mission_type,
        "target_location": location,
        "asset": asset,
    }


# =========================
# WebSocket 連線管理
# =========================
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_json(self, payload: dict):
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# =========================
# ROS2 Bridge Node
# =========================
class WebUIROSBridge(Node):
    def __init__(self, loop: asyncio.AbstractEventLoop, manager: ConnectionManager):
        super().__init__("webui_backend_bridge")

        self.loop = loop
        self.manager = manager

        self.user_command_pub = self.create_publisher(String, "/webui/user_command", 10)
        self.task_request_pub = self.create_publisher(String, "/webui/task_request", 10)
        self.ai_reply_pub = self.create_publisher(String, "/webui/ai_reply", 10)

        self.create_subscription(String, "/webui/ai_reply", self.on_ai_reply, 10)
        self.create_subscription(Bool, "/webui/fall_flag", self.on_fall_flag, 10)
        self.create_subscription(String, "/webui/event_text", self.on_event_text, 10)

        self.get_logger().info("WebUI ROS bridge started.")

    def push_to_frontend(self, payload: dict):
        asyncio.run_coroutine_threadsafe(
            self.manager.broadcast_json(payload),
            self.loop
        )

    def on_ai_reply(self, msg: String):
        self.push_to_frontend({
            "type": "ai_reply",
            "text": msg.data
        })

    def on_fall_flag(self, msg: Bool):
        if msg.data:
            text = "異常事件觸發！事件：行人跌倒！派遣UGV中"
            self.push_to_frontend({
                "type": "event",
                "text": text,
                "event_type": "行人跌倒",
                "action": "派遣UGV中"
            })

    def on_event_text(self, msg: String):
        self.push_to_frontend({
            "type": "event",
            "text": msg.data,
            "event_type": "自訂事件",
            "action": "已接收"
        })

    def publish_user_command(self, text: str):
        raw_msg = String()
        raw_msg.data = text
        self.user_command_pub.publish(raw_msg)

        task = build_task_payload(text)
        task_msg = String()
        task_msg.data = json.dumps(task, ensure_ascii=False)
        self.task_request_pub.publish(task_msg)

        return task

    def publish_ai_reply(self, text: str):
        msg = String()
        msg.data = text
        self.ai_reply_pub.publish(msg)


# =========================
# FastAPI
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI()
manager = ConnectionManager()

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

ros_node: Optional[WebUIROSBridge] = None
ros_thread: Optional[threading.Thread] = None


class CommandRequest(BaseModel):
    text: str


def call_llm_openai_compat(user_text: str, task: dict) -> str:
    endpoint = os.getenv("LLM_ENDPOINT", "http://localhost:8000/v1/chat/completions")
    model = os.getenv("LLM_MODEL", "local-model")
    api_key = os.getenv("LLM_API_KEY", "")

    system_prompt = (
        "你是機器人任務指揮介面的 AI 助理。"
        "請根據使用者命令，以繁體中文簡短回覆。"
        "固定格式為：任務啟動，出動設備：<設備>，地點：<地點>。"
        "不要加入多餘說明。"
    )

    user_prompt = (
        f"使用者命令：{user_text}\n"
        f"設備：{task['asset']}\n"
        f"地點：{task['target_location']}"
    )

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 64,
    }

    resp = requests.post(endpoint, headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def build_rule_reply(task: dict) -> str:
    return f"任務啟動，出動設備：{task['asset']}，地點：{task['target_location']}"


@app.on_event("startup")
async def startup_event():
    global ros_node, ros_thread

    loop = asyncio.get_running_loop()

    rclpy.init(args=None)
    ros_node = WebUIROSBridge(loop=loop, manager=manager)

    def spin_ros():
        rclpy.spin(ros_node)

    ros_thread = threading.Thread(target=spin_ros, daemon=True)
    ros_thread.start()


@app.on_event("shutdown")
async def shutdown_event():
    global ros_node
    if ros_node is not None:
        ros_node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await websocket.send_json({
        "type": "system",
        "text": "WebSocket 已連線，等待任務與事件。"
    })
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/command")
async def api_command(req: CommandRequest):
    global ros_node
    text = req.text.strip()
    if not text:
        return {"ok": False, "error": "empty text"}

    task = ros_node.publish_user_command(text)

    llm_mode = os.getenv("LLM_MODE", "rule").lower()

    try:
        if llm_mode == "openai_compat":
            reply = call_llm_openai_compat(text, task)
        else:
            reply = build_rule_reply(task)
    except Exception as e:
        reply = build_rule_reply(task)
        print(f"[WARN] LLM call failed, fallback to rule reply: {e}")

    ros_node.publish_ai_reply(reply)

    await manager.broadcast_json({
        "type": "task",
        "task": task
    })

    return {
        "ok": True,
        "task": task,
        "reply": reply
    }


@app.post("/api/simulate/fall")
async def api_simulate_fall():
    text = "異常事件觸發！事件：行人跌倒！派遣UGV中"
    await manager.broadcast_json({
        "type": "event",
        "text": text,
        "event_type": "行人跌倒",
        "action": "派遣UGV中"
    })
    return {"ok": True}