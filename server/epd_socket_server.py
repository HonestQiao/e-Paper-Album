#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPD Socket Server - 电子纸网络测试服务端 (增强版)

用于 TuyaOpen e-Paper 示例项目的网络通信测试。
监听 18888 端口，接收客户端发送的命令并返回响应。

增强功能:
- 文件监控：自动检测目录变化
- 文件排序：根据文件名排序（支持数字文件名）
- 自动重载：检测到变化时自动重新加载图片

功能:
- 监听 TCP 连接
- 接收命令并返回响应
- 支持 "update" 命令返回下一张图片信息
- 支持扫描 bmp 图片目录并轮询
- 支持下载图片二进制数据
- 记录连接和通信日志

使用方法:
    python epd_socket_server.py [--host HOST] [--port PORT] [--image-dir DIR]

示例:
    python epd_socket_server.py                          # 使用默认配置
    python epd_socket_server.py --image-dir ./dist       # 指定图片目录
    python epd_socket_server.py --host 0.0.0.0 --port 8080

Copyright (c) 2025 Tuya Inc. All Rights Reserved.
"""

import socket
import argparse
import sys
import threading
import datetime
import json
import os
import struct
from typing import Optional, List, Dict
import time

# 配置
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 18888
DEFAULT_IMAGE_DIR = "./dist"
BUFFER_SIZE = 8192
FILE_CHECK_INTERVAL = 5  # 检查文件变化的时间间隔（秒）
FILE_CHANGE_DEBOUNCE = 5  # 文件变化防抖动时间（秒）


def log_message(message: str, level: str = "INFO") -> None:
    """打印日志消息"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def scan_bmp_images(image_dir: str) -> List[str]:
    """
    扫描目录下所有 bmp 图片并排序

    Args:
        image_dir: 图片目录路径

    Returns:
        排序后的 bmp 文件路径列表
    """
    if not os.path.isdir(image_dir):
        return []

    bmp_files = []
    file_stats = []

    for f in os.listdir(image_dir):
        if f.lower().endswith('.bmp'):
            full_path = os.path.join(image_dir, f)
            if os.path.isfile(full_path):
                stat = os.stat(full_path)
                file_stats.append({
                    'path': full_path,
                    'name': f,
                    'mtime': stat.st_mtime,
                    'size': stat.st_size
                })

    # 按文件名排序（确保数字文件名正确排序）
    def sort_key(item):
        name = item['name']
        # 提取文件名前的数字
        parts = name.split('_')
        if len(parts) > 0 and parts[0].isdigit():
            return int(parts[0])
        return name.lower()

    file_stats.sort(key=sort_key)

    # 返回路径列表
    for stat in file_stats:
        bmp_files.append(stat['path'])

    return bmp_files


def get_file_checksums(image_dir: str) -> Dict[str, tuple]:
    """
    获取文件的校验和（修改时间+大小）

    Args:
        image_dir: 图片目录路径

    Returns:
        文件名 -> (mtime, size) 的字典
    """
    checksums = {}
    if not os.path.isdir(image_dir):
        return checksums

    for f in os.listdir(image_dir):
        if f.lower().endswith('.bmp'):
            full_path = os.path.join(image_dir, f)
            if os.path.isfile(full_path):
                stat = os.stat(full_path)
                checksums[f] = (stat.st_mtime, stat.st_size)

    return checksums


