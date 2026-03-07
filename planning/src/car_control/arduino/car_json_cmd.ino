// modbus_宣告區
#include <SoftwareSerial.h>
#define modbus_ttl Serial2
//SoftwareSerial modbus_ttl(10, 11);  // RX = 10, TX = 11
String modbus_msg = "";
// ------------

// json_控制_宣告區
#include <ArduinoJson.h>
DeserializationError json_control_error;
StaticJsonDocument<256> json_data;
String json_msg = "";
// ----------------
// 充電站_宣告區
#include <mcp_can.h>
#include <SPI.h>
const int SPI_CS_PIN = 10;
MCP_CAN CAN(SPI_CS_PIN);
bool if_exe_charge = false;
// ----------------
void setup(){
    Serial.begin(115200);
    modbus_init(); delay(1000);
    Charging_Station_init();
}
void loop(){
    json_control_read();
    // 是否進入充電站
    if(if_exe_charge){
        Charging_Station_read();
    }
    // -------------
}

// json_控制_工作區
void json_control_read(){
    if (Serial.available() > 0){
        char data = Serial.read();
        if(data == '\n'){
            json_control_error = deserializeJson(json_data,json_msg);
            if(!json_control_error){
                json_car_set_speed(json_data["m"],
                                   json_data["ls"],
                                   json_data["rs"]);
                json_car_set_pos(   json_data["m"],
                                    json_data["s"],
                                    json_data["lp"],
                                    json_data["rp"]);
                json_read_pos(json_data["rpos"]);
                json_read_pow(json_data["rpow"]);
                json_if_charge(json_data["charge"]);
            }
            json_msg = "";
        }else{
            json_msg += data;
        }
    }
}
void json_if_charge(String if_charge){
    // {"charge" : 1}
    if(if_charge != "null"){
        if(if_charge.toInt() == 1){
            Serial.println("啟用充電站功能");
            if_exe_charge = true;
        }else{
            Serial.println("關閉充電站功能");
            car_set_speed(1, 0, 0); // 停止車輛移動
            if_exe_charge = false;
        }
        
    }
}
void json_read_pow(String if_read){
    // {"rpow" : 1}
    if(if_read != "null"){
        driver_read_pow();
    }
}
void json_read_pos(String addr){
    // {"rpos" : 1}
    if(addr != "null"){
        driver_read_pos(addr.toInt());
    }
}
void json_car_set_speed(String mode, String left_speed, String right_speed){
    // {"m" : 0 , "ls" : 0 , "rs" : 0 }
    if(mode != "null" &&
       left_speed != "null" &&
       right_speed != "null"){
       car_set_speed(mode.toInt(), left_speed.toInt(), right_speed.toInt());
    }
}
void json_car_set_pos(String mode, String speed , String left_pos, String right_pos){
    // {"m" : 0 , "s" : 0 , "lp" : 0 , "rp" : 0 }
    if(mode != "null" &&
        speed != "null" &&
        left_pos != "null" &&
        right_pos != "null"){
       car_set_pos(mode.toInt(), speed.toInt() , left_pos.toInt(), right_pos.toInt());
    }
    
}
// ------------------
// 充電站_工作區
void Charging_Station_init() {
  // 初始化 MCP2515：模式=任意、速率=1Mbps、水晶頻率=8MHz
  while (CAN_OK != CAN.begin(MCP_ANY, CAN_1000KBPS, MCP_8MHZ)) {
    Serial.println("CAN BUS init fail, retrying...");
    delay(100);
  }
  Serial.println("CAN BUS 1Mbps init ok!");

  // 可選：設定為正常模式
  CAN.setMode(MCP_NORMAL);
}
void Charging_Station_read() {
    long unsigned int rxId;
    unsigned char len = 0;
    unsigned char data[8];

    if (CAN_MSGAVAIL == CAN.checkReceive()) {
        CAN.readMsgBuf(&rxId, &len, data);  // 讀取資料

        if (rxId == 0x182) {
            // 解析資料_開始
            int16_t linear_raw = (data[0] << 8) | data[1];
            float linear_speed = linear_raw * 0.001;

            byte contact_state = data[2];
            String contact_str;
            switch (contact_state) {
                case 0xAA: contact_str = "接觸充電區"; break;
                case 0xBB: contact_str = "接觸測壓區"; break;
                case 0xCF: contact_str = "全部接觸"; break;
                case 0x01: contact_str = "未接觸"; break;
                default: contact_str = "未知狀態"; break;
            }

            int16_t angular_raw = (data[4] << 8) | data[5];
            float angular_speed = angular_raw * 0.001;

            byte flag = data[6];
            bool ir_LA = flag & (1 << 2);
            bool ir_LB = flag & (1 << 3);
            bool ir_RB = flag & (1 << 4);
            bool ir_RA = flag & (1 << 5);
            bool ir_signal = flag & (1 << 1);
            bool is_charging = flag & (1 << 0);

            float current = data[7] * 0.033;
            // 解析資料_結束
            // 顯示資料_開始
            Serial.println("===== 充電站資料 =====");
            Serial.print("線性速度: "); Serial.print(linear_speed); Serial.println(" m/s");
            Serial.print("角速度: "); Serial.print(angular_speed); Serial.println(" rad/s");
            Serial.print("接觸狀態: "); Serial.println(contact_str);
            Serial.print("紅外線 L_A L_B R_B R_A: ");
            Serial.print(ir_LA); Serial.print(" ");
            Serial.print(ir_LB); Serial.print(" ");
            Serial.print(ir_RB); Serial.print(" ");
            Serial.println(ir_RA);
            Serial.print("紅外線訊號: "); Serial.println(ir_signal ? "有" : "無");
            Serial.print("是否充電中: "); Serial.println(is_charging ? "是" : "否");
            Serial.print("充電電流: "); Serial.print(current); Serial.println(" A");
            Serial.println("======================");
            // 顯示資料_結束

            // 進充電站_開始
            if(is_charging){
                // 停止移動
                car_set_speed(1, 0, 0);
                Serial.println("進入充電站，車輛已停止移動。");
                if_exe_charge = false;
            }else{
                Serial.println("未進入充電站，車輛可繼續移動。");
                int left_speed = -50;  // 設定左輪速度
                int right_speed = -50; // 設定右輪速度
                byte speed = 100;
                if(linear_speed != 0){
                    left_speed = -speed;
                    right_speed = -speed;
                }
                if(angular_speed < 0){
                    right_speed -= speed;
                }else if(angular_speed > 0){
                    left_speed -= speed;
                }
                car_set_speed(1, left_speed, right_speed);
            }
            // 進充電站_結束

        }
    }
}
// ------------
// 履帶車_工作區
void car_set_speed(bool mode , uint16_t left_speed , uint16_t right_speed)
{
    driver_set_speed(1, mode, left_speed);
    driver_set_speed(2, mode, right_speed);
}
void car_set_pos(bool mode ,byte speed , long left_pos, long right_pos)
{
    driver_set_pos(1, mode, abs(left_pos * speed), left_pos);
    driver_set_pos(2, mode, abs(right_pos * speed), right_pos);
}
// ------------

