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
    --log-file FILE     日志文件路径 (默认: ./server.log)

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
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

# 导入服务器模块
from web_server import app as web_app, main as web_main, set_logging_config
from epd_socket_server import EPDSocketServer, set_logging_config as set_socket_logging_config


class LoggerManager:
    """日志管理器 - 统一配置所有模块的日志"""

    _instance = None
    _logger = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.log_file = None
        self._setup_logger()

    def _setup_logger(self):
        """配置日志"""
        # 获取日志文件路径
        self.log_file = os.environ.get('LOG_FILE', './server.log')

        # 创建日志记录器
        self._logger = logging.getLogger('EPDServer')
        self._logger.setLevel(logging.DEBUG)

        # 避免重复添加处理器
        if self._logger.handlers:
            return

        # 创建格式
        console_formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)-8s] %(message)s',
            datefmt='%H:%M:%S'
        )
        file_formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_formatter)
        self._logger.addHandler(console_handler)

        # 文件处理器（带轮转，10MB）
        try:
            file_handler = RotatingFileHandler(
                self.log_file,
                maxBytes=10*1024*1024,
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(file_formatter)
            self._logger.addHandler(file_handler)
        except Exception as e:
            print(f"[WARNING] Cannot create log file: {e}")

    def get_logger(self):
        """获取日志记录器"""
        return self._logger

    def log(self, message, level='INFO'):
        """统一日志接口"""
        getattr(self._logger, level.lower())(message)

    def info(self, message):
        self.log(message, 'INFO')

    def debug(self, message):
        self.log(message, 'DEBUG')

    def warning(self, message):
        self.log(message, 'WARNING')

    def error(self, message):
        self.log(message, 'ERROR')


def get_logger():
    """获取日志记录器的便捷函数"""
    return LoggerManager().get_logger()


class Manager:
    """管理系统"""

    def __init__(self, web_host, web_port, socket_host, socket_port, image_dir, log_file=None):
        self.web_host = web_host
        self.web_port = web_port
        self.socket_host = socket_host
        self.socket_port = socket_port
        self.image_dir = image_dir
        self.running = False
        self.log_file = log_file

    def print_banner(self):
        """打印横幅"""
        logger = get_logger()
        logger.info("="*70)
        logger.info("  EPD 墨水屏图片管理系统")
        logger.info("  Enhanced Image Management System for E-Paper Display")
        logger.info("="*70)
        logger.info("")
        logger.info(f"Web管理界面:  http://{self.web_host}:{self.web_port}")
        logger.info(f"Socket服务器: {self.socket_host}:{self.socket_port}")
        logger.info(f"图片目录:     {self.image_dir}")
        logger.info(f"日志文件:     {self.log_file}")
        logger.info("")
        logger.info("按 Ctrl+C 停止服务")
        logger.info("="*70)
        logger.info("")

    def start_web_server(self):
        """启动Web服务器"""
        logger = get_logger()
        try:
            os.environ['WEB_HOST'] = self.web_host
            os.environ['WEB_PORT'] = str(self.web_port)
            os.environ['IMAGE_DIR'] = self.image_dir
            os.environ['LOG_FILE'] = self.log_file

            # 设置日志配置
            set_logging_config(self.log_file)

            logger.info(f"[WEB] 启动Web管理服务器...")
            logger.info(f"[WEB] 监听地址: {self.web_host}:{self.web_port}")

            # 使用Flask的run方法
            web_app.run(host=self.web_host, port=self.web_port, debug=False, threaded=True)
        except Exception as e:
            logger.error(f"[WEB] 服务器启动失败: {e}")

    def start_socket_server(self):
        """启动Socket服务器（在同一进程内，启用文件监控）"""
        logger = get_logger()
        try:
            logger.info(f"[SOCKET] 启动Socket服务器...")
            logger.info(f"[SOCKET] 监听地址: {self.socket_host}:{self.socket_port}")
            logger.info(f"[SOCKET] 图片目录: {self.image_dir}")

            # 设置日志配置
            set_socket_logging_config(self.log_file)

            # 启用文件监控（在同一进程内运行）
            server = EPDSocketServer(
                host=self.socket_host,
                port=self.socket_port,
                image_dir=self.image_dir,
                enable_file_monitor=True  # 启用文件监控
            )
            logger.info(f"[SOCKET] Socket服务器初始化完成，开始运行...")
            # 运行主循环
            server.run()
        except KeyboardInterrupt:
            logger.info(f"\n[SOCKET] Socket服务器已停止")
        except Exception as e:
            logger.error(f"[SOCKET] 服务器异常: {e}")
            import traceback
            traceback.print_exc()

    def start_all(self):
        """启动所有服务"""
        logger = get_logger()
        self.print_banner()

        # 启动Web服务器（daemon线程）
        web_thread = threading.Thread(target=self.start_web_server, daemon=True)
        web_thread.start()

        logger.info("[MAIN] 正在启动Web服务器...")
        time.sleep(2)

        # 启动Socket服务器（非daemon线程，在同一进程内）
        logger.info("[MAIN] 正在启动Socket服务器...")
        socket_thread = threading.Thread(target=self.start_socket_server)
        socket_thread.start()

        logger.info("[MAIN] 所有服务已启动！")
        logger.info("[MAIN] 服务状态:")
        logger.info(f"[MAIN]   - Web管理界面: http://{self.web_host}:{self.web_port}")
        logger.info(f"[MAIN]   - Socket服务器: {self.socket_host}:{self.socket_port}")
        logger.info(f"[MAIN]   - 日志文件: {self.log_file}")
        logger.info("")

        try:
            # 主线程保持运行
            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("\n[MAIN] 收到停止信号，正在关闭服务...")
            self.stop_all()

    def start_web_only(self):
        """仅启动Web服务器"""
        logger = get_logger()
        logger.info("="*70)
        logger.info("  启动模式: Web管理界面")
        logger.info("="*70)
        logger.info("")
        logger.info(f"访问地址: http://{self.web_host}:{self.web_port}")
        logger.info(f"日志文件: {self.log_file}")
        logger.info("")
        logger.info("按 Ctrl+C 停止服务")
        logger.info("="*70)
        logger.info("")

        try:
            self.start_web_server()
        except KeyboardInterrupt:
            logger.info("\n[INFO] 服务器已停止")

    def start_socket_only(self):
        """仅启动Socket服务器"""
        logger = get_logger()
        logger.info("="*70)
        logger.info("  启动模式: Socket服务器")
        logger.info("="*70)
        logger.info("")
        logger.info(f"监听地址: {self.socket_host}:{self.socket_port}")
        logger.info(f"图片目录: {self.image_dir}")
        logger.info(f"日志文件: {self.log_file}")
        logger.info("")
        logger.info("按 Ctrl+C 停止服务")
        logger.info("="*70)
        logger.info("")

        try:
            # 设置日志配置
            set_socket_logging_config(self.log_file)

            # 启用文件监控
            server = EPDSocketServer(
                host=self.socket_host,
                port=self.socket_port,
                image_dir=self.image_dir,
                enable_file_monitor=True  # 启用文件监控
            )
            server.start()
        except KeyboardInterrupt:
            logger.info("\n[INFO] 服务器已停止")

    def stop_all(self):
        """停止所有服务"""
        logger = get_logger()
        logger.info("[MAIN] 正在停止服务...")
        logger.info("[MAIN] 所有服务已停止")


def check_dependencies():
    """检查依赖"""
    logger = get_logger()
    try:
        import flask
        logger.info(f"[DEPENDENCY] Flask: {flask.__version__}")
    except ImportError:
        logger.error("[DEPENDENCY] Flask 未安装，请运行: pip install flask")
        return False

    try:
        from PIL import Image
        logger.info(f"[DEPENDENCY] Pillow: 已安装")
    except ImportError:
        logger.error("[DEPENDENCY] Pillow 未安装，请运行: pip install Pillow")
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

    parser.add_argument(
        '--log-file',
        default='./server.log',
        help='日志文件路径 (默认: ./server.log)'
    )

    args = parser.parse_args()

    # 初始化日志
    logger = get_logger()

    # 检查依赖
    if not check_dependencies():
        sys.exit(1)

    # 创建目录
    os.makedirs(args.image_dir, exist_ok=True)
    os.makedirs('./uploads', exist_ok=True)

    logger.info(f"[MAIN] 启动 EPD 图片管理系统")
    logger.info(f"[MAIN] 日志文件: {args.log_file}")

    # 创建管理器
    manager = Manager(
        web_host=args.web_host,
        web_port=args.web_port,
        socket_host=args.socket_host,
        socket_port=args.socket_port,
        image_dir=args.image_dir,
        log_file=args.log_file
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
