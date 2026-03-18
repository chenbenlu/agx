/**
 * @file kinematics_node.cpp
 * @brief ROS 2 Kinematics Node — 處理 cmd_vel→輪速 (正運動學) 與 encoder→Odom/TF (逆運動學)
 *
 * 職責：
 *   1. 訂閱 /cmd_vel (geometry_msgs/Twist)
 *      → 差速運動學計算左右輪 RPM
 *      → 打包成 JSON 發布至 /serial_tx (由 serial_bridge_node 寫入 UART)
 *
 *   2. 訂閱 /serial_rx (std_msgs/String)
 *      → 解析 Arduino 回傳的 encoder JSON (pos_1, pos_2)
 *      → 差速逆運動學計算 Odometry
 *      → 發布 /odom (nav_msgs/Odometry) 與 TF (odom → base_link)
 *
 * 設計理念：
 *   - 這是一個純數學/ROS 訊息的節點，完全不碰硬體
 *   - 所有運動學公式保留原始 Python 版本的計算邏輯
 *   - 可獨立進行單元測試
 *
 * 編譯依賴：rclcpp, std_msgs, geometry_msgs, nav_msgs, tf2_ros, nlohmann_json
 */

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2/LinearMath/Quaternion.h>

#include <nlohmann/json.hpp>

#include <cmath>
#include <string>
#include <optional>

using json = nlohmann::json;

class KinematicsNode : public rclcpp::Node
{
public:
    KinematicsNode()
        : Node("kinematics_node")
    {
        // =====================================================================
        //  參數宣告與讀取（與原 Python 版完全對應）
        // =====================================================================
        this->declare_parameter<double>("car_distance", 0.65);
        this->declare_parameter<std::string>("car_mode", "diff");
        this->declare_parameter<double>("Tire_diameter", 0.18);
        this->declare_parameter<int>("encoder_resolution", 720);
        this->declare_parameter<double>("gear_ratio", 1.0);
        this->declare_parameter<int>("odom_up_hz", 10);
        this->declare_parameter<bool>("use_encoder_feedback", true);

        car_distance_        = this->get_parameter("car_distance").as_double();
        car_mode_            = this->get_parameter("car_mode").as_string();
        tire_diameter_       = this->get_parameter("Tire_diameter").as_double();
        encoder_resolution_  = this->get_parameter("encoder_resolution").as_int();
        gear_ratio_          = this->get_parameter("gear_ratio").as_double();
        odom_up_hz_          = this->get_parameter("odom_up_hz").as_int();
        use_encoder_feedback_= this->get_parameter("use_encoder_feedback").as_bool();

        // =====================================================================
        //  衍生常數計算
        // =====================================================================
        tire_circumference_ = M_PI * tire_diameter_;                             // 輪周長
        tire_radius_        = tire_diameter_ / 2.0;                              // 輪半徑
        total_pulses_       = gear_ratio_ * static_cast<double>(encoder_resolution_); // 每圈總脈衝數
        distance_per_pulse_ = M_PI * tire_diameter_ / total_pulses_;             // 每脈衝行進距離 (m)

        // 原 Python car_controller.py 的 speed_1_every_second_speed
        // = (pi * D / Total_pulses) / 10
        speed_1_per_second_ = (M_PI * tire_diameter_ / total_pulses_) / 10.0;

        RCLCPP_INFO(this->get_logger(), "--- Kinematics 參數 ---");
        RCLCPP_INFO(this->get_logger(), "car_distance      = %.3f m", car_distance_);
        RCLCPP_INFO(this->get_logger(), "car_mode           = %s", car_mode_.c_str());
        RCLCPP_INFO(this->get_logger(), "Tire_diameter      = %.3f m", tire_diameter_);
        RCLCPP_INFO(this->get_logger(), "encoder_resolution = %d", encoder_resolution_);
        RCLCPP_INFO(this->get_logger(), "gear_ratio         = %.2f", gear_ratio_);
        RCLCPP_INFO(this->get_logger(), "odom_up_hz         = %d Hz", odom_up_hz_);
        RCLCPP_INFO(this->get_logger(), "use_encoder_feedback = %s", use_encoder_feedback_ ? "true" : "false");
        RCLCPP_INFO(this->get_logger(), "tire_circumference = %.4f m", tire_circumference_);
        RCLCPP_INFO(this->get_logger(), "distance_per_pulse = %.6f m", distance_per_pulse_);
        RCLCPP_INFO(this->get_logger(), "-----------------------");

        // =====================================================================
        //  Odom 狀態初始化
        // =====================================================================
        x_ = 0.0;
        y_ = 0.0;
        theta_ = 0.0;
        last_linear_x_ = 0.0;
        last_linear_y_ = 0.0;
        last_angular_z_ = 0.0;
        last_time_ = this->now();

        // =====================================================================
        //  ROS 介面
        // =====================================================================

        // --- Publisher ---
        pub_serial_tx_ = this->create_publisher<std_msgs::msg::String>("serial_tx", 10);
        pub_odom_       = this->create_publisher<nav_msgs::msg::Odometry>("odom", 10);
        tf_broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);

