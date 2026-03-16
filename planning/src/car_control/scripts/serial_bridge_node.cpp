/**
 * @file serial_bridge_node.cpp
 * @brief ROS 2 Serial Bridge Node — 獨佔 Serial Port，負責 ROS Topics ↔ UART JSON 雙向轉換
 *
 * 職責：
 *   1. 訂閱 /serial_tx (std_msgs/String)，將 JSON 字串寫入 Serial Port
 *   2. 定時讀取 Serial Port，將收到的完整 JSON 行發布至 /serial_rx (std_msgs/String)
 *   3. 節點關閉時自動送出停車命令 {"m":0,"ls":0,"rs":0}
 *
 * 設計理念：
 *   - 此節點「不理解」JSON 內容的語義，它只是一個透明的 Serial ↔ Topic 橋接器
 *   - 所有運動學邏輯由 kinematics_node 處理
 *   - Serial 使用 POSIX termios 非阻塞式 I/O，避免阻塞 ROS callback
 *
 * 編譯依賴：rclcpp, std_msgs
 */

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>

#include <fcntl.h>
#include <termios.h>
#include <unistd.h>
#include <errno.h>
#include <cstring>
#include <string>
#include <mutex>

class SerialBridgeNode : public rclcpp::Node
{
public:
    SerialBridgeNode()
        : Node("serial_bridge_node"), serial_fd_(-1)
    {
        // ---------- 宣告參數 ----------
        this->declare_parameter<std::string>("usb_port", "/dev/ttyACM0");
        this->declare_parameter<int>("baudrate", 115200);
        this->declare_parameter<int>("serial_read_hz", 50);

        const auto port = this->get_parameter("usb_port").as_string();
        const auto baudrate = this->get_parameter("baudrate").as_int();
        const auto read_hz = this->get_parameter("serial_read_hz").as_int();

        // ---------- 初始化 Serial Port (POSIX termios) ----------
        if (!open_serial(port, baudrate)) {
            RCLCPP_FATAL(this->get_logger(), "無法開啟 Serial Port: %s", port.c_str());
            throw std::runtime_error("Serial port open failed");
        }
        RCLCPP_INFO(this->get_logger(), "成功連接底層控制板: %s @ %d baud", port.c_str(), static_cast<int>(baudrate));

        // ---------- Publisher: Serial RX → ROS Topic ----------
        pub_serial_rx_ = this->create_publisher<std_msgs::msg::String>("serial_rx", 10);

        // ---------- Subscriber: ROS Topic → Serial TX ----------
        sub_serial_tx_ = this->create_subscription<std_msgs::msg::String>(
            "serial_tx", 10,
            std::bind(&SerialBridgeNode::serial_tx_callback, this, std::placeholders::_1));

        // ---------- Timer: 定時讀取 Serial Port ----------
        const auto period_ms = std::chrono::milliseconds(1000 / read_hz);
        read_timer_ = this->create_wall_timer(
            period_ms, std::bind(&SerialBridgeNode::read_serial_callback, this));

        RCLCPP_INFO(this->get_logger(), "Serial Bridge 啟動完成 (read_hz=%d)", static_cast<int>(read_hz));
    }

    ~SerialBridgeNode() override
    {
        // 安全停車：關閉前送出零速命令
        if (serial_fd_ >= 0) {
            const std::string stop_cmd = "{\"m\":0,\"ls\":0,\"rs\":0}\n";
            write_serial(stop_cmd);
            RCLCPP_INFO(this->get_logger(), "送出停車命令，關閉 Serial Port");
            ::close(serial_fd_);
            serial_fd_ = -1;
        }
    }

private:
    // =========================================================================
    //  Serial Port 操作 (POSIX termios, 非阻塞)
    // =========================================================================

