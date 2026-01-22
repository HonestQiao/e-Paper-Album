#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPD 管理系统 - 统一管理界面

提供统一的入口，启动：
- Web管理界面 (Flask)
- Socket服务器 (TCP)
- 图片管理服务

使用方法:
    python manage.py [选项]

选项:
    --mode MODE         运行模式: web, socket, all (默认: all)
    --web-host HOST     Web服务器地址 (默认: 0.0.0.0)
    --web-port PORT     Web服务器端口 (默认: 5000)
    --socket-host HOST  Socket服务器地址 (默认: 0.0.0.0)
    --socket-port PORT  Socket服务器端口 (默认: 18888)
    --image-dir DIR     图片目录 (默认: ./dist)

示例:
    python manage.py --mode all                          # 启动所有服务
    python manage.py --mode web --web-port 5000         # 仅启动Web服务
    python manage.py --mode socket --socket-port 8080   # 仅启动Socket服务
"""

import os
import sys
import time
import signal
import threading
import argparse

# 导入服务器模块
from web_server import app as web_app, main as web_main
from epd_socket_server import EPDSocketServer


class Manager:
    """管理系统"""

    def __init__(self, web_host, web_port, socket_host, socket_port, image_dir):
        self.web_host = web_host
        self.web_port = web_port
        self.socket_host = socket_host
        self.socket_port = socket_port
        self.image_dir = image_dir
        self.running = False

    def print_banner(self):
        """打印横幅"""
        print("="*70)
        print("  EPD 墨水屏图片管理系统")
        print("  Enhanced Image Management System for E-Paper Display")
        print("="*70)
        print()
        print(f"Web管理界面:  http://{self.web_host}:{self.web_port}")
        print(f"Socket服务器: {self.socket_host}:{self.socket_port}")
        print(f"图片目录:     {self.image_dir}")
        print()
        print("按 Ctrl+C 停止服务")
        print("="*70)
        print()

    def start_web_server(self):
        """启动Web服务器"""
        try:
            os.environ['WEB_HOST'] = self.web_host
            os.environ['WEB_PORT'] = str(self.web_port)
            os.environ['IMAGE_DIR'] = self.image_dir

            # 使用Flask的run方法
            web_app.run(host=self.web_host, port=self.web_port, debug=False, threaded=True)
        except Exception as e:
            print(f"[ERROR] Web服务器启动失败: {e}")

    def start_socket_server(self):
        """启动Socket服务器（在同一进程内，启用文件监控）"""
        try:
            print("[INFO] Socket服务器启动中...")
            # 启用文件监控（在同一进程内运行）
            server = EPDSocketServer(
                host=self.socket_host,
                port=self.socket_port,
                image_dir=self.image_dir,
                enable_file_monitor=True  # 启用文件监控
            )
            print("[INFO] Socket服务器初始化完成，开始运行...")
            # 运行主循环
            server.run()
        except KeyboardInterrupt:
            print("\n[INFO] Socket服务器已停止")
        except Exception as e:
            print(f"[ERROR] Socket服务器异常: {e}")
            import traceback
            traceback.print_exc()

    def start_all(self):
        """启动所有服务"""
        self.print_banner()

        # 启动Web服务器（daemon线程）
        web_thread = threading.Thread(target=self.start_web_server, daemon=True)
        web_thread.start()

        print("[INFO] 正在启动Web服务器...")
        time.sleep(2)

        # 启动Socket服务器（非daemon线程，在同一进程内）
        print("[INFO] 正在启动Socket服务器...")
        socket_thread = threading.Thread(target=self.start_socket_server)
        socket_thread.start()

        print("[INFO] 所有服务已启动！")
        print()

        try:
            # 主线程保持运行
            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n[INFO] 收到停止信号，正在关闭服务...")
            self.stop_all()

    def start_web_only(self):
        """仅启动Web服务器"""
        print("="*70)
        print("  启动模式: Web管理界面")
        print("="*70)
        print()
        print(f"访问地址: http://{self.web_host}:{self.web_port}")
        print()
        print("按 Ctrl+C 停止服务")
        print("="*70)
        print()

        try:
            self.start_web_server()
        except KeyboardInterrupt:
            print("\n[INFO] 服务器已停止")

    def start_socket_only(self):
        """仅启动Socket服务器"""
        print("="*70)
        print("  启动模式: Socket服务器")
        print("="*70)
        print()
        print(f"监听地址: {self.socket_host}:{self.socket_port}")
        print(f"图片目录: {self.image_dir}")
        print()
        print("按 Ctrl+C 停止服务")
        print("="*70)
        print()

        try:
            # 启用文件监控
            server = EPDSocketServer(
                host=self.socket_host,
                port=self.socket_port,
                image_dir=self.image_dir,
                enable_file_monitor=True  # 启用文件监控
            )
            server.start()
        except KeyboardInterrupt:
            print("\n[INFO] 服务器已停止")

    def stop_all(self):
        """停止所有服务"""
        print("[INFO] 正在停止服务...")
        print("[INFO] 所有服务已停止")


def check_dependencies():
    """检查依赖"""
    try:
        import flask
        print(f"[INFO] Flask: {flask.__version__}")
    except ImportError:
        print("[ERROR] Flask 未安装，请运行: pip install flask")
        return False

    try:
        from PIL import Image
        print(f"[INFO] Pillow: 已安装")
    except ImportError:
        print("[ERROR] Pillow 未安装，请运行: pip install Pillow")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(
        description='EPD 墨水屏图片管理系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --mode all
  %(prog)s --mode web --web-port 5000
  %(prog)s --mode socket --socket-port 8080
        """
    )

    parser.add_argument(
        '--mode',
        choices=['web', 'socket', 'all'],
        default='all',
        help='运行模式 (默认: all)'
    )

    parser.add_argument(
        '--web-host',
        default='0.0.0.0',
        help='Web服务器地址 (默认: 0.0.0.0)'
    )

    parser.add_argument(
        '--web-port',
        type=int,
        default=5000,
        help='Web服务器端口 (默认: 5000)'
    )

    parser.add_argument(
        '--socket-host',
        default='0.0.0.0',
        help='Socket服务器地址 (默认: 0.0.0.0)'
    )

    parser.add_argument(
        '--socket-port',
        type=int,
        default=18888,
        help='Socket服务器端口 (默认: 18888)'
    )

    parser.add_argument(
        '--image-dir',
        default='./dist',
        help='图片目录 (默认: ./dist)'
    )

    args = parser.parse_args()

    # 检查依赖
    if not check_dependencies():
        sys.exit(1)

    # 创建目录
    os.makedirs(args.image_dir, exist_ok=True)
    os.makedirs('./uploads', exist_ok=True)

    # 创建管理器
    manager = Manager(
        web_host=args.web_host,
        web_port=args.web_port,
        socket_host=args.socket_host,
        socket_port=args.socket_port,
        image_dir=args.image_dir
    )

    # 启动服务
    if args.mode == 'all':
        manager.start_all()
    elif args.mode == 'web':
        manager.start_web_only()
    elif args.mode == 'socket':
        manager.start_socket_only()


if __name__ == '__main__':
    main()
