// ============================================================
//  差速履帶 AMR — Arduino Mega 最終生產版控制韌體
//  通訊格式：115200 bps, 8E1
//  核心防護：8ms 匯流排釋放防撞、500ms 斷線煞車看門狗
// ============================================================

#include <ArduinoJson.h>

#define ROS_SERIAL      Serial    // USB -> Jetson AGX Orin
#define MODBUS_SERIAL   Serial2   // RS485 -> 驅動器

#define LEFT_SLAVE_ID   1
#define RIGHT_SLAVE_ID  2

// --- 時序常數 ---
#define ENCODER_PUSH_MS 50   // Odom 推播頻率 (20Hz)
#define BATTERY_PUSH_MS 1000 // 電量推播頻率 (1Hz)
#define CAN_PUSH_MS     100  // CAN 充電站推播 (10Hz)
#define WATCHDOG_TIMEOUT_MS 500 

// --- 狀態變數 ---
static unsigned long last_encoder_ms = 0;
static unsigned long last_battery_ms = 0;
static unsigned long last_can_ms     = 0;
static unsigned long last_cmd_ms     = 0;

static long last_valid_p1 = 0; 
static long last_valid_p2 = 0; 

// --- JSON 接收緩衝區 (防 SRAM 破碎) ---
#define ROS_BUF_SIZE 128
static char ros_buf[ROS_BUF_SIZE];
static uint8_t ros_buf_idx = 0;

// --- 前向宣告 ---
uint16_t modbus_crc16(const uint8_t *data, uint16_t len);
bool modbus_read_position(uint8_t slave_id, long *out_position);
void driver_set_speed(uint8_t slave_id, int16_t speed);

void setup() {
    ROS_SERIAL.begin(115200);
    // 嚴格對齊 8E1 格式
    MODBUS_SERIAL.begin(115200, SERIAL_8E1);
    
    delay(1000);
    
    unsigned long now = millis();
    last_encoder_ms = now;
    last_battery_ms = now;
    last_can_ms     = now;
    last_cmd_ms     = now;

    ROS_SERIAL.println("{\"sys\":\"AMR_READY_115200_8E1\"}");
}

void loop() {
    // 1. 最高優先：處理 ROS 2 速度指令
    ros_serial_read();

    unsigned long now = millis();

    // 2. 20Hz 推播左右輪 Odom
    if (now - last_encoder_ms >= ENCODER_PUSH_MS) {
        last_encoder_ms = now;
        push_encoder();
    }

    // 3. 1Hz 推播電量
    if (now - last_battery_ms >= BATTERY_PUSH_MS) {
        last_battery_ms = now;
        push_battery();
    }

    // 4. 10Hz 推播 CAN 充電資料
    if (now - last_can_ms >= CAN_PUSH_MS) {
        last_can_ms = now;
        push_can_data();
    }

    // 5. 看門狗安全機制
    watchdog_check();
}

// ============================================================
//  ROS 2 邏輯區塊
// ============================================================

void ros_serial_read() {
    while (ROS_SERIAL.available() > 0) {
        char c = (char)ROS_SERIAL.read();
        if (c == '\n') {
            ros_buf[ros_buf_idx] = '\0';
            if (ros_buf_idx > 0) parse_ros_command(ros_buf);
            ros_buf_idx = 0;
        } else if (c != '\r') {
            if (ros_buf_idx < ROS_BUF_SIZE - 1) ros_buf[ros_buf_idx++] = c;
            else ros_buf_idx = 0; // 溢位保護
        }
    }
}

void parse_ros_command(const char *json_str) {
    StaticJsonDocument<128> doc;
    DeserializationError err = deserializeJson(doc, json_str);

    if (err) return; // 忽略錯誤格式

    if (doc.containsKey("ls") && doc.containsKey("rs")) {
        int16_t ls = (int16_t)doc["ls"].as<int>();
        int16_t rs = (int16_t)doc["rs"].as<int>();

        // 寫入左輪速度
        driver_set_speed(LEFT_SLAVE_ID, ls);
        
        // ⚠️ 寫入防撞延遲
        delay(8);
        
        // 寫入右輪速度
        driver_set_speed(RIGHT_SLAVE_ID, rs);

        // 刷新看門狗
        last_cmd_ms = millis();
    }
}