// 驅動器_工作區
void driver_read_pos(byte addr){
    byte request_cmd[8] = {addr, 0x03, 0x00, 0x24, 0x00, 0x02, 0x00, 0x00};
    // 發送命令
    modbus_send(request_cmd, 8);
    
    Serial.print("{\"pos_");
    Serial.print(addr);
    Serial.print("\" : ");
    Serial.print(modbus_read());
    Serial.println("}");
}
void driver_read_pow(){
    byte request_cmd[8] = {0x01, 0x03, 0x00, 0x38, 0x00, 0x01, 0x00, 0x00};
    // 發送命令
    modbus_send(request_cmd, 8);
    
    Serial.print("{\"pow\" : ");
    Serial.print(float(modbus_read())/10);
    Serial.println("}");
}
void driver_set_pos(byte addr , bool mode , uint16_t speed , long pos){
    byte request_cmd[17] = { addr, 0x10, 0x00, 0x44, 0x00, 0x04, 0x08,
                             (byte)(speed >> 8), (byte)(speed & 0xFF),
                             0x00, 0x00,
                             (byte)((pos >> 24) & 0xFF), (byte)((pos >> 16) & 0xFF),
                             (byte)((pos >> 8) & 0xFF), (byte)(pos & 0xFF),
                             0x00, 0x00 };
    // 設定模式
    if (mode)
    {
        request_cmd[10] = 0x00; // 絕對位置模式
    }
    else
    {
        request_cmd[10] = 0x01; // 相對位置模式
    }
    // -------
    // 發送命令
    modbus_send(request_cmd, 17);
    modbus_clear();
    // --------
}
void driver_set_speed(byte addr , bool mode , uint16_t  speed)
{
    byte request_cmd[8] = {addr, 0x06, 0x00, 0x00, (byte)(speed >> 8), (byte)(speed & 0xFF), 0x00, 0x00};
    // 設定模式
    if (mode)
    {
        request_cmd[3] = 0x42; // pwm模式
    }
    else
    {
        request_cmd[3] = 0x43; // 速度模式
    }
    // -------
    // 發送命令
    modbus_send(request_cmd, 8);
    modbus_clear();
    // --------
    
}
// -------------



