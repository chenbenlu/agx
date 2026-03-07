#include <ESP8266WiFi.h>
// html_界面_宣告區
WiFiServer server(80);          // 創建服務器(端口)
// ----------------
// 遙控_宣告區
int moving_speed = 0;
// -----------
void setup() {
    Serial.begin(115200);       delay(100);
    ap_init();                  delay(100);
    html_init();                delay(100);
}
void loop() {
    html_interface();
}
// html_界面_工作區
void html_init(){
    server.begin(); 
}
void html_interface(){
    // 創建客戶端 放入 已連接的設備 進行資料讀取
    WiFiClient client = server.available();
    String header;
    if (client)         // 檢測是否有設備連接
    {
        unsigned long previousTime = millis();// 放入現在arduino執行時間
        //Serial.println("New Client.");
        String currentLine = "";
        // 循環(是否連接 與 是否循環超過兩秒)
        while (client.connected() && millis() - previousTime <= 2000)
        {
            if (client.available())         // 判斷讀取到用戶端需資料
            {
                char c = client.read();     // 讀取
                //Serial.write(c);
                header += c;                // 保存讀取的字
                if (c == '\n')              
                {
                    if (currentLine.length() == 0)
                    {
                        // 網頁格式基本配置
                        client.println("HTTP/1.1 200 OK");
                        client.println("Content-type:text/html");
                        client.println("Connection: close");
                        // ----------------
                        client.println();
                        // 判斷使用者發布(按鍵){並設定為執行目標}
                        //telecontrol_Target = header[5];
                        exe_remote_control_command(header[5]);
                        // ------------------------------------
                        // 網頁
                        String html_str = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
<link rel="icon" href="data:,">
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  .grid-container {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    padding: 20px;
  }
  .grid-item {
    background-color: #3498db;
    color: white;
    text-align: center;
    padding: 20px;
    font-size: 18px;
    border-radius: 5px;
    cursor: pointer;
    text-decoration: none; /* Remove underline */
  }
</style>
</head>
<body>
  <div class="grid-container">
    <a class="grid-item" href="/q">\</a>
    <a class="grid-item" href="/w">^</a>
    <a class="grid-item" href="/e">/</a>

    <a class="grid-item" href="/a"><</a>
    <a class="grid-item" href="/s">+</a>
    <a class="grid-item" href="/d">></a>

    <a class="grid-item" href="/z">/</a>
    <a class="grid-item" href="/x">v</a>
    <a class="grid-item" href="/c">\</a>

    <a class="grid-item" href="/u">-</a>
    <a class="grid-item" href="/i">speed</a>
    <a class="grid-item" href="/o">+</a>

    <a class="grid-item" href="/j">NO</a>
    <a class="grid-item" href="/k">charge</a>
    <a class="grid-item" href="/l">OFF</a>

  </div>
</body>
</html>
                        )rawliteral";
                        html_str.replace("speed" , String(moving_speed));
                        client.println(html_str);
                        // ---------------
                        break;
                    }
                    else
                    { // 如果有換行符，則清除 currentLine
                        currentLine = "";
                    }
                }
                else if (c != '\r')
                {                     // 如果你除了回車符之外還有別的東西，
                    currentLine += c; // 將其添加到 currentLine 的末尾
                }
            }
        }
        header = "";
        client.stop();
        //Serial.println("Client disconnected.");
        //Serial.println("");
    }
}
// ---------------
// 遙控_工作區
void exe_remote_control_command(char telecontrol_Target){
    // 比對鍵位(按鍵){控制馬達([速度])}
    if (telecontrol_Target == 'q'){
        json_motor_driver_set_speed(0,moving_speed);
    }else if(telecontrol_Target == 'w'){
        json_motor_driver_set_speed(moving_speed,moving_speed);
    }else if(telecontrol_Target == 'e'){
        json_motor_driver_set_speed(moving_speed,0);
    }else if(telecontrol_Target == 'a'){
        json_motor_driver_set_speed(-moving_speed,moving_speed);
    }else if(telecontrol_Target == 's'){
        json_motor_driver_set_speed(0,0);
    }else if(telecontrol_Target == 'd'){
        json_motor_driver_set_speed(moving_speed,-moving_speed);
    }else if(telecontrol_Target == 'z'){
        json_motor_driver_set_speed(0,-moving_speed);
    }else if(telecontrol_Target == 'x'){
        json_motor_driver_set_speed(-moving_speed,-moving_speed);
    }else if(telecontrol_Target == 'c'){
        json_motor_driver_set_speed(-moving_speed,0);
    }else if(telecontrol_Target == 'u'){
        moving_speed -= 100;
    }else if(telecontrol_Target == 'o'){
        moving_speed += 100;
    }
    else if(telecontrol_Target == 'j'){
        Serial.println("{\"charge\" : 1}");
    }else if(telecontrol_Target == 'l'){
        Serial.println("{\"charge\" : 0}");
    }
    // ----------------------------
}
void json_motor_driver_set_speed(int left_speed , int right_speed){
    String str = "{\"m\" : 1 , \"ls\" : \"left_speed\" , \"rs\" : \"right_speed\"}";
    str.replace("left_speed",String(left_speed));
    str.replace("right_speed",String(right_speed));
    Serial.println(str);
}
// ----------
// wifi/ap_工作區
void ap_init(){
    // 放入 ap 賬號密碼
    const char *ssid = "zan";
    const char *password = "zanrobot";
    // ----------------
    WiFi.mode(WIFI_AP);             // 設定網卡模式為(ap模式)
    WiFi.softAP(ssid, password);    // 設定 ap (賬號,密碼)
    //Serial.println(WiFi.localIP()); // 顯示 ip 位置 
}
// --------------