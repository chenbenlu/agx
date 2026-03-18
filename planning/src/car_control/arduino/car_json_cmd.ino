// ============================================================
//  car_json_cmd.ino
//  差速履帶 AMR — Arduino Mega 底層控制韌體
//
//  硬體配置：
//    Serial  (USB)    → Jetson AGX Orin (ROS 2), 115200 baud
//    Serial2 (RS485)  → AQMD6030BLS-E2 × 2, 115200 baud, 8E1
//
//  功能：
//    1. 接收 ROS 2 JSON 速度命令：{"ls":<RPM>,"rs":<RPM>}
//    2. 20Hz 主動推播 encoder：{"p1":<左輪ticks>,"p2":<右輪ticks>}
//    3. 500ms 無命令自動煞車（看門狗）
//
//  設計原則：
//    - 禁用 Arduino String 物件（防止 SRAM 碎片化）
//    - 所有 I/O 皆為 millis() 非阻塞式
//    - 通訊失敗時保留上一次有效 encoder 值
// ============================================================

#include <ArduinoJson.h>

// ============================================================
//  硬體定義
// ============================================================
#define ROS_SERIAL      Serial    // USB → Jetson AGX Orin
#define MODBUS_SERIAL   Serial2   // RS485 → 馬達驅動器

#define ROS_BAUD        115200
#define MODBUS_BAUD     115200
#define MODBUS_CONFIG   SERIAL_8E1  // 偶校驗, 1 停止位 (驅動器已解封設定)

// 驅動器 Modbus 站號
#define LEFT_SLAVE_ID   1
#define RIGHT_SLAVE_ID  2

// Modbus 暫存器地址
#define REG_POSITION    0x0024  // 轉動位置 (功能碼 0x03, 讀 2 Word = 4 Bytes)
#define REG_SPEED       0x0043  // 換向頻率 (功能碼 0x06, 寫 1 Word = 2 Bytes)

// ============================================================
//  時序常數
// ============================================================
#define ENCODER_PUSH_MS         50   // Encoder 推播週期 (50ms = 20Hz)
#define WATCHDOG_TIMEOUT_MS     500  // 看門狗逾時：超過此時間無命令 → 煞車
#define MODBUS_READ_TIMEOUT_MS  20   // Modbus 讀取回應逾時
#define MODBUS_ECHO_TIMEOUT_MS  5    // 0x06 寫入 Echo 丟棄逾時

// ============================================================
//  ROS 接收緩衝區（純 char 陣列，禁止 String）
// ============================================================
#define ROS_BUF_SIZE 128
static char  ros_buf[ROS_BUF_SIZE];
static uint8_t ros_buf_idx = 0;

// ============================================================
//  狀態變數
// ============================================================
static unsigned long last_encoder_ms = 0;  // 上次 encoder 推播時間
static unsigned long last_cmd_ms     = 0;  // 上次收到有效命令時間

// 上一次有效的 encoder 數值
// → 通訊失敗或 CRC 錯誤時保留此值，防止 ROS 座標飛走
static long last_valid_p1 = 0;  // 左輪
static long last_valid_p2 = 0;  // 右輪

// ============================================================
//  前向宣告
// ============================================================
uint16_t modbus_crc16(const uint8_t *data, uint16_t len);
bool     modbus_read_position(uint8_t slave_id, long *out_position);
void     driver_set_speed(uint8_t slave_id, int16_t speed);
void     push_encoder();
void     ros_serial_read();
void     parse_ros_command(const char *json_str);
void     watchdog_check();

// ============================================================
//  setup()
// ============================================================
void setup()
{
    // 初始化 ROS 通訊 (USB Serial)
    ROS_SERIAL.begin(ROS_BAUD);

    // 初始化 Modbus RS485 通訊
    // AQMD6030BLS-E2 解封後：115200, 偶校驗, 1 停止位
    MODBUS_SERIAL.begin(MODBUS_BAUD, MODBUS_CONFIG);

    // 等待 Serial 就緒
    delay(500);

    // 初始化時間戳
    last_encoder_ms = millis();
    last_cmd_ms     = millis();  // 給看門狗一個初始值，避免開機立刻觸發

    ROS_SERIAL.println("{\"status\":\"Arduino Ready\"}");
}