        // --- Subscriber ---
        sub_cmd_vel_ = this->create_subscription<geometry_msgs::msg::Twist>(
            "cmd_vel", 10,
            std::bind(&KinematicsNode::cmd_vel_callback, this, std::placeholders::_1));

        sub_serial_rx_ = this->create_subscription<std_msgs::msg::String>(
            "serial_rx", 10,
            std::bind(&KinematicsNode::serial_rx_callback, this, std::placeholders::_1));

        // --- Timer ---
        if (!use_encoder_feedback_) {
            // 開迴路模式：定時以 cmd_vel 積分 Odom
            const auto period = std::chrono::milliseconds(1000 / odom_up_hz_);
            odom_timer_ = this->create_wall_timer(
                period, std::bind(&KinematicsNode::odom_openloop_callback, this));
            RCLCPP_INFO(this->get_logger(), "開迴路模式：以 %d Hz 積分 Odom",
                        static_cast<int>(odom_up_hz_));
        } else {
            // 閉迴路模式：等待 Arduino 主動 push {"p1":x,"p2":y}
            // 不需要任何 Timer，Odom 由 serial_rx callback 直接觸發
            RCLCPP_INFO(this->get_logger(),
                        "閉迴路模式：等待 Arduino Push {\"p1\":x,\"p2\":y}");
        }

        RCLCPP_INFO(this->get_logger(), "Kinematics Node 啟動完成");
    }