    /**
     * @brief 以非阻塞模式開啟 Serial Port
     * @param port  裝置路徑，例如 "/dev/ttyUSB0"
     * @param baudrate  鮑率，僅支援常見值 (9600, 115200, ...)
     * @return true 成功
     */
    bool open_serial(const std::string &port, int baudrate)
    {
        serial_fd_ = ::open(port.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
        if (serial_fd_ < 0) {
            RCLCPP_ERROR(this->get_logger(), "open() 失敗: %s (%s)", port.c_str(), strerror(errno));
            return false;
        }

        struct termios tty{};
        if (tcgetattr(serial_fd_, &tty) != 0) {
            RCLCPP_ERROR(this->get_logger(), "tcgetattr() 失敗: %s", strerror(errno));
            ::close(serial_fd_);
            serial_fd_ = -1;
            return false;
        }

        // ---------- 鮑率 ----------
        speed_t baud_flag = baud_to_flag(baudrate);
        cfsetispeed(&tty, baud_flag);
        cfsetospeed(&tty, baud_flag);

        // ---------- 8N1, 無流控 ----------
        tty.c_cflag &= ~PARENB;        // 無同位元
        tty.c_cflag &= ~CSTOPB;        // 1 stop bit
        tty.c_cflag &= ~CSIZE;
        tty.c_cflag |= CS8;            // 8 data bits
        tty.c_cflag &= ~CRTSCTS;       // 無硬體流控
        tty.c_cflag |= CREAD | CLOCAL; // 啟用接收，忽略 modem 控制

        // ---------- Raw mode ----------
        tty.c_lflag &= ~(ICANON | ECHO | ECHOE | ISIG);
        tty.c_iflag &= ~(IXON | IXOFF | IXANY);
        tty.c_iflag &= ~(IGNBRK | BRKINT | PARMRK | ISTRIP | INLCR | IGNCR | ICRNL);
        tty.c_oflag &= ~OPOST;

        // ---------- 非阻塞讀取 ----------
        tty.c_cc[VMIN] = 0;   // 不等待最少字元數
        tty.c_cc[VTIME] = 0;  // 立即返回

        if (tcsetattr(serial_fd_, TCSANOW, &tty) != 0) {
            RCLCPP_ERROR(this->get_logger(), "tcsetattr() 失敗: %s", strerror(errno));
            ::close(serial_fd_);
            serial_fd_ = -1;
            return false;
        }

        tcflush(serial_fd_, TCIOFLUSH); // 清除輸入/輸出緩衝
        return true;
    }

    /**
     * @brief 將整數鮑率轉成 termios speed_t flag
     */
    static speed_t baud_to_flag(int baudrate)
    {
        switch (baudrate) {
            case 9600:   return B9600;
            case 19200:  return B19200;
            case 38400:  return B38400;
            case 57600:  return B57600;
            case 115200: return B115200;
            case 230400: return B230400;
            case 460800: return B460800;
            case 921600: return B921600;
            default:     return B115200;
        }
    }

    /**
     * @brief 非阻塞寫入 Serial Port
     */
    void write_serial(const std::string &data)
    {
        std::lock_guard<std::mutex> lock(serial_mutex_);
        if (serial_fd_ < 0) return;

        ssize_t total = 0;
        ssize_t len = static_cast<ssize_t>(data.size());
        while (total < len) {
            ssize_t n = ::write(serial_fd_, data.c_str() + total, len - total);
            if (n < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    // 暫時無法寫入，稍後重試
                    usleep(100);
                    continue;
                }
                RCLCPP_ERROR(this->get_logger(), "write() 失敗: %s", strerror(errno));
                return;
            }
            total += n;
        }
        // tcdrain 確保資料送出
        tcdrain(serial_fd_);
    }

    // =========================================================================
    //  ROS Callbacks
    // =========================================================================

    /**
     * @brief 收到 serial_tx topic 訊息 → 寫入 Serial Port
     *        訊息內容直接是一個完整的 JSON 字串（不含 '\n'），本節點自動加上換行
     */
    void serial_tx_callback(const std_msgs::msg::String::SharedPtr msg)
    {
        std::string data = msg->data;
        if (data.empty()) return;

        // 確保以換行結尾（Arduino 以 '\n' 作為封包界定符）
        if (data.back() != '\n') {
            data.push_back('\n');
        }

        write_serial(data);
        RCLCPP_DEBUG(this->get_logger(), "TX → %s", msg->data.c_str());
    }

    /**
     * @brief 定時從 Serial Port 非阻塞讀取，遇到 '\n' 就將該行發布至 serial_rx
     */
    void read_serial_callback()
    {
        std::lock_guard<std::mutex> lock(serial_mutex_);
        if (serial_fd_ < 0) return;

        char buf[512];
        ssize_t n = ::read(serial_fd_, buf, sizeof(buf) - 1);
        if (n <= 0) return;

        // 將讀到的資料附加到內部緩衝
        rx_buffer_.append(buf, static_cast<size_t>(n));

        // 逐行切割，每遇到 '\n' 就發布一則訊息
        std::string::size_type pos;
        while ((pos = rx_buffer_.find('\n')) != std::string::npos) {
            std::string line = rx_buffer_.substr(0, pos);
            rx_buffer_.erase(0, pos + 1);

            if (line.empty()) continue;
            // 去除可能的 '\r'
            if (!line.empty() && line.back() == '\r') {
                line.pop_back();
            }
            if (line.empty()) continue;

            auto out_msg = std_msgs::msg::String();
            out_msg.data = line;
            pub_serial_rx_->publish(out_msg);
            RCLCPP_DEBUG(this->get_logger(), "RX ← %s", line.c_str());
        }

        // 防止因 Arduino 無換行導致的緩衝溢出
        if (rx_buffer_.size() > 4096) {
            RCLCPP_WARN(this->get_logger(), "RX 緩衝超過 4KB，清除");
            rx_buffer_.clear();
        }
    }

    // =========================================================================
    //  成員變數
    // =========================================================================
    int serial_fd_;
    std::mutex serial_mutex_;
    std::string rx_buffer_;

    rclcpp::Publisher<std_msgs::msg::String>::SharedPtr pub_serial_rx_;
    rclcpp::Subscription<std_msgs::msg::String>::SharedPtr sub_serial_tx_;
    rclcpp::TimerBase::SharedPtr read_timer_;
};

// =============================================================================
//  main
// =============================================================================
int main(int argc, char *argv[])
{
    rclcpp::init(argc, argv);

    auto node = std::make_shared<SerialBridgeNode>();
    rclcpp::spin(node);

    rclcpp::shutdown();
    return 0;
}