// ============================================================
//  loop() — 主迴圈，全部非阻塞
// ============================================================
void loop()
{
    // ① 最高優先：接收並處理 ROS 速度指令
    //    使用 char 陣列逐字元累積，遇到 '\n' 即解析
    ros_serial_read();

    // ② 定時推播 encoder（20Hz, 非阻塞 millis 計時）
    unsigned long now = millis();
    if (now - last_encoder_ms >= ENCODER_PUSH_MS) {
        last_encoder_ms = now;
        push_encoder();
    }

    // ③ 看門狗：超過 500ms 無命令 → 緊急煞車
    // watchdog_check();
}

// ============================================================
//  Modbus CRC16 校驗函式
//
//  演算法：標準 Modbus RTU CRC-16
//  多項式：0xA001 (反射型)
//  初始值：0xFFFF
//  結果格式：低位元組在前 (Little-Endian in frame)
// ============================================================
uint16_t modbus_crc16(const uint8_t *data, uint16_t len)
{
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i];
        for (uint8_t j = 0; j < 8; j++) {
            if (crc & 0x0001) {
                crc = (crc >> 1) ^ 0xA001;
            } else {
                crc >>= 1;
            }
        }
    }
    return crc;
}

// ============================================================
//  modbus_read_position()
//
//  讀取驅動器的「轉動位置」暫存器 (0x0024, 2 Words)
//  回應封包格式 (9 Bytes)：
//    [SlaveID, 0x03, 0x04, D1H, D1L, D2H, D2L, CRCL, CRCH]
//
//  @param slave_id      驅動器站號 (1=左, 2=右)
//  @param out_position  輸出的 32-bit 編碼器脈衝數
//  @return true=讀取成功, false=逾時或CRC錯誤
// ============================================================
bool modbus_read_position(uint8_t slave_id, long *out_position)
{
    // --- 組建 Modbus 0x03 讀取請求 (8 Bytes) ---
    uint8_t req[8];
    req[0] = slave_id;
    req[1] = 0x03;                      // 功能碼：讀保持暫存器
    req[2] = (REG_POSITION >> 8) & 0xFF; // 暫存器地址高位元組
    req[3] = REG_POSITION & 0xFF;        // 暫存器地址低位元組
    req[4] = 0x00;                       // 讀取數量高位元組
    req[5] = 0x02;                       // 讀取數量低位元組 (2 Word = 4 Bytes)
    uint16_t crc = modbus_crc16(req, 6);
    req[6] = crc & 0xFF;                 // CRC 低位元組
    req[7] = (crc >> 8) & 0xFF;          // CRC 高位元組

    // --- 清空接收緩衝，防止殘留資料污染 ---
    while (MODBUS_SERIAL.available()) {
        MODBUS_SERIAL.read();
    }

    // --- 發送請求 ---
    MODBUS_SERIAL.write(req, 8);
    MODBUS_SERIAL.flush();  // 等待 TX 完成（硬體層級）

    // --- 非阻塞式等待 9 Bytes 回應 ---
    uint8_t resp[9];
    uint8_t idx = 0;
    unsigned long t0 = millis();

    while (idx < 9 && (millis() - t0) < MODBUS_READ_TIMEOUT_MS) {
        if (MODBUS_SERIAL.available()) {
            resp[idx++] = MODBUS_SERIAL.read();
        }
    }

    // 逾時：未收齊 9 Bytes
    if (idx < 9) return false;

    // --- CRC 校驗 ---
    uint16_t recv_crc = (uint16_t)resp[7] | ((uint16_t)resp[8] << 8);
    uint16_t calc_crc = modbus_crc16(resp, 7);
    if (recv_crc != calc_crc) return false;

    // --- 驗證封包頭 ---
    if (resp[0] != slave_id || resp[1] != 0x03 || resp[2] != 0x04) return false;

    // --- 提取 32-bit 位置 (Big-Endian → Little-Endian) ---
    // Modbus 回應: resp[3]=MSB ... resp[6]=LSB
    // Arduino Mega 為 Little-Endian，需反轉位元組順序
    uint8_t raw[4];
    raw[0] = resp[6];  // LSB
    raw[1] = resp[5];
    raw[2] = resp[4];
    raw[3] = resp[3];  // MSB
    memcpy(out_position, raw, 4);

    return true;
}