private:
    // =========================================================================
    //  cmd_vel → 輪速 (正運動學) → Serial TX
    // =========================================================================

    /**
     * @brief /cmd_vel 回呼
     *
     * 1. 差速運動學：
     *      v_left  = linear_x - (angular_z * car_distance / 2)
     *      v_right = linear_x + (angular_z * car_distance / 2)
     *
     * 2. 轉換為 Arduino 驅動器格式：
     *      - cmd_vel_to_serial.py 使用 RPM 整數: RPM = (v / circumference) * 60 * gear_ratio
     *      - car_controller.py 使用驅動器脈衝速度: speed_cmd = v / speed_1_every_second_speed
     *
     *    這裡保留 cmd_vel_to_serial.py 的 JSON 格式 {"m":0,"ls":RPM,"rs":RPM}
     *    因為 Arduino car_json_cmd.ino 接收的就是這個格式
     */
    void cmd_vel_callback(const geometry_msgs::msg::Twist::SharedPtr msg)
    {
        if (car_mode_ != "diff") {
            RCLCPP_ERROR_THROTTLE(this->get_logger(), *this->get_clock(), 5000,
                                  "目前僅支援 diff (差速) 模式！");
            return;
        }

        const double linear_x  = msg->linear.x;   // m/s
        const double angular_z = msg->angular.z;   // rad/s

        // 暫存 (供開迴路 Odom 使用)
        last_linear_x_  = linear_x;
        last_linear_y_  = msg->linear.y;
        last_angular_z_ = angular_z;

        // ---- 差速運動學 ----
        const double v_left  = linear_x - (angular_z * car_distance_ / 2.0);
        const double v_right = linear_x + (angular_z * car_distance_ / 2.0);

        // ---- m/s → RPM (同 cmd_vel_to_serial.py) ----
        // RPM = (v / circumference) * 60 * gear_ratio
        const int rpm_left  = static_cast<int>((v_left  / tire_circumference_) * 60.0 * gear_ratio_);
        const int rpm_right = static_cast<int>((v_right / tire_circumference_) * 60.0 * gear_ratio_);

        // ---- 組合 JSON 並發布至 serial_tx ----
        json cmd;
        cmd["m"]  = 0;
        cmd["ls"] = rpm_left;
        cmd["rs"] = rpm_right;

        auto tx_msg = std_msgs::msg::String();
        tx_msg.data = cmd.dump();
        pub_serial_tx_->publish(tx_msg);

        RCLCPP_DEBUG(this->get_logger(), "cmd_vel → TX: %s", tx_msg.data.c_str());
    }

    // =========================================================================
    //  Serial RX → Encoder 解析 → Odom/TF (閉迴路逆運動學)
    // =========================================================================

    /**
     * @brief /serial_rx 回呼 — 解析 Arduino 主動推送的 JSON
     *
     * Arduino 回傳新格式（push_encoder() 產生）：
     *   {"p1": <左輪ticks>, "p2": <右輪ticks>}
     *
     * 收到就直接觸發逆運動學計算，不需等待兩個分離的封包。
     */
    void serial_rx_callback(const std_msgs::msg::String::SharedPtr msg)
    {
        if (!use_encoder_feedback_) return;

        try {
            auto j = json::parse(msg->data);

            // 新格式：{"p1": x, "p2": y} 左右輪同封包
            if (j.contains("p1") && j.contains("p2")) {
                last_left_encoder_  = j["p1"].get<long>();
                last_right_encoder_ = j["p2"].get<long>();
                compute_encoder_odom(); // 直接觸發，不需等待兩次
            }

        } catch (const json::parse_error &) {
            RCLCPP_DEBUG_THROTTLE(this->get_logger(), *this->get_clock(), 2000,
                                  "丟棄非 JSON 字串: %s", msg->data.c_str());
        }
    }

    /**
     * @brief 從 encoder ticks 計算 Odometry 並發布
     */
    void compute_encoder_odom()
    {
        const auto current_time = this->now();
        const double dt = (current_time - last_time_).seconds();
        if (dt <= 0.0) return;

        if (prev_left_encoder_.has_value() && prev_right_encoder_.has_value()) {
            const long delta_left  = last_left_encoder_  - prev_left_encoder_.value();
            const long delta_right = last_right_encoder_ - prev_right_encoder_.value();

            const double dist_left  = static_cast<double>(delta_left)  * distance_per_pulse_;
            const double dist_right = static_cast<double>(delta_right) * distance_per_pulse_;

            const double odom_vx = (dist_right + dist_left) / (2.0 * dt);
            const double odom_vy = 0.0;
            const double odom_wz = (dist_right - dist_left) / (car_distance_ * dt);

            // Odom 積分
            integrate_odom(odom_vx, odom_vy, odom_wz, dt);

            // 發布
            publish_odom_and_tf(current_time, odom_vx, odom_vy, odom_wz);
        }

        prev_left_encoder_  = last_left_encoder_;
        prev_right_encoder_ = last_right_encoder_;
        last_time_ = current_time;
    }

    // =========================================================================
    //  開迴路 Odom (使用 cmd_vel 積分，無 encoder feedback)
    // =========================================================================

    void odom_openloop_callback()
    {
        const auto current_time = this->now();
        const double dt = (current_time - last_time_).seconds();
        if (dt <= 0.0) return;

        integrate_odom(last_linear_x_, last_linear_y_, last_angular_z_, dt);
        publish_odom_and_tf(current_time, last_linear_x_, last_linear_y_, last_angular_z_);

        last_time_ = current_time;
    }

    // =========================================================================
    //  共用：Odom 積分 & 發布
    // =========================================================================

    /**
     * @brief 2D Odom 積分 (同原 Python 版)
     */
    void integrate_odom(double vx, double vy, double wz, double dt)
    {
        const double delta_x  = (vx * std::cos(theta_) - vy * std::sin(theta_)) * dt;
        const double delta_y  = (vx * std::sin(theta_) + vy * std::cos(theta_)) * dt;
        const double delta_th = wz * dt;

        x_     += delta_x;
        y_     += delta_y;
        theta_ += delta_th;
    }

    /**
     * @brief 發布 /odom 訊息 與 TF (odom → base_link)
     */
    void publish_odom_and_tf(const rclcpp::Time &stamp,
                             double vx, double vy, double wz)
    {
        // --- 四元數 ---
        tf2::Quaternion q;
        q.setRPY(0.0, 0.0, theta_);

        // --- TF ---
        geometry_msgs::msg::TransformStamped tf;
        tf.header.stamp    = stamp;
        tf.header.frame_id = "odom";
        tf.child_frame_id  = "base_link";
        tf.transform.translation.x = x_;
        tf.transform.translation.y = y_;
        tf.transform.translation.z = 0.0;
        tf.transform.rotation.x = q.x();
        tf.transform.rotation.y = q.y();
        tf.transform.rotation.z = q.z();
        tf.transform.rotation.w = q.w();
        tf_broadcaster_->sendTransform(tf);

        // --- Odometry ---
        nav_msgs::msg::Odometry odom;
        odom.header.stamp    = stamp;
        odom.header.frame_id = "odom";
        odom.child_frame_id  = "base_link";

        odom.pose.pose.position.x = x_;
        odom.pose.pose.position.y = y_;
        odom.pose.pose.position.z = 0.0;
        odom.pose.pose.orientation.x = q.x();
        odom.pose.pose.orientation.y = q.y();
        odom.pose.pose.orientation.z = q.z();
        odom.pose.pose.orientation.w = q.w();

        odom.twist.twist.linear.x  = vx;
        odom.twist.twist.linear.y  = vy;
        odom.twist.twist.angular.z = wz;

        pub_odom_->publish(odom);
    }

    // =========================================================================
    //  成員變數
    // =========================================================================

    // --- 車體/運動學參數 ---
    double car_distance_;
    std::string car_mode_;
    double tire_diameter_;
    int encoder_resolution_;
    double gear_ratio_;
    int odom_up_hz_;
    bool use_encoder_feedback_;

    double tire_circumference_;  // π * D
    double tire_radius_;
    double total_pulses_;        // gear_ratio * encoder_resolution
    double distance_per_pulse_;  // π * D / total_pulses
    double speed_1_per_second_;  // 原 Python 版 speed_1_every_second_speed

    // --- Odom 狀態 ---
    double x_, y_, theta_;
    double last_linear_x_, last_linear_y_, last_angular_z_;
    rclcpp::Time last_time_;

    // --- Encoder 追蹤 ---
    long last_left_encoder_{0};
    long last_right_encoder_{0};
    std::optional<long> prev_left_encoder_;
    std::optional<long> prev_right_encoder_;

    // --- ROS 介面 ---
    rclcpp::Publisher<std_msgs::msg::String>::SharedPtr pub_serial_tx_;
    rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr pub_odom_;
    std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;

    rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr sub_cmd_vel_;
    rclcpp::Subscription<std_msgs::msg::String>::SharedPtr sub_serial_rx_;

    rclcpp::TimerBase::SharedPtr odom_timer_;  // 僅開迴路模式使用
};

// =============================================================================
//  main
// =============================================================================
int main(int argc, char *argv[])
{
    rclcpp::init(argc, argv);

    auto node = std::make_shared<KinematicsNode>();
    rclcpp::spin(node);

    rclcpp::shutdown();
    return 0;
}
