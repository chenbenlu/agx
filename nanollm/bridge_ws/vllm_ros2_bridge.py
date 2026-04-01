#!/usr/bin/env python3

import json
import threading
import requests

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class VLLMBridgeNode(Node):
    def __init__(self):
        super().__init__("vllm_ros2_bridge")

        self.declare_parameter("api_url", "http://127.0.0.1:8000/v1/chat/completions")
        self.declare_parameter("model_name", "/data/models/Cosmos-Reason2-2B")
        self.declare_parameter("default_system_prompt", "You are a helpful assistant.")

        self.api_url = self.get_parameter("api_url").get_parameter_value().string_value
        self.model_name = self.get_parameter("model_name").get_parameter_value().string_value
        self.default_system_prompt = (
            self.get_parameter("default_system_prompt").get_parameter_value().string_value
        )

        self.system_prompt = self.default_system_prompt
        self.lock = threading.Lock()

        # 訂閱 user request
        self.request_sub = self.create_subscription(
            String,
            "/llm/request",
            self.request_callback,
            10
        )

        # 訂閱 system prompt
        self.system_prompt_sub = self.create_subscription(
            String,
            "/llm/system_prompt",
            self.system_prompt_callback,
            10
        )

        # 發布模型回覆
        self.response_pub = self.create_publisher(
            String,
            "/llm/response",
            10
        )

        # 可選：發布狀態
        self.status_pub = self.create_publisher(
            String,
            "/llm/status",
            10
        )

        self.get_logger().info("vLLM ROS2 bridge started")
        self.get_logger().info(f"API URL: {self.api_url}")
        self.get_logger().info(f"Model: {self.model_name}")
        self.get_logger().info("Subscribe: /llm/system_prompt")
        self.get_logger().info("Subscribe: /llm/request")
        self.get_logger().info("Publish:   /llm/response")
        self.get_logger().info("Publish:   /llm/status")
        self.get_logger().info(f"Default system prompt: {self.system_prompt}")

    def publish_status(self, text: str):
        msg = String()
        msg.data = text
        self.status_pub.publish(msg)

    def system_prompt_callback(self, msg: String):
        new_prompt = msg.data.strip()
        if not new_prompt:
            self.get_logger().warn("Received empty system prompt, ignore")
            return

        with self.lock:
            self.system_prompt = new_prompt

        self.get_logger().info(f"Updated system prompt: {new_prompt}")
        self.publish_status(f"system_prompt_updated: {new_prompt}")

    def request_callback(self, msg: String):
        user_text = msg.data.strip()
        if not user_text:
            self.get_logger().warn("Received empty request")
            return

        with self.lock:
            current_system_prompt = self.system_prompt

        self.get_logger().info(f"Received request: {user_text}")
        self.get_logger().info(f"Using system prompt: {current_system_prompt}")

        try:
            result_text = self.call_vllm(
                system_prompt=current_system_prompt,
                user_text=user_text
            )

            out_msg = String()
            out_msg.data = result_text
            self.response_pub.publish(out_msg)

            self.get_logger().info(f"Published response: {result_text}")
            self.publish_status("inference_done")

        except Exception as e:
            err_text = f"[vLLM API error] {str(e)}"
            self.get_logger().error(err_text)

            out_msg = String()
            out_msg.data = err_text
            self.response_pub.publish(out_msg)

            self.publish_status(err_text)

    def call_vllm(self, system_prompt: str, user_text: str) -> str:
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            "temperature": 0.2,
            "max_tokens": 512,
            "stream": False
        }

        headers = {
            "Content-Type": "application/json"
        }

        response = requests.post(
            self.api_url,
            headers=headers,
            data=json.dumps(payload),
            timeout=120
        )

        response.raise_for_status()
        data = response.json()

        return data["choices"][0]["message"]["content"].strip()


def main(args=None):
    rclpy.init(args=args)
    node = VLLMBridgeNode()

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()