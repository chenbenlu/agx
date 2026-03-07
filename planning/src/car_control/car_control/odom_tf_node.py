#!/usr/bin/python
# -*- coding: UTF-8 -*-
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from std_msgs.msg import Int32MultiArray
from geometry_msgs.msg import TransformStamped
import tf_transformations
import tf2_ros
import math

class OdomTfPublisher(Node):
    def __init__(self):
        super().__init__('odom_tf_node')
        
        # 參數讀取 (與之前 MCU 一致)
        self.declare_parameter('car_distance', 0.25)
        self.declare_parameter('Tire_diameter', 0.092)
        self.declare_parameter('encoder_resolution', 11)
        self.declare_parameter('gear_ratio', 90)
        
        self.car_distance = self.get_parameter('car_distance').value
        Tire_diameter = self.get_parameter('Tire_diameter').value
        encoder_resolution = self.get_parameter('encoder_resolution').value
        gear_ratio = self.get_parameter('gear_ratio').value
        
        Total_pulses = gear_ratio * encoder_resolution
        self.distance_per_pulse = math.pi * Tire_diameter / Total_pulses
        
        # ROS 通訊
        self.create_subscription(Int32MultiArray, '/encoders', self.encoder_callback, 10)
        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self.odom_broadcaster = tf2_ros.TransformBroadcaster(self)

        self.last_left_pos = None
        self.last_right_pos = None
        self.last_time = self.get_clock().now()
        
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0

    def encoder_callback(self, msg):
        if len(msg.data) < 2:
            return
            
        left_pos = msg.data[0]
        right_pos = msg.data[1]
        current_time = self.get_clock().now()
        
        if self.last_left_pos is not None and self.last_right_pos is not None:
            # 計算脈衝差
            delta_left = left_pos - self.last_left_pos
            delta_right = right_pos - self.last_right_pos
            
            # 脈衝差 -> 行駛距離 (米)
            dist_left = delta_left * self.distance_per_pulse
            dist_right = delta_right * self.distance_per_pulse
            
            # 時間差
            dt = (current_time.nanoseconds - self.last_time.nanoseconds) * 1e-9
            if dt <= 0: return

            # 差速輪逆運動學
            odom_vx = (dist_right + dist_left) / (2.0 * dt)
            odom_vy = 0.0
            odom_wz = (dist_right - dist_left) / (self.car_distance * dt)
            
            dist_center = (dist_right + dist_left) / 2.0
            delta_th = (dist_right - dist_left) / self.car_distance
            
            self.x += dist_center * math.cos(self.theta + delta_th/2.0)
            self.y += dist_center * math.sin(self.theta + delta_th/2.0)
            self.theta += delta_th

            # 發布 TF
            t = TransformStamped()
            t.header.stamp = current_time.to_msg()
            t.header.frame_id = 'odom'
            t.child_frame_id = 'base_link'
            t.transform.translation.x = self.x
            t.transform.translation.y = self.y
            t.transform.translation.z = 0.0
            q = tf_transformations.quaternion_from_euler(0, 0, self.theta)
            t.transform.rotation.x = q[0]
            t.transform.rotation.y = q[1]
            t.transform.rotation.z = q[2]
            t.transform.rotation.w = q[3]
            self.odom_broadcaster.sendTransform(t)

            # 發布 Odometry
            odom = Odometry()
            odom.header.stamp = current_time.to_msg()
            odom.header.frame_id = 'odom'
            odom.child_frame_id = 'base_link'
            odom.pose.pose.position.x = self.x
            odom.pose.pose.position.y = self.y
            odom.pose.pose.position.z = 0.0
            odom.pose.pose.orientation.x = q[0]
            odom.pose.pose.orientation.y = q[1]
            odom.pose.pose.orientation.z = q[2]
            odom.pose.pose.orientation.w = q[3]
            odom.twist.twist.linear.x = odom_vx
            odom.twist.twist.linear.y = odom_vy
            odom.twist.twist.angular.z = odom_wz
            self.odom_pub.publish(odom)

        self.last_left_pos = left_pos
        self.last_right_pos = right_pos
        self.last_time = current_time

def main(args=None):
    rclpy.init(args=args)
    node = OdomTfPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