// ============================================================
//  driver_set_speed()
//
//  使用 Modbus 0x06 寫入「換向頻率」暫存器 (0x0043)
//  驅動器會立刻 Echo 回傳完全相同的 8 Bytes，
//  必須讀出並丟棄，防止殘留在緩衝區污染 Odom 讀取。
//
//  @param slave_id  驅動器站號
//  @param speed     帶符號 16-bit 速度值 (RPM)
// ============================================================
void driver_set_speed(uint8_t slave_id, int16_t speed)
{
    // --- 組建 Modbus 0x06 寫入請求 (8 Bytes) ---
    uint8_t req[8];
    req[0] = slave_id;
    req[1] = 0x06;                     // 功能碼：寫單一暫存器
    req[2] = (REG_SPEED >> 8) & 0xFF;  // 暫存器地址高位元組
    req[3] = REG_SPEED & 0xFF;         // 暫存器地址低位元組
    req[4] = (speed >> 8) & 0xFF;      // 數值高位元組 (Big-Endian signed)
    req[5] = speed & 0xFF;             // 數值低位元組
    uint16_t crc = modbus_crc16(req, 6);
    req[6] = crc & 0xFF;               // CRC 低位元組
    req[7] = (crc >> 8) & 0xFF;        // CRC 高位元組

    // --- 清空接收緩衝 ---
    while (MODBUS_SERIAL.available()) {
        MODBUS_SERIAL.read();
    }

    // --- 發送命令 ---
    MODBUS_SERIAL.write(req, 8);
    MODBUS_SERIAL.flush();  // 等待 TX 完成

    // --- 丟棄驅動器的 8 Bytes Echo 回應 ---
    // 使用 millis() 非阻塞迴圈，5ms 逾時
    // 如果不讀出這些 Echo，它們會殘留在 Serial2 接收緩衝區，
    // 導致下次 modbus_read_position() 讀到錯誤資料！
    uint8_t discarded = 0;
    unsigned long t0 = millis();
    while (discarded < 8 && (millis() - t0) < MODBUS_ECHO_TIMEOUT_MS) {
        if (MODBUS_SERIAL.available()) {
            MODBUS_SERIAL.read();  // 讀出即丟棄
            discarded++;
        }
    }
}

// ============================================================
//  push_encoder()
//
//  主動推播 encoder 至 ROS 2 (由 loop 中的 millis 計時器驅動)
//  格式：{"p1":<左輪ticks>,"p2":<右輪ticks>}\n
//
//  關鍵安全機制：
//    若 Modbus 讀取失敗（逾時 / CRC 錯誤），保留上一次的
//    有效數值繼續回傳，絕對不會回傳 0 導致 ROS 座標暴跳。
// ============================================================
void push_encoder()
{
    long p1, p2;

    // 讀取左輪 encoder
    if (modbus_read_position(LEFT_SLAVE_ID, &p1)) {
        last_valid_p1 = p1;  // 更新有效值
    }
    // 失敗時 last_valid_p1 維持不變

    // 讀取右輪 encoder
    if (modbus_read_position(RIGHT_SLAVE_ID, &p2)) {
        last_valid_p2 = p2;  // 更新有效值
    }
    // 失敗時 last_valid_p2 維持不變

    // --- 以 Serial.print 輸出 JSON（避免使用 String 物件）---
    // 格式：{"p1":12345,"p2":12340}\n
    ROS_SERIAL.print("{\"p1\":");
    ROS_SERIAL.print(last_valid_p1);
    ROS_SERIAL.print(",\"p2\":");
    ROS_SERIAL.print(last_valid_p2);
    ROS_SERIAL.println("}");
}