// modbus_工作區
void modbus_init()
{
    modbus_ttl.begin(9600, SERIAL_8N2);
}
void modbus_clear()
{
    delay(5);
    modbus_msg = "";
    bool is_reading = false;
    while (true)
    {
          
        if(modbus_ttl.available() > 0){
            char data = modbus_ttl.read();
            modbus_msg += data;
            //Serial.print(byte(data), HEX);
            //Serial.print(" ");
            is_reading = true;
            
        }else{
            if(is_reading){
                delay(2);
                is_reading = false;
            }else{
                break;
            }
        }
    }
    //Serial.println();
}
long modbus_read()
{
    delay(10);
    modbus_msg = "";
    bool is_reading = false;
    //Serial.println();
    while (true)
    {
          
        if(modbus_ttl.available() > 0){
            char data = modbus_ttl.read();
            modbus_msg += data;
            //Serial.print(byte(data), HEX);
            //Serial.print(" ");
            is_reading = true;
        }else{
            if(is_reading){
                //Serial.println();
                delay(10);
                is_reading = false;
            }else{
                break;
            }
        }
        
        // modbus解析
        if(modbus_msg.length() > 3){
           if (byte(modbus_msg[2]) + 5 <= modbus_msg.length())
            { // 最終解析
                if (crc())
                {
                   if(byte(modbus_msg[2]) == 2){
                        byte data_list[] = {
                            modbus_msg[4], 
                            modbus_msg[3]};
                        int data_value;
                        memcpy(&data_value, data_list, 2);
                        return data_value;
                   }else if(byte(modbus_msg[2]) == 4){
                        byte data_list[] = {
                            modbus_msg[6],
                            modbus_msg[5],
                            modbus_msg[4],
                            modbus_msg[3]
                        };
                        long data_value;
                        memcpy(&data_value, data_list, 4);
                        return data_value;
                   } 
                }
                
            }
            // -------- 
        }
        // --------

        
    }
    
    return 0;
    
}
void modbus_send(byte data[], byte data_len)
{
    // crc 計算
    uint16_t crc = 0xFFFF;
    for (byte i = 0; i < data_len - 2; i++)
    {
        crc ^= data[i];
        for (byte j = 0; j < 8; j++)
        {
            if (crc & 0x0001)
            {
                crc = (crc >> 1) ^ 0xA001;
            }
            else
            {
                crc >>= 1;
            }
        }
    }
    data[data_len - 1] = byte(crc / 256);
    data[data_len - 2] = byte(crc - (data[data_len - 1] * 256));
    // -------
    // 發送命令
    modbus_ttl.write(data, data_len);
    modbus_ttl.flush();
    // --------
}

bool crc()
{
    // crc 計算
    uint16_t crc = 0xFFFF;
    for (byte i = 0; i < (modbus_msg.length() - 2); i++)
    {
        crc ^= uint8_t(modbus_msg[i]);
        for (byte j = 0; j < 8; j++)
        {
            if (crc & 0x0001)
            {
                crc = (crc >> 1) ^ 0xA001;
            }
            else
            {
                crc >>= 1;
            }
        }
    }
    // --------
    // 被比對 crc 格式轉成 int
    uint8_t data_crc[] =
        {modbus_msg[modbus_msg.length() - 2], modbus_msg[modbus_msg.length() - 1]};
    uint16_t data_crc_int;
    memcpy(&data_crc_int, data_crc, 2);
    // -----------------------
    return (data_crc_int == crc);
}
// ----------------