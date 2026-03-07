// modbus_宣告區
#include <SoftwareSerial.h>
#define modbus_ttl Serial2

String modbus_msg = "";

// ----------------
// 充電站_宣告區
#include <mcp_can.h>
#include <SPI.h>
const int SPI_CS_PIN = 10;
MCP_CAN CAN(SPI_CS_PIN);
bool if_exe_charge = false;
// ----------------

// micro-ROS 宣告區
#include <micro_ros_arduino.h>
#include <stdio.h>
#include <rcl/rcl.h>
#include <rcl/error_handling.h>
#include <rclc/rclc.h>
#include <rclc/executor.h>

#include <geometry_msgs/msg/twist.h>
#include <std_msgs/msg/int32_multi_array.h>

rcl_publisher_t encoder_pub;
std_msgs__msg__Int32MultiArray enc_msg;

rcl_subscription_t twist_sub;
geometry_msgs__msg__Twist twist_msg;

rclc_executor_t executor;
rclc_support_t support;
rcl_allocator_t allocator;
rcl_node_t node;
rcl_timer_t timer;

#define LED_PIN 13
#define RCCHECK(fn) { rcl_ret_t temp_rc = fn; if((temp_rc != RCL_RET_OK)){error_loop();}}
#define RCSOFTCHECK(fn) { rcl_ret_t temp_rc = fn; if((temp_rc != RCL_RET_OK)){}}

// 逆運動學參數
const float car_distance = 0.25;
const float Tire_diameter = 0.092;
const float encoder_resolution = 11.0;
const float gear_ratio = 90.0;
const float Total_pulses = gear_ratio * encoder_resolution;
const float speed_1_every_second_speed = (PI * Tire_diameter / Total_pulses) / 10.0;

void error_loop(){
  while(1){
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    delay(100);
  }
}

// 接收 Twist 訊息的 callback
void twist_callback(const void * msgin)
{  
  const geometry_msgs__msg__Twist * msg = (const geometry_msgs__msg__Twist *)msgin;
  
  float linear_x = msg->linear.x;
  float angular_z = msg->angular.z;
  
  // 差速輪速度換算
  float left_speed = linear_x - (car_distance / 2.0) * angular_z;
  float right_speed = linear_x + (car_distance / 2.0) * angular_z;
  
  int ls_val = (int)(left_speed / speed_1_every_second_speed);
  int rs_val = (int)(right_speed / speed_1_every_second_speed);
  
  car_set_speed(0, ls_val, rs_val); 
}

// 定時器 callback，用來發送編碼器資料
void timer_callback(rcl_timer_t * timer, int64_t last_call_time)
{  
  RCLC_UNUSED(last_call_time);
  if (timer != NULL) {
    long pos_1 = modbus_read_pos_direct(1);
    long pos_2 = modbus_read_pos_direct(2);
    
    enc_msg.data.data[0] = (int32_t)pos_1;
    enc_msg.data.data[1] = (int32_t)pos_2;
    
    RCSOFTCHECK(rcl_publish(&encoder_pub, &enc_msg, NULL));
  }
}

void setup() {
  set_microros_transports();
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  
  
  modbus_init(); 
  delay(1000);
  Charging_Station_init();

  allocator = rcl_get_default_allocator();

  RCCHECK(rclc_support_init(&support, 0, NULL, &allocator));
  RCCHECK(rclc_node_init_default(&node, "micro_ros_arduino_node", "", &support));

  // 發佈者
  RCCHECK(rclc_publisher_init_default(
    &encoder_pub,
    &node,
    ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Int32MultiArray),
    "encoders"));

  // 初始化陣列記憶體
  enc_msg.data.capacity = 2;
  enc_msg.data.size = 2;
  enc_msg.data.data = (int32_t*) malloc(enc_msg.data.capacity * sizeof(int32_t));

  // 訂閱者
  RCCHECK(rclc_subscription_init_default(
    &twist_sub,
    &node,
    ROSIDL_GET_MSG_TYPE_SUPPORT(geometry_msgs, msg, Twist),
    "cmd_vel"));

  // Timer (例如 10Hz 發送編碼器資料)
  const unsigned int timer_timeout = 100;
  RCCHECK(rclc_timer_init_default(
    &timer,
    &support,
    RCL_MS_TO_NS(timer_timeout),
    timer_callback));

  // Executor
  RCCHECK(rclc_executor_init(&executor, &support.context, 2, &allocator));
  RCCHECK(rclc_executor_add_subscription(&executor, &twist_sub, &twist_msg, &twist_callback, ON_NEW_DATA));
  RCCHECK(rclc_executor_add_timer(&executor, &timer));
}

