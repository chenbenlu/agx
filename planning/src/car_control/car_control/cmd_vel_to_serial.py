import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped, Quaternion
from nav_msgs.msg import Odometry
import tf2_ros
import serial
import json
import math
import threading
import time

class CarControllerNode(Node):
    def __init__(self):
        super().__init__('car_controller_node')
        
        # --- 1. 宣告與讀取 YAML 參數 ---
        self.declare_parameter('usb_port', '/dev/ttyUSB0')
        self.declare_parameter('car_distance', 0.65)
        self.declare_parameter('car_mode', 'diff')
        self.declare_parameter('Tire_diameter', 0.18)
        self.declare_parameter('encoder_resolution', 720)
        self.declare_parameter('gear_ratio', 1.0)
        self.declare_parameter('odom_up_hz', 10.0)
        self.declare_parameter('baudrate', 115200)

        self.port = self.get_parameter('usb_port').value
        self.car_distance = self.get_parameter('car_distance').value
        self.tire_diameter = self.get_parameter('Tire_diameter').value
        self.encoder_res = self.get_parameter('encoder_resolution').value
        self.gear_ratio = self.get_parameter('gear_ratio').value
        self.odom_up_hz = self.get_parameter('odom_up_hz').value
        baudrate = self.get_parameter('baudrate').value

        # --- 2. 初始化硬體通訊與執行緒鎖 ---
        self.serial_lock = threading.Lock() # 確保 TX/RX 不會互相干擾
        try:
            self.serial_port = serial.Serial(self.port, baudrate, timeout=0.01)
            self.get_logger().info(f"成功連接底層控制板: {self.port}")
        except Exception as e:
            self.get_logger().error(f"Serial Port 連接失敗: {e}")
            raise SystemExit

        # --- 3. 初始化 ROS 2 通訊介面 ---
        self.subscription = self.create_subscription(Twist, 'cmd_vel', self.cmd_vel_callback, 10)
        self.odom_pub = self.create_publisher(Odometry, 'odom', 10)
        self.tf_broadcaster = tf2_ros.TransformBroadcaster(self)

        # --- 4. 狀態變數 (Odometry) ---
        self.x = 0.0
        self.y = 0.0
        self.th = 0.0
        self.last_time = self.get_clock().now()
        
        self.last_enc_left = None
        self.last_enc_right = None

        # --- 5. 定時器 ---
        # 讀取 Serial 緩衝區 (高頻，確保不漏封包)
        self.read_timer = self.create_timer(0.02, self.read_serial_callback)
        # 請求里程計資料 (依據 YAML 設定的 Hz)
        self.odom_timer = self.create_timer(1.0 / self.odom_up_hz, self.request_odom_callback)

    def cmd_vel_callback(self, msg):
        """處理下發的速度指令"""
        linear_x = msg.linear.x
        angular_z = msg.angular.z

        # 逆向運動學 (Inverse Kinematics)
        v_left = linear_x - (angular_z * self.car_distance / 2.0)
        v_right = linear_x + (angular_z * self.car_distance / 2.0)

        circumference = math.pi * self.tire_diameter
        rpm_left = (v_left / circumference) * 60.0 * self.gear_ratio
        rpm_right = (v_right / circumference) * 60.0 * self.gear_ratio

        # 組合 JSON
        command = {"m": 0, "ls": int(rpm_left), "rs": int(rpm_right)}
        json_str = json.dumps(command) + '\n'

        # 寫入 Serial (使用鎖)
        with self.serial_lock:
            try:
                self.serial_port.write(json_str.encode('utf-8'))
                self.serial_port.flush()
            except Exception as e:
                self.get_logger().error(f"下發指令失敗: {e}")

    def request_odom_callback(self):
        """定時向 Arduino 請求左右輪編碼器資料"""
        with self.serial_lock:
            try:
                # 依據你的 Arduino 邏輯，需發送兩次請求 (這是效能瓶頸，見下方挑戰)
                self.serial_port.write(b'{"rpos": 1}\n')
                self.serial_port.write(b'{"rpos": 2}\n')
                self.serial_port.flush()
            except Exception as e:
                pass

    def read_serial_callback(self):
        """讀取 Arduino 回傳的 JSON 並計算里程計"""
        try:
            while self.serial_port.in_waiting > 0:
                line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                if not line or not line.startswith('{'):
                    continue
                
                try:
                    data = json.loads(line)
                    enc_left_now = self.last_enc_left
                    enc_right_now = self.last_enc_right

                    if "pos_1" in data:
                        enc_left_now = data["pos_1"]
                    if "pos_2" in data:
                        enc_right_now = data["pos_2"]

                    # 只有當我們擁有左右兩輪的資料，且資料有更新時才計算 Odom
                    if enc_left_now is not None and enc_right_now is not None:
                        if enc_left_now != self.last_enc_left or enc_right_now != self.last_enc_right:
                            self.update_odometry(enc_left_now, enc_right_now)
                            
                except json.JSONDecodeError:
                    self.get_logger().warn(f"JSON 碎片丟棄: {line}")
        except Exception:
            pass

    def update_odometry(self, current_left, current_right):
        """正向運動學：將編碼器 Ticks 轉換為世界座標系的 X, Y, Theta"""
        current_time = self.get_clock().now()
        
        if self.last_enc_left is None or self.last_enc_right is None:
            self.last_enc_left = current_left
            self.last_enc_right = current_right
            self.last_time = current_time
            return

        # 計算脈衝差值
        dt_left = current_left - self.last_enc_left
        dt_right = current_right - self.last_enc_right

        # 計算單輪移動距離 (公尺)
        # 公式: (脈衝差 / (解析度 * 減速比)) * 輪胎周長
        circumference = math.pi * self.tire_diameter
        ticks_per_meter = (self.encoder_res * self.gear_ratio) / circumference
        
        dist_left = dt_left / ticks_per_meter
        dist_right = dt_right / ticks_per_meter

        # 計算中心點移動距離與旋轉角度
        d_center = (dist_right + dist_left) / 2.0
        d_theta = (dist_right - dist_left) / self.car_distance

        # 更新機器人座標 (使用 Runge-Kutta 2nd order approximation)
        self.x += d_center * math.cos(self.th + (d_theta / 2.0))
        self.y += d_center * math.sin(self.th + (d_theta / 2.0))
        self.th += d_theta

        # 計算速度 (Velocity)
        dt = (current_time - self.last_time).nanoseconds / 1e9
        v_x = d_center / dt if dt > 0 else 0.0
        v_theta = d_theta / dt if dt > 0 else 0.0

        # 發布 TF 與 Odom
        self.publish_odom(current_time, v_x, v_theta)

        # 更新狀態
        self.last_enc_left = current_left
        self.last_enc_right = current_right
        self.last_time = current_time

    def publish_odom(self, current_time, v_x, v_theta):
        # 1. 廣播 TF (odom -> base_link)
        t = TransformStamped()
        t.header.stamp = current_time.to_msg()
        t.header.frame_id = 'odom'
        t.child_frame_id = 'base_link'
        t.transform.translation.x = self.x
        t.transform.translation.y = self.y
        t.transform.translation.z = 0.0
        
        # Euler 轉 Quaternion
        q = Quaternion()
        q.z = math.sin(self.th / 2.0)
        q.w = math.cos(self.th / 2.0)
        t.transform.rotation = q
        
        self.tf_broadcaster.sendTransform(t)

        # 2. 發布 nav_msgs/Odometry
        odom = Odometry()
        odom.header.stamp = current_time.to_msg()
        odom.header.frame_id = 'odom'
        odom.child_frame_id = 'base_link'
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.orientation = q
        odom.twist.twist.linear.x = v_x
        odom.twist.twist.angular.z = v_theta
        
        self.odom_pub.publish(odom)

def main(args=None):
    rclpy.init(args=args)
    node = CarControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if hasattr(node, 'serial_port') and node.serial_port.is_open:
            with node.serial_lock:
                node.serial_port.write(b'{"m":0,"ls":0,"rs":0}\n')
                node.serial_port.flush()
                node.serial_port.close()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()