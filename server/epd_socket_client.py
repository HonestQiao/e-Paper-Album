#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPD Socket Client - 电子纸网络测试客户端

用于验证 TuyaOpen e-Paper 示例项目的 Socket 服务端。
连接服务器并发送命令，支持交互模式和命令行模式。

功能:
- 连接服务器并发送命令
- 支持交互模式和批量模式
- 支持图片轮询测试
- 支持下载图片二进制数据

使用方法:
    python epd_socket_client.py [--host HOST] [--port PORT] [command]

示例:
    python epd_socket_client.py                    # 交互模式
    python epd_socket_client.py update             # 发送 update 命令
    python epd_socket_client.py get -o ./downloaded # 下载当前图片
    python epd_socket_client.py --host 127.0.0.1 --port 18888 status

Copyright (c) 2025 Tuya Inc. All Rights Reserved.
"""

import socket
import argparse
import sys
import json
import time
import os
import struct
from typing import Optional

# 配置
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18888
BUFFER_SIZE = 8192
DEFAULT_TIMEOUT = 10.0


def log_message(message: str, level: str = "INFO") -> None:
    """打印日志消息"""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def parse_response(response: str) -> dict:
    """解析 JSON 响应"""
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"raw": response, "error": "Failed to parse response"}


class EPDSocketClient:
    """EPD Socket 客户端类"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.output_dir = "./downloaded"
        self.socket: Optional[socket.socket] = None

    def connect(self) -> bool:
        """
        连接到服务器

        Returns:
            True 表示连接成功
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))
            log_message(f"Connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            log_message(f"Connection failed: {e}", "ERROR")
            return False

    def send_command(self, command: str) -> Optional[dict]:
        """
        发送命令并获取 JSON 响应

        Args:
            command: 要发送的命令

        Returns:
            解析后的响应 dict，或 None 表示失败
        """
        if not self.socket:
            log_message("Not connected", "ERROR")
            return None

        try:
            # 发送命令
            self.socket.sendall(command.encode('utf-8'))
            log_message(f"Sent: {command}")

            # 接收响应
            data = self.socket.recv(BUFFER_SIZE)
            if not data:
                log_message("Server closed connection", "WARNING")
                return None

            response = data.decode('utf-8')
            log_message(f"Received: {response[:200]}..." if len(response) > 200 else f"Received: {response}")

            return parse_response(response)

        except socket.timeout:
            log_message("Receive timeout", "ERROR")
            return None
        except Exception as e:
            log_message(f"Error: {e}", "ERROR")
            return None

    def download_current_image(self, use_c_array: bool = False) -> bool:
        """
        下载当前图片到指定目录

        流程: info -> get 或 info -> get_c

        Args:
            use_c_array: 是否使用 get_c 命令（获取 C 数组格式）

        Returns:
            True 表示成功
        """
        if not self.socket:
            log_message("Not connected", "ERROR")
            return False

        try:
            # 使用 info 获取当前图片信息（不推进索引）
            info_resp = self.send_command("info")
            if not info_resp or info_resp.get("status") != "success":
                log_message("Failed to get image info", "ERROR")
                return False

            data_info = info_resp.get("data", {})
            filename = data_info.get("filename", "image.bmp")
            log_message(f"Image: {filename}")

            # 根据模式选择命令
            cmd = b"get_c" if use_c_array else b"get"
            cmd_str = "get_c" if use_c_array else "get"
            self.socket.sendall(cmd)
            log_message(f"Sent: {cmd_str}")

            # 接收 4 字节长度头部
            header = self.socket.recv(4)
            if len(header) < 4:
                log_message("Failed to receive header", "ERROR")
                return False

            data_len = struct.unpack('>I', header)[0]
            log_message(f"Data size: {data_len} bytes")

            # 接收数据
            received = 0
            data = b''
            while received < data_len:
                chunk = self.socket.recv(min(BUFFER_SIZE, data_len - received))
                if not chunk:
                    log_message("Connection closed", "ERROR")
                    return False
                data += chunk
                received += len(chunk)

            # 保存文件
            os.makedirs(self.output_dir, exist_ok=True)
            if use_c_array:
                # get_c: 修改文件名后缀为 .bin
                base_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
                output_filename = f"{base_name}.bin"
            else:
                output_filename = filename
            output_path = os.path.join(self.output_dir, output_filename)
            with open(output_path, 'wb') as f:
                f.write(data)

            log_message(f"Saved: {output_path} ({len(data)} bytes)")
            return True

        except socket.timeout:
            log_message("Receive timeout", "ERROR")
            return False
        except Exception as e:
            log_message(f"Download failed: {e}", "ERROR")
            return False

    def close(self) -> None:
        """关闭连接"""
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            log_message("Connection closed")


def interactive_mode(client: EPDSocketClient) -> None:
    """交互模式"""
    print("\n=== EPD Socket Client - Interactive Mode ===")
    print("Commands: update, info, get, get_c, list, status, refresh, reload, reset, quit")
    print("-" * 50)
    print(f"Output directory: {client.output_dir}")
    print("-" * 50)

    while True:
        try:
            cmd = input("\nEnter command (or 'quit' to exit): ").strip()
            if not cmd:
                continue

            if cmd.lower() == 'quit' or cmd.lower() == 'exit':
                print("Goodbye!")
                break

            if cmd.lower() == 'get':
                client.download_current_image(use_c_array=False)
                continue

            if cmd.lower() == 'get_c':
                client.download_current_image(use_c_array=True)
                continue

            response = client.send_command(cmd)
            if response:
                print(f"\nResponse:\n{json.dumps(response, indent=2, ensure_ascii=False)}")

        except KeyboardInterrupt:
            print("\nInterrupted")
            break


def batch_mode(client: EPDSocketClient, commands: list) -> None:
    """批量命令模式"""
    log_message(f"Running {len(commands)} commands...")

    for i, cmd in enumerate(commands, 1):
        cmd_lower = cmd.lower()

        # 处理 get 命令（下载 BMP）
        if cmd_lower == "get":
            log_message(f"\n--- Downloading BMP {i}/{len(commands)} ---")
            client.download_current_image(use_c_array=False)
            continue

        # 处理 get_c 命令（下载 C 数组）
        if cmd_lower == "get_c":
            log_message(f"\n--- Downloading C array {i}/{len(commands)} ---")
            client.download_current_image(use_c_array=True)
            continue

        log_message(f"\n--- Command {i}/{len(commands)}: {cmd} ---")
        response = client.send_command(cmd)
        if response:
            print(json.dumps(response, indent=2, ensure_ascii=False))
        time.sleep(0.5)


def slideshow_mode(client: EPDSocketClient, count: int = 5) -> None:
    """
    幻灯片模式 - 多次调用 update 测试图片轮询

    Args:
        client: 客户端实例
        count: 循环次数
    """
    log_message(f"Slideshow mode: {count} updates")

    for i in range(count):
        log_message(f"\n--- Update {i+1}/{count} ---")
        response = client.send_command("update")
        if response:
            print(json.dumps(response, indent=2, ensure_ascii=False))

            data = response.get("data", {})
            if data:
                filename = data.get("filename", "Unknown")
                index = data.get("index", 0)
                total = data.get("total", 0)
                log_message(f"Image {index}/{total}: {filename}")
        time.sleep(1)


def download_mode(client: EPDSocketClient, count: int = 1) -> bool:
    """
    下载模式 - 下载当前图片

    Args:
        client: 客户端实例
        count: 下载次数

    Returns:
        True 表示成功
    """
    log_message(f"Download mode: {count} image(s) to {client.output_dir}")

    success = True
    for i in range(count):
        log_message(f"\n--- Downloading {i+1}/{count} ---")
        if not client.download_current_image():
            success = False
            break
        time.sleep(0.5)

    return success


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="EPD Socket Client - 电子纸网络测试客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
交互模式命令:
    update   - 返回下一张图片信息（循环）
    info     - 返回当前图片信息（不推进索引）
    get      - 下载当前图片的二进制数据
    list     - 返回所有图片列表
    status   - 返回设备状态
    refresh  - 返回刷新状态
    reload   - 重新扫描图片目录
    reset    - 重置图片索引到开头
    quit     - 退出程序

示例:
    python epd_socket_client.py                              # 交互模式
    python epd_socket_client.py update                       # 发送 update 命令
    python epd_socket_client.py get -o ./downloaded          # 下载当前图片
    python epd_socket_client.py update info get              # 批量命令
    python epd_socket_client.py --host 192.168.1.15 update   # 指定服务器地址
        """
    )

    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"服务器地址 (默认: {DEFAULT_HOST})"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"服务器端口 (默认: {DEFAULT_PORT})"
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"超时时间秒 (默认: {DEFAULT_TIMEOUT})"
    )

    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default="./downloaded",
        help=f"下载输出目录 (默认: ./downloaded)"
    )

    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="get 命令的下载次数 (默认: 1)"
    )

    parser.add_argument(
        "commands",
        nargs="*",
        help="要发送的命令 (留空进入交互模式)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="启用详细输出"
    )

    args = parser.parse_args()

    # 创建客户端
    client = EPDSocketClient(host=args.host, port=args.port, timeout=args.timeout)
    client.output_dir = args.output_dir

    # 连接服务器
    if not client.connect():
        log_message("Failed to connect to server", "ERROR")
        sys.exit(1)

    try:
        if args.commands:
            # 批量模式
            batch_mode(client, args.commands)
        else:
            # 交互模式
            interactive_mode(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()