void watchdog_check() {
    unsigned long now = millis();
    if ((now - last_cmd_ms) > WATCHDOG_TIMEOUT_MS) {
        // 緊急煞車
        driver_set_speed(LEFT_SLAVE_ID, 0);
        delay(8);
        driver_set_speed(RIGHT_SLAVE_ID, 0);
        
        // 每 500ms 重發一次煞車，避免佔用總線
        last_cmd_ms = now;
    }
}

void push_encoder() {
    long p1, p2;

    if (modbus_read_position(LEFT_SLAVE_ID, &p1)) last_valid_p1 = p1;
    
    // ⚠️ 讀取防撞延遲
    delay(8); 
    
    if (modbus_read_position(RIGHT_SLAVE_ID, &p2)) last_valid_p2 = p2;

    ROS_SERIAL.print("{\"p1\":"); ROS_SERIAL.print(last_valid_p1);
    ROS_SERIAL.print(",\"p2\":"); ROS_SERIAL.print(last_valid_p2);
    ROS_SERIAL.println("}");
}

void push_battery() {
    float voltage = 24.5; // 替換為實際讀取邏輯
    ROS_SERIAL.print("{\"pow\":");
    ROS_SERIAL.print(voltage, 1);
    ROS_SERIAL.println("}");
}

void push_can_data() {
    float can_v = 0.0; // 替換為實際 CAN 邏輯
    float can_w = 0.0;
    int c_st = 0;
    ROS_SERIAL.print("{\"can_v\":"); ROS_SERIAL.print(can_v, 2);
    ROS_SERIAL.print(",\"can_w\":"); ROS_SERIAL.print(can_w, 2);
    ROS_SERIAL.print(",\"c_st\":"); ROS_SERIAL.print(c_st);
    ROS_SERIAL.println("}");
}

// ============================================================
//  底層 Modbus 通訊區塊 (已包含 8ms 與 10ms 物理防撞優化)
// ============================================================

uint16_t modbus_crc16(const uint8_t *data, uint16_t len) {
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i];
        for (uint8_t j = 0; j < 8; j++) {
            if (crc & 0x0001) crc = (crc >> 1) ^ 0xA001;
            else crc >>= 1;
        }
    }
    return crc;
}

bool modbus_read_position(uint8_t slave_id, long *out_position) {
    uint8_t req[8] = {slave_id, 0x03, 0x00, 0x24, 0x00, 0x02, 0x00, 0x00};
    uint16_t crc = modbus_crc16(req, 6);
    req[6] = crc & 0xFF; req[7] = (crc >> 8) & 0xFF;

    while (MODBUS_SERIAL.available()) MODBUS_SERIAL.read(); 
    MODBUS_SERIAL.write(req, 8);
    MODBUS_SERIAL.flush();

    uint8_t resp[9];
    uint8_t idx = 0;
    unsigned long t0 = millis();

    while (idx < 9 && (millis() - t0) < 20) {
        if (MODBUS_SERIAL.available()) resp[idx++] = MODBUS_SERIAL.read();
    }

    if (idx < 9) return false;
    uint16_t recv_crc = (uint16_t)resp[7] | ((uint16_t)resp[8] << 8);
    if (recv_crc != modbus_crc16(resp, 7)) return false;
    if (resp[0] != slave_id || resp[1] != 0x03) return false;

    uint8_t raw[4] = {resp[6], resp[5], resp[4], resp[3]};
    memcpy(out_position, raw, 4);
    return true;
}

void driver_set_speed(uint8_t slave_id, int16_t speed) {
    uint8_t req[8] = {slave_id, 0x06, 0x00, 0x43, (uint8_t)(speed >> 8), (uint8_t)(speed & 0xFF), 0x00, 0x00};
    uint16_t crc = modbus_crc16(req, 6);
    req[6] = crc & 0xFF; req[7] = (crc >> 8) & 0xFF;

    while (MODBUS_SERIAL.available()) MODBUS_SERIAL.read();
    MODBUS_SERIAL.write(req, 8);
    MODBUS_SERIAL.flush();

    // ⚠️ 10ms 確保 Echo 徹底清空
    uint8_t discarded = 0;
    unsigned long t0 = millis();
    while (discarded < 8 && (millis() - t0) < 10) {
        if (MODBUS_SERIAL.available()) {
            MODBUS_SERIAL.read();
            discarded++;
        }
    }
}