// ============================================================
//  ros_serial_read()
//
//  非阻塞式逐字元讀取 ROS Serial 資料，
//  遇到 '\n' 時觸發 JSON 解析。
//  使用 char 陣列而非 String 物件，防止 SRAM 碎片化。
// ============================================================
void ros_serial_read()
{
    while (ROS_SERIAL.available() > 0) {
        char c = (char)ROS_SERIAL.read();

        if (c == '\n') {
            // 完整一行，進行解析
            ros_buf[ros_buf_idx] = '\0';  // Null 結尾

            if (ros_buf_idx > 0) {
                parse_ros_command(ros_buf);
            }

            ros_buf_idx = 0;  // 重置索引
        }
        else if (c == '\r') {
            // 忽略 '\r'（Windows 換行相容）
        }
        else {
            // 累積字元到緩衝區
            if (ros_buf_idx < ROS_BUF_SIZE - 1) {
                ros_buf[ros_buf_idx++] = c;
            } else {
                // 緩衝區溢位 → 丟棄目前累積的資料，防止越界
                ros_buf_idx = 0;
            }
        }
    }
}

// ============================================================
//  parse_ros_command()
//
//  使用 ArduinoJson 解析 ROS 2 下發的速度 JSON
//  預期格式：{"ls":<左輪RPM>,"rs":<右輪RPM>}
//  （kinematics_node 實際發送 {"m":0,"ls":RPM,"rs":RPM}，
//   本函式僅提取 ls/rs，忽略其他欄位）
//
//  解析成功後：
//    1. 寫入左/右輪驅動器速度
//    2. 重置看門狗計時器
// ============================================================
void parse_ros_command(const char *json_str)
{
    // StaticJsonDocument 使用 Stack 記憶體，不會碎片化
    StaticJsonDocument<128> doc;
    DeserializationError err = deserializeJson(doc, json_str);

    if (err) {
        // JSON 格式錯誤 → 靜默忽略（可能是 Arduino 開機訊息被回讀）
        return;
    }

    // 檢查是否包含速度欄位
    if (doc.containsKey("ls") && doc.containsKey("rs")) {
        int16_t ls = (int16_t)doc["ls"].as<int>();
        int16_t rs = (int16_t)doc["rs"].as<int>();

        // 寫入左輪速度
        driver_set_speed(LEFT_SLAVE_ID, ls);

        // 寫入右輪速度
        driver_set_speed(RIGHT_SLAVE_ID, rs);

        // 重置看門狗計時器（表示 ROS 仍然在線）
        last_cmd_ms = millis();
    }
}

// ============================================================
//  watchdog_check()
//
//  安全看門狗：
//    若超過 WATCHDOG_TIMEOUT_MS (500ms) 沒有收到來自 ROS 2
//    的有效速度命令，強制將左右馬達設為零速，防止失控暴衝。
//
//    觸發後每 500ms 重送一次煞車命令，直到 ROS 恢復連線。
//    對於 50kg 的 AMR，這是最基本的安全保障。
// ============================================================
void watchdog_check()
{
    unsigned long now = millis();

    if ((now - last_cmd_ms) > WATCHDOG_TIMEOUT_MS) {
        // 緊急煞車
        driver_set_speed(LEFT_SLAVE_ID, 0);
        driver_set_speed(RIGHT_SLAVE_ID, 0);

        // 重設計時器，避免每次 loop 都發送煞車指令
        // 改為每 500ms 重送一次，既保證安全又不佔用過多 Modbus 頻寬
        last_cmd_ms = now;
    }
}