class EPDSocketServer:
    """EPD Socket 服务器类"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, image_dir: str = DEFAULT_IMAGE_DIR, enable_file_monitor: bool = True):
        self.host = host
        self.port = port
        self.image_dir = image_dir
        self.image_list: List[str] = []
        self.current_index = 0
        self.lock = threading.Lock()
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self.client_threads = []
        self.last_checksums: Dict[str, tuple] = {}
        self.file_monitor_thread: Optional[threading.Thread] = None
        self.enable_file_monitor = enable_file_monitor
        # 防抖动相关
        self.last_change_time = 0.0
        self.pending_reload = False

    def load_images(self) -> int:
        """加载图片列表"""
        old_count = len(self.image_list)
        self.image_list = scan_bmp_images(self.image_dir)
        old_index = self.current_index

        # 重置索引
        self.current_index = 0

        # 更新校验和
        self.last_checksums = get_file_checksums(self.image_dir)

        log_message(f"Loaded {len(self.image_list)} BMP images from {self.image_dir}")
        for i, img in enumerate(self.image_list):
            log_message(f"  [{i+1}] {os.path.basename(img)}")

        # 如果图片数量发生变化，记录变化
        if old_count != len(self.image_list):
            log_message(f"Image count changed: {old_count} -> {len(self.image_list)}", "WARN")

        # 如果索引超出范围，重置
        if self.current_index >= len(self.image_list):
            self.current_index = 0

        return len(self.image_list)

    def check_file_changes(self) -> bool:
        """
        检查文件是否有变化

        Returns:
            True 表示有变化
        """
        current_checksums = get_file_checksums(self.image_dir)

        # 检查新增或删除的文件
        if set(current_checksums.keys()) != set(self.last_checksums.keys()):
            # 更新校验和
            self.last_checksums = current_checksums
            return True

        # 检查文件修改时间和大小
        for filename, (mtime, size) in current_checksums.items():
            if filename not in self.last_checksums:
                # 更新校验和
                self.last_checksums = current_checksums
                return True
            old_mtime, old_size = self.last_checksums[filename]
            if mtime != old_mtime or size != old_size:
                # 更新校验和
                self.last_checksums = current_checksums
                return True

        return False

    def file_monitor_loop(self):
        """文件监控循环（带防抖动机制）"""
        try:
            log_message("File monitor thread started")
            self.load_images()  # 初始加载

            while self.running:
                try:
                    current_time = time.time()

                    # 检查文件变化
                    if self.check_file_changes():
                        log_message("File changes detected, starting debounce timer...")
                        self.last_change_time = current_time
                        self.pending_reload = True

                    # 如果有待执行的重载且已超时
                    if self.pending_reload and (current_time - self.last_change_time) >= FILE_CHANGE_DEBOUNCE:
                        log_message(f"Debounce timeout ({FILE_CHANGE_DEBOUNCE}s), reloading images...")
                        old_count = len(self.image_list)
                        self.load_images()
                        new_count = len(self.image_list)
                        log_message(f"Reloaded: {old_count} -> {new_count} images")
                        self.pending_reload = False
                        self.last_change_time = 0.0

                    time.sleep(FILE_CHECK_INTERVAL)
                except Exception as e:
                    log_message(f"File monitor error: {e}", "ERROR")
                    time.sleep(FILE_CHECK_INTERVAL)

            log_message("File monitor thread stopped normally")
        except Exception as e:
            log_message(f"File monitor thread fatal error: {e}", "ERROR")
            # 不重新抛出异常，避免线程意外终止

    def get_next_image(self) -> Optional[dict]:
        """获取下一张图片信息（循环）- 先返回当前图片再推进索引"""
        if not self.image_list:
            return None

        with self.lock:
            image_path = self.image_list[self.current_index]
            image_name = os.path.basename(image_path)
            image_size = os.path.getsize(image_path)

            # 获取文件修改时间
            mtime = os.path.getmtime(image_path)
            mtime_str = datetime.datetime.fromtimestamp(mtime).isoformat()

            result = {
                "index": self.current_index + 1,
                "total": len(self.image_list),
                "filename": image_name,
                "path": image_path,
                "size_bytes": image_size,
                "modified": mtime_str
            }

            # 先返回当前图片，然后推进索引
            self.current_index = (self.current_index + 1) % len(self.image_list)

            return result

    def get_current_image_path(self) -> Optional[str]:
        """获取当前图片路径（不推进索引）- current_index 是 1-based"""
        if not self.image_list:
            return None

        with self.lock:
            if self.current_index <= 0 or self.current_index > len(self.image_list):
                self.current_index = 1
            return self.image_list[self.current_index - 1]

    def get_current_image_info(self) -> Optional[dict]:
        """获取当前图片信息（不推进索引）- current_index 是 1-based"""
        if not self.image_list:
            return None

        with self.lock:
            if self.current_index <= 0 or self.current_index > len(self.image_list):
                self.current_index = 1

            image_path = self.image_list[self.current_index - 1]
            image_name = os.path.basename(image_path)
            image_size = os.path.getsize(image_path)

            mtime = os.path.getmtime(image_path)
            mtime_str = datetime.datetime.fromtimestamp(mtime).isoformat()

            return {
                "index": self.current_index,
                "total": len(self.image_list),
                "filename": image_name,
                "path": image_path,
                "size_bytes": image_size,
                "modified": mtime_str
            }

    def send_image_data(self, client_socket: socket.socket) -> bool:
        """
        发送当前图片的二进制数据

        发送格式: 4字节长度(大端) + 二进制数据

        Args:
            client_socket: 客户端 socket

        Returns:
            True 表示成功
        """
        image_path = self.get_current_image_path()
        if not image_path:
            error_msg = json.dumps({
                "status": "error",
                "message": "No images available"
            }, ensure_ascii=False)
            client_socket.sendall(error_msg.encode('utf-8'))
            return False

        try:
            # 读取文件二进制数据
            with open(image_path, 'rb') as f:
                data = f.read()

            # 发送：4字节长度 + 二进制数据
            header = struct.pack('>I', len(data))
            client_socket.sendall(header + data)

            log_message(f"Sent image data: {os.path.basename(image_path)} ({len(data)} bytes)")
            return True

        except Exception as e:
            log_message(f"Failed to send image: {e}", "ERROR")
            error_msg = json.dumps({
                "status": "error",
                "message": str(e)
            }, ensure_ascii=False)
            client_socket.sendall(error_msg.encode('utf-8'))
            return False

    def bmp_to_c_array(self, image_path: str) -> bytes:
        """
        将 BMP 图片转换为 6 色 C 数组二进制数据

        格式: 每像素 4 位，每字节存储 2 像素
        高 4 位 = 第一个像素，低 4 位 = 第二个像素
        6 色: 黑(0), 白(1), 黄(2), 红(3), 蓝(4), 绿(5)

        Args:
            image_path: BMP 图片路径

        Returns:
            转换后的二进制数据
        """
        from PIL import Image

        # 6 色调色板
        PALETTE_6COLOR = [
            (0, 0, 0),         # 黑色
            (255, 255, 255),   # 白色
            (255, 255, 0),     # 黄色
            (255, 0, 0),       # 红色
            (0, 0, 255),       # 蓝色
            (0, 255, 0),       # 绿色
        ]

        def find_closest_color_index(pixel, palette):
            """找到最接近的调色板颜色，返回索引"""
            mindiff = float('inf')
            best_index = 0

            for idx, color in enumerate(palette):
                diffr = pixel[0] - color[0]
                diffg = pixel[1] - color[1]
                diffb = pixel[2] - color[2]
                diff = diffr * diffr + diffg * diffg + diffb * diffb

                if diff < mindiff:
                    mindiff = diff
                    best_index = idx

            return best_index

        # 打开图片
        image = Image.open(image_path)
        width, height = image.size

        # 转换为 RGB 模式
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # 获取像素数据 (兼容新旧版本 Pillow)
        try:
            # 新版本 Pillow (推荐)
            pixels = list(image.get_flattened_data())
        except AttributeError:
            # 旧版本 Pillow (fallback)
            pixels = list(image.getdata())

        # 转换数据
        output_data = bytearray()
        out_width = width // 2

        for y in range(height):
            for x_pair in range(out_width):
                # 获取 2 个像素
                pixel1 = pixels[y * width + x_pair * 2]
                pixel2 = pixels[y * width + x_pair * 2 + 1]

                # 查找最接近的颜色
                c1 = find_closest_color_index(pixel1, PALETTE_6COLOR)
                c2 = find_closest_color_index(pixel2, PALETTE_6COLOR)

                # 压缩到 1 字节：高 4 位 = c1，低 4 位 = c2
                byte_val = ((c1 & 0xF) << 4) | (c2 & 0xF)
                output_data.append(byte_val)

        log_message(f"Converted {os.path.basename(image_path)}: {width}x{height} -> {len(output_data)} bytes")
        return bytes(output_data)

    def send_c_array_data(self, client_socket: socket.socket) -> bool:
        """
        发送当前图片的 C 数组二进制数据

        发送格式: 4字节长度(大端) + 二进制数据

        Args:
            client_socket: 客户端 socket

        Returns:
            True 表示成功
        """
        image_path = self.get_current_image_path()
        if not image_path:
            error_msg = json.dumps({
                "status": "error",
                "message": "No images available"
            }, ensure_ascii=False)
            client_socket.sendall(error_msg.encode('utf-8'))
            return False

        try:
            # 转换为 C 数组二进制数据
            data = self.bmp_to_c_array(image_path)

            # 发送：4字节长度 + 二进制数据
            header = struct.pack('>I', len(data))
            client_socket.sendall(header + data)

            log_message(f"Sent C array data: {os.path.basename(image_path)} ({len(data)} bytes)")
            return True

        except Exception as e:
            log_message(f"Failed to convert/send C array: {e}", "ERROR")
            error_msg = json.dumps({
                "status": "error",
                "message": str(e)
            }, ensure_ascii=False)
            client_socket.sendall(error_msg.encode('utf-8'))
            return False

    def handle_client(self, client_socket: socket.socket, client_addr: tuple) -> None:
        """处理客户端连接"""
        log_message(f"Client connected: {client_addr[0]}:{client_addr[1]}")

        try:
            # 设置超时
            client_socket.settimeout(30.0)

            while True:
                # 接收数据
                try:
                    data = client_socket.recv(BUFFER_SIZE)
                    if not data:
                        log_message(f"Client disconnected: {client_addr[0]}:{client_addr[1]}")
                        break

                    # 解码命令
                    command = data.decode('utf-8').strip()
                    log_message(f"Received command: {command} from {client_addr[0]}:{client_addr[1]}")

                    # 处理命令
                    command_lower = command.lower()

                    # get 命令 - 发送当前图片二进制数据（不推进索引）
                    if command_lower == "get":
                        self.send_image_data(client_socket)
                        continue

                    # get_c 命令 - 发送当前图片的 C 数组二进制数据（不推进索引）
                    if command_lower == "get_c":
                        self.send_c_array_data(client_socket)
                        continue

                    # info 命令 - 获取当前图片信息（不推进索引）
                    if command_lower == "info":
                        image_info = self.get_current_image_info()
                        if image_info:
                            response = json.dumps({
                                "status": "success",
                                "message": "Current image",
                                "data": image_info
                            }, ensure_ascii=False)
                        else:
                            response = json.dumps({
                                "status": "error",
                                "message": f"No images found in {self.image_dir}",
                                "data": {}
                            }, ensure_ascii=False)
                        client_socket.sendall(response.encode('utf-8'))
                        log_message(f"Sent response to {client_addr[0]}:{client_addr[1]}")
                        continue

                    # 其他命令 - 返回 JSON 响应
                    response = self.process_command(command)
                    client_socket.sendall(response.encode('utf-8'))
                    log_message(f"Sent response to {client_addr[0]}:{client_addr[1]}")

                except socket.timeout:
                    log_message(f"Client timeout: {client_addr[0]}:{client_addr[1]}")
                    break

        except Exception as e:
            log_message(f"Error handling client: {e}", "ERROR")

        finally:
            try:
                client_socket.close()
            except Exception:
                pass
            log_message(f"Connection closed: {client_addr[0]}:{client_addr[1]}")

    def process_command(self, command: str) -> str:
        """
        处理接收到的命令

        Args:
            command: 收到的命令字符串

        Returns:
            响应字符串
        """
        command_lower = command.lower()

        # update 命令 - 设置当前图片索引（1-based，循环）
        if command_lower == "update":
            total = len(self.image_list)
            if total == 0:
                return json.dumps({
                    "status": "error",
                    "message": "No images available",
                    "data": {}
                }, ensure_ascii=False)

            # 设置 current_index 为 1-based，第一次调用后 index=1
            if self.current_index <= 0:
                self.current_index = 1
            else:
                self.current_index = self.current_index % total + 1

            return json.dumps({
                "status": "success",
                "message": "Image selected",
                "data": {
                    "current_index": self.current_index,
                    "total": total
                }
            }, ensure_ascii=False)

        # list 命令 - 返回所有图片列表
        if command_lower == "list":
            if self.image_list:
                images = []
                for i, img_path in enumerate(self.image_list):
                    images.append({
                        "index": i + 1,
                        "filename": os.path.basename(img_path),
                        "path": img_path
                    })
                # current_index 已经是 1-based
                display_index = max(1, self.current_index) if self.current_index <= 0 else self.current_index
                return json.dumps({
                    "status": "success",
                    "message": f"Found {len(images)} images",
                    "data": {
                        "total": len(images),
                        "current_index": display_index,
                        "images": images
                    }
                }, ensure_ascii=False)
            else:
                return json.dumps({
                    "status": "error",
                    "message": f"No images found in {self.image_dir}",
                    "data": {}
                }, ensure_ascii=False)

        # status 命令 - 返回设备状态
        if command_lower == "status":
            display_index = max(1, self.current_index) if self.current_index <= 0 else self.current_index
            return json.dumps({
                "status": "success",
                "message": "Device is online",
                "data": {
                    "uptime": "unknown",
                    "memory": "OK",
                    "display": "ready",
                    "image_count": len(self.image_list),
                    "image_dir": self.image_dir,
                    "current_index": display_index
                }
            }, ensure_ascii=False)

        # refresh 命令 - 返回刷新状态
        if command_lower == "refresh":
            return json.dumps({
                "status": "success",
                "message": "Display refresh scheduled",
                "data": {
                    "pending": True,
                    "duration_ms": 500
                }
            }, ensure_ascii=False)

        # reload 命令 - 重新扫描图片目录
        if command_lower == "reload":
            count = self.load_images()
            return json.dumps({
                "status": "success",
                "message": f"Reloaded {count} images",
                "data": {
                    "image_count": count,
                    "image_dir": self.image_dir
                }
            }, ensure_ascii=False)

        # reset 命令 - 重置图片索引
        if command_lower == "reset":
            with self.lock:
                self.current_index = 0
            return json.dumps({
                "status": "success",
                "message": "Image index reset to 0",
                "data": {
                    "current_index": 0
                }
            }, ensure_ascii=False)

        # 默认响应
        return json.dumps({
            "status": "unknown",
            "message": f"Unknown command: {command}",
            "received": command
        }, ensure_ascii=False)

    def start(self) -> bool:
        """
        启动服务器

        Returns:
            True 表示启动成功
        """
        try:
            # 创建 socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # 绑定地址
            self.server_socket.bind((self.host, self.port))

            # 监听
            self.server_socket.listen(5)
            self.running = True

            log_message(f"EPD Socket Server started on {self.host}:{self.port}")
            log_message(f"Image directory: {self.image_dir}")

            # 仅在启用文件监控时启动文件监控线程
            if self.enable_file_monitor:
                self.file_monitor_thread = threading.Thread(target=self.file_monitor_loop)
                self.file_monitor_thread.start()
                log_message("File monitor thread started")
            else:
                # 手动加载一次图片（不使用后台监控）
                self.load_images()
                log_message("File monitoring disabled, images loaded once")

            log_message("Waiting for connections...")

            return True

        except Exception as e:
            log_message(f"Failed to start server: {e}", "ERROR")
            return False

    def run(self) -> None:
        """主服务器循环"""
        if not self.start():
            return

        try:
            while self.running:
                # 接受连接
                try:
                    client_socket, client_addr = self.server_socket.accept()

                    # 创建新线程处理客户端
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_addr),
                        daemon=True
                    )
                    client_thread.start()
                    self.client_threads.append(client_thread)

                except socket.timeout:
                    continue

                except Exception as e:
                    if self.running:
                        log_message(f"Error accepting connection: {e}", "ERROR")

        except KeyboardInterrupt:
            log_message("Received interrupt signal", "WARNING")

        finally:
            self.stop()

    def stop(self) -> None:
        """停止服务器"""
        log_message("Stopping server...")
        self.running = False

        # 关闭服务器 socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass

        # 等待文件监控线程结束（仅在启用文件监控时）
        if self.enable_file_monitor and self.file_monitor_thread and self.file_monitor_thread.is_alive():
            log_message("Waiting for file monitor thread to finish...")
            self.file_monitor_thread.join(timeout=2.0)

        # 等待所有客户端线程结束
        for thread in self.client_threads:
            thread.join(timeout=1.0)

        log_message("Server stopped")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="EPD Socket Server - 电子纸网络测试服务端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
支持的命令:
    update   - 返回下一张图片信息（循环）
    info     - 返回当前图片信息（不推进索引）
    get      - 下载当前图片的二进制数据
    list     - 返回所有图片列表
    status   - 返回设备状态
    refresh  - 返回刷新状态
    reload   - 重新扫描图片目录
    reset    - 重置图片索引到开头

示例:
    python epd_socket_server.py                              # 使用默认配置
    python epd_socket_server.py --image-dir ./dist           # 指定图片目录
    python epd_socket_server.py --host 0.0.0.0 --port 8080   # 自定义地址端口
        """
    )

    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"服务器监听地址 (默认: {DEFAULT_HOST})"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"服务器监听端口 (默认: {DEFAULT_PORT})"
    )

    parser.add_argument(
        "-i", "--image-dir",
        type=str,
        default=DEFAULT_IMAGE_DIR,
        help=f"BMP 图片目录 (默认: {DEFAULT_IMAGE_DIR})"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="启用详细输出"
    )

    args = parser.parse_args()

    if args.verbose:
        log_message(f"Server configuration: {args.host}:{args.port}")
        log_message(f"Image directory: {args.image_dir}")

    # 创建并运行服务器
    server = EPDSocketServer(host=args.host, port=args.port, image_dir=args.image_dir)
    server.run()


if __name__ == "__main__":
    main()
