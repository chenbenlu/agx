import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import serial
import json
import math

class CarControllerNode(Node):
    def __init__(self):
        super().__init__('car_controller_node')
        
        # --- 宣告並讀取 YAML 參數 ---
        self.declare_parameter('usb_port', '/dev/ttyACM0')
        self.declare_parameter('car_distance', 0.65)
        self.declare_parameter('car_mode', 'diff')
        self.declare_parameter('Tire_diameter', 0.18)
        self.declare_parameter('encoder_resolution', 720)
        self.declare_parameter('gear_ratio', 1.0)
        self.declare_parameter('odom_up_hz', 10)
        self.declare_parameter('baudrate', 115200) # 隱藏參數，對應 Arduino

        self.port = self.get_parameter('usb_port').value
        self.car_distance = self.get_parameter('car_distance').value
        self.car_mode = self.get_parameter('car_mode').value
        self.tire_diameter = self.get_parameter('Tire_diameter').value
        self.encoder_res = self.get_parameter('encoder_resolution').value
        self.gear_ratio = self.get_parameter('gear_ratio').value
        self.odom_up_hz = self.get_parameter('odom_up_hz').value
        baudrate = self.get_parameter('baudrate').value

        # --- 初始化 Serial ---
        try:
            self.serial_port = serial.Serial(self.port, baudrate, timeout=0.1)
            self.get_logger().info(f"成功連接底層控制板: {self.port}")
        except Exception as e:
            self.get_logger().error(f"Serial Port 連接失敗: {e}")
            raise SystemExit

        # --- 訂閱 cmd_vel ---
        self.subscription = self.create_subscription(
            Twist,
            'cmd_vel',
            self.cmd_vel_callback,
            10
        )
        
        # 預留：依據 odom_up_hz 建立 Timer 定期向 Arduino 請求 Odom 資料
        # self.odom_timer = self.create_timer(1.0 / self.odom_up_hz, self.request_odom)

    def cmd_vel_callback(self, msg):
        if self.car_mode != 'diff':
            self.get_logger().error("目前演算法僅支援 diff (差速) 模式！")
            return

        linear_x = msg.linear.x    # m/s
        angular_z = msg.angular.z  # rad/s

        # 1. 差速運動學：計算左右輪線速度 (m/s)
        v_left = linear_x - (angular_z * self.car_distance / 2.0)
        v_right = linear_x + (angular_z * self.car_distance / 2.0)

        # 2. 物理單位轉換 (m/s -> RPM)
        # 輪周長 = pi * D
        circumference = math.pi * self.tire_diameter
        
        # RPM = (線速度 / 周長) * 60秒 * 減速比
        rpm_left = (v_left / circumference) * 60.0 * self.gear_ratio
        rpm_right = (v_right / circumference) * 60.0 * self.gear_ratio

        # 3. 輸出數值整數化 (依據 Arduino Modbus 驅動器的接收格式)
        # 這裡假設你的驅動器直接接收 RPM 整數值。
        # 若驅動器需要的是「每秒脈衝數(PPS)」，則需乘上 (encoder_res / 60)
        ls_out = int(rpm_left)
        rs_out = int(rpm_right)

        # 4. 組合 JSON 並發送
        command = {"m": 0, "ls": ls_out, "rs": rs_out}
        json_str = json.dumps(command) + '\n'

        try:
            self.serial_port.write(json_str.encode('utf-8'))
            self.serial_port.flush()
        except Exception as e:
            self.get_logger().error(f"寫入 Serial 失敗: {e}")

def main(args=None):
    rclpy.init(args=args)
    node = CarControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if hasattr(node, 'serial_port') and node.serial_port.is_open:
            # 安全機制：關閉前煞車
            node.serial_port.write(b'{"m":0,"ls":0,"rs":0}\n')
            node.serial_port.flush()
            node.serial_port.close()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()