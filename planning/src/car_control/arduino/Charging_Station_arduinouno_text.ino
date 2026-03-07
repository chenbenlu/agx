#include <mcp_can.h>
#include <SPI.h>

const int SPI_CS_PIN = 10;
MCP_CAN CAN(SPI_CS_PIN);

void setup() {
  Serial.begin(115200);
  Charging_Station_init();
  
}

void loop() {
  Charging_Station_read();
  delay(1000);
}

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
    CAN.readMsgBuf(&rxId, &len, data);

    if (rxId == 0x182) {
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
    }
  }
}
// ------------
