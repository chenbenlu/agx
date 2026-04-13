#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped


class FoxglovePoseRepublisher(Node):
    def __init__(self):
        super().__init__('foxglove_pose_republisher')

        self.initial_pub = self.create_publisher(
            PoseWithCovarianceStamped, '/initialpose', 10)
        self.goal_pub = self.create_publisher(
            PoseStamped, '/goal_pose', 10)

        self.create_subscription(
            PoseWithCovarianceStamped, '/initialpose_fox',
            self.initial_cb, 10)
        self.create_subscription(
            PoseStamped, '/goal_pose_fox', self.goal_cb, 10)

        self.get_logger().info(
            'republishing /initialpose_fox -> /initialpose, '
            '/goal_pose_fox -> /goal_pose with current clock stamp')

    def initial_cb(self, msg: PoseWithCovarianceStamped):
        msg.header.stamp = self.get_clock().now().to_msg()
        if not msg.header.frame_id:
            msg.header.frame_id = 'map'
        self.initial_pub.publish(msg)

    def goal_cb(self, msg: PoseStamped):
        msg.header.stamp = self.get_clock().now().to_msg()
        if not msg.header.frame_id:
            msg.header.frame_id = 'map'
        self.goal_pub.publish(msg)


def main():
    rclpy.init()
    node = FoxglovePoseRepublisher()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