void loop() {
  delay(10);
  RCSOFTCHECK(rclc_executor_spin_some(&executor, RCL_MS_TO_NS(100)));
  
  // 是否進入充電站
  if(if_exe_charge){
      Charging_Station_read();
  }
}

// ------------------
// 充電站_工作區
void Charging_Station_init() {
  while (CAN_OK != CAN.begin(MCP_ANY, CAN_1000KBPS, MCP_8MHZ)) {
    delay(100);
  }
  CAN.setMode(MCP_NORMAL);
}

void Charging_Station_read() {
    long unsigned int rxId;
    unsigned char len = 0;
    unsigned char data[8];

    if (CAN_MSGAVAIL == CAN.checkReceive()) {
        CAN.readMsgBuf(&rxId, &len, data);  

        if (rxId == 0x182) {
            byte flag = data[6];
            bool is_charging = flag & (1 << 0);

            if(is_charging){
                car_set_speed(1, 0, 0);
                if_exe_charge = false;
            }else{
                // ... 繼續移動邏輯，略
                car_set_speed(1, -100, -100);
            }
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

// 驅動器_工作區
long modbus_read_pos_direct(byte addr){
    byte request_cmd[8] = {addr, 0x03, 0x00, 0x24, 0x00, 0x02, 0x00, 0x00};
    modbus_send(request_cmd, 8);
    return modbus_read();
}

void driver_set_speed(byte addr , bool mode , uint16_t  speed)
{
    byte request_cmd[8] = {addr, 0x06, 0x00, 0x00, (byte)(speed >> 8), (byte)(speed & 0xFF), 0x00, 0x00};
    if (mode)
        request_cmd[3] = 0x42; // pwm模式
    else
        request_cmd[3] = 0x43; // 速度模式
        
    modbus_send(request_cmd, 8);
    modbus_clear();
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
}

long modbus_read()
{
    delay(10);
    modbus_msg = "";
    bool is_reading = false;
    while (true)
    {
        if(modbus_ttl.available() > 0){
            char data = modbus_ttl.read();
            modbus_msg += data;
            is_reading = true;
        }else{
            if(is_reading){
                delay(10);
                is_reading = false;
            }else{
                break;
            }
        }
        
        // modbus解析
        if(modbus_msg.length() > 3){
           if (byte(modbus_msg[2]) + 5 <= modbus_msg.length())
            {
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
        }
    }
    return 0;
}

void modbus_send(byte data[], byte data_len)
{
    uint16_t crc = 0xFFFF;
    for (byte i = 0; i < data_len - 2; i++)
    {
        crc ^= data[i];
        for (byte j = 0; j < 8; j++)
        {
            if (crc & 0x0001)
                crc = (crc >> 1) ^ 0xA001;
            else
                crc >>= 1;
        }
    }
    data[data_len - 1] = byte(crc / 256);
    data[data_len - 2] = byte(crc - (data[data_len - 1] * 256));
    
    modbus_ttl.write(data, data_len);
    modbus_ttl.flush();
}

bool crc()
{
    uint16_t crc = 0xFFFF;
    for (byte i = 0; i < (modbus_msg.length() - 2); i++)
    {
        crc ^= uint8_t(modbus_msg[i]);
        for (byte j = 0; j < 8; j++)
        {
            if (crc & 0x0001)
                crc = (crc >> 1) ^ 0xA001;
            else
                crc >>= 1;
        }
    }
    uint8_t data_crc[] = {modbus_msg[modbus_msg.length() - 2], modbus_msg[modbus_msg.length() - 1]};
    uint16_t data_crc_int;
    memcpy(&data_crc_int, data_crc, 2);
    return (data_crc_int == crc);
}
