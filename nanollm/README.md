## webui
`cd webui_system && uvicorn backend.app:app --host 0.0.0.0 --port 8089`

## vllm ros2 bridge
`python bridge_ws/vllm_ros2_bridge.py`

```bash
ros2 topic pub /llm/request std_msgs/msg/String "{data: '請描述這段影片中的人物、動作與是否有異常事件。'}" --once
ros2 topic pub /llm/video_uri std_msgs/msg/String "{data: 'file:///workspaces/cosmos_ws/video/sec_fly.mp4'}" --once
ros2 topic pub /llm/request std_msgs/msg/String "{data: '請描述路上特徵，與是否有人在草皮上跌倒(異常事件)。'}" --once
ros2 topic echo /llm/response
```
ros2 topic pub /llm/request std_msgs/msg/String "{data: '請根據影片做完整分析，務必使用繁體中文，並嚴格依照以下格式輸出：

1. 場景摘要：至少 3 句
2. 主要物件與位置：至少 3 點
3. 正在發生的動作流程：至少 5 點，依時間順序描述
4. 是否有異常事件：若有，說明原因；若無，也要明確說「未觀察到異常」
5. 建議後續動作：至少 3 點

請勿只回答一兩句，也不要省略任何段落。'}" --once

請根據影片做完整分析，務必使用繁體中文，並嚴格依照以下格式輸出：

1. 場景摘要：至少 3 句
2. 主要物件與位置：至少 3 點
3. 正在發生的動作流程：至少 5 點，依時間順序描述
4. 是否有異常事件：若有，說明原因；若無，也要明確說「未觀察到異常」
5. 建議後續動作：至少 3 點

請勿只回答一兩句，也不要省略任何段落。