#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPD Web管理界面 - 电子纸图片管理服务器

提供Web界面用于：
- 图片预览
- 图片上传
- 自动转换为BMP
- 管理Socket服务器

功能:
- Flask Web界面
- 图片上传和预览
- 自动格式转换
- 文件监控
- Socket服务器集成

使用方法:
    python web_server.py [--host HOST] [--port PORT]

示例:
    python web_server.py                          # 使用默认配置
    python web_server.py --host 0.0.0.0 --port 5000
"""

import os
import sys
import json
import argparse
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, send_from_directory
from PIL import Image

# 配置
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000
UPLOAD_FOLDER = './uploads'
DIST_FOLDER = './dist/data'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# 动态目录设置
_IMAGE_DIR = DIST_FOLDER  # 内部变量，main()中设置

def get_image_dir():
    """获取图片目录（优先从环境变量读取）"""
    return os.environ.get('IMAGE_DIR', _IMAGE_DIR)

def set_image_dir(directory):
    """设置图片目录"""
    global _IMAGE_DIR
    _IMAGE_DIR = directory
    os.makedirs(_IMAGE_DIR, exist_ok=True)

# 确保基本目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DIST_FOLDER, exist_ok=True)

# 全局进度跟踪字典
# 格式: {filename: {'status': 'converting'|'completed'|'error', 'progress': 0-100, 'message': ''}}
conversion_progress = {}

def update_progress(filename, progress, message='', status='converting'):
    """更新转换进度"""
    global conversion_progress
    conversion_progress[filename] = {
        'progress': progress,
        'message': message,
        'status': status
    }

def get_progress(filename):
    """获取转换进度"""
    return conversion_progress.get(filename, {'progress': 0, 'message': '', 'status': 'unknown'})


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def log_message(message):
    """打印日志消息"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [WEB] {message}")


def prepare_image(input_path, output_path, rotation=0, target_width=400, target_height=600):
    """
    图片预处理：完全参考prepare_image.py的逻辑
    将任意尺寸图片转换为400x600规格的JPG图片

    Args:
        input_path: 输入图片路径
        output_path: 输出图片路径
        rotation: 旋转角度（0/90/180/270），默认0
        target_width: 目标宽度，默认400
        target_height: 目标高度，默认600

    Returns:
        tuple: (output_path, original_size, final_size)
    """
    log_message(f"开始预处理: {os.path.basename(input_path)}")

    # 打开图片
    with Image.open(input_path) as image:
        original_width, original_height = image.size
        log_message(f"原始尺寸: {original_width}x{original_height}")

        # 应用旋转
        if rotation != 0:
            log_message(f"按指定角度旋转: {rotation}度")
            # expand=True确保旋转后完整显示图片
            image = image.rotate(-rotation, expand=True)  # 负号表示顺时针旋转
            rotated_width, rotated_height = image.size
            log_message(f"旋转后尺寸: {rotated_width}x{rotated_height}")

        # 计算缩放比例（保持宽高比）
        current_width, current_height = image.size
        scale = min(target_width / current_width, target_height / current_height)

        # 计算缩放后的尺寸
        new_width = int(current_width * scale)
        new_height = int(current_height * scale)

        log_message(f"缩放比例: {scale:.3f}")
        log_message(f"缩放后尺寸: {new_width}x{new_height}")

        # 等比缩放
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        log_message(f"等比缩放完成")

        # 如果缩放后尺寸小于目标尺寸，需要填充
        if new_width < target_width or new_height < target_height:
            log_message(f"检测到缩放后尺寸小于目标，创建画布填充")
            # 创建目标尺寸画布
            canvas = Image.new('RGB', (target_width, target_height), color='white')

            # 计算居中位置
            paste_x = (target_width - new_width) // 2
            paste_y = (target_height - new_height) // 2

            log_message(f"居中粘贴到画布: 偏移({paste_x}, {paste_y})")

            # 粘贴图片到画布中心
            canvas.paste(image, (paste_x, paste_y))
            image = canvas

            final_width, final_height = target_width, target_height
        else:
            final_width, final_height = new_width, new_height

        # 转换为RGB模式（确保是JPG兼容格式）
        if image.mode != 'RGB':
            log_message(f"转换图片模式: {image.mode} -> RGB")
            image = image.convert('RGB')

        # 保存图片
        image.save(output_path, format='JPEG', quality=95)
        log_message(f"保存图片到: {output_path}")

        log_message(f"预处理完成! 最终尺寸: {final_width}x{final_height}")

        return output_path, (original_width, original_height), (final_width, final_height)


def init_6color_palette():
    """初始化6色调色板（同6-color.act）"""
    core_colors = [
        0, 0, 0,           # 索引0：黑色
        255, 255, 255,     # 索引1：白色
        255, 255, 0,       # 索引2：黄色
        255, 0, 0,         # 索引3：红色
        0, 0, 255,         # 索引4：蓝色
        0, 255, 0          # 索引5：绿色
    ]
    palette = core_colors + [0] * (768 - len(core_colors))
    return palette


def floyd_steinberg_dithering(img_rgb, palette, dither_step=1,
                              r_weight=0.35, g_weight=0.45, b_weight=0.2):
    """
    Floyd-Steinberg仿色算法
    """
    import numpy as np

    dither_step = max(1, min(10, dither_step))
    palette_np = np.array(palette).reshape(-1, 3)[:6]
    img_array = np.array(img_rgb, dtype=np.float32)
    height, width = img_array.shape[:2]

    # 归一化权重
    total_weight = r_weight + g_weight + b_weight
    weights = np.array([r_weight, g_weight, b_weight]) / total_weight

    for y in range(0, height, dither_step):
        for x in range(0, width, dither_step):
            old_pixel = img_array[y, x].copy()

            # 加权颜色距离计算
            weighted_diff = (palette_np - old_pixel) * weights
            distances = np.sqrt(np.sum(weighted_diff **2, axis=1))
            closest_idx = np.argmin(distances)
            new_pixel = palette_np[closest_idx]

            # 按步长填充像素
            for dy in range(dither_step):
                for dx in range(dither_step):
                    ny = y + dy
                    nx = x + dx
                    if ny < height and nx < width:
                        img_array[ny, nx] = new_pixel

            # 误差扩散
            brightness = np.dot(old_pixel, [0.299, 0.587, 0.114]) / 255.0
            if brightness < 0.95:
                error = old_pixel - new_pixel
                if x + dither_step < width:
                    img_array[y, x+dither_step] += error * 7/16
                if y + dither_step < height and x - dither_step >= 0:
                    img_array[y+dither_step, x-dither_step] += error * 3/16
                if y + dither_step < height:
                    img_array[y+dither_step, x] += error * 5/16
                if y + dither_step < height and x + dither_step < width:
                    img_array[y+dither_step, x+dither_step] += error * 1/16

    # 转换为RGB图片并量化
    img_dithered = Image.fromarray(np.clip(img_array, 0, 255).astype(np.uint8), mode="RGB")
    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(palette)
    img_indexed = img_dithered.quantize(palette=palette_img)

    return img_indexed


def convert_to_6color_gif(input_path, output_path, dither_step=1,
                          r_weight=0.35, g_weight=0.45, b_weight=0.2):
    """
    转换为6色GIF（使用与full_convert.py相同的逻辑）
    """
    import numpy as np

    # 加载图片
    with Image.open(input_path) as img:
        img_rgb = img.convert("RGB")

    # 初始化调色板
    palette = init_6color_palette()

    # 仿色处理
    img_dithered = floyd_steinberg_dithering(img_rgb, palette, dither_step, r_weight, g_weight, b_weight)

    # 保存GIF
    img_dithered.save(
        output_path,
        format="GIF",
        optimize=False,
        loop=0,
        disposal=0
    )

    return True


def gif_to_bmp(gif_path, bmp_path):
    """
    将6色GIF转换为BMP（使用与full_convert.py相同的逻辑）
    """
    with Image.open(gif_path) as img:
        img.seek(0)
        gif_rgb = img.convert("RGB")
        gif_rgb.save(bmp_path, format="BMP")

    return True


def convert_to_bmp(input_path, output_path, size=(400, 600), progress_callback=None):
    """
    将图片转换为BMP格式（跳过预处理步骤，因为uploads中的文件已经是400x600）

    Args:
        input_path: 输入文件路径（已经是400x600的JPEG）
        output_path: 输出文件路径
        size: 目标尺寸
        progress_callback: 进度回调函数，接收(progress, message)参数

    Returns:
        True表示成功
    """
    filename = os.path.basename(input_path)
    temp_dir = os.path.dirname(output_path) if os.path.dirname(output_path) else '.'

    try:
        # 步骤1: 加载图片 (20%)
        if progress_callback:
            progress_callback(10, "正在加载图片...")
        log_message(f"开始转换: {filename}")

        # 创建临时目录
        os.makedirs(temp_dir, exist_ok=True)
        base_name = os.path.splitext(filename)[0]

        # 跳过预处理步骤，因为文件已经是400x600
        log_message(f"文件已经是400x600，直接转换: {filename}")

        # 步骤2: 转换为6色GIF (80%)
        if progress_callback:
            progress_callback(20, "正在转换为6色GIF...")

        temp_gif = os.path.join(temp_dir, f"temp_{base_name}.gif")
        # input_path已经是400x600的JPEG，直接传递给convert_to_6color_gif
        convert_to_6color_gif(input_path, temp_gif, dither_step=1,
                             r_weight=0.35, g_weight=0.45, b_weight=0.2)

        if progress_callback:
            progress_callback(80, "6色GIF转换完成")

        # 步骤3: 转换为BMP (100%)
        if progress_callback:
            progress_callback(90, "正在生成BMP文件...")

        gif_to_bmp(temp_gif, output_path)

        # 清理临时文件
        try:
            os.remove(temp_gif)
        except:
            pass

        # 完成 (100%)
        if progress_callback:
            progress_callback(100, "转换完成!")

        log_message(f"转换成功: {filename} -> {os.path.basename(output_path)}")
        return True

    except Exception as e:
        error_msg = f"转换失败: {str(e)}"
        log_message(f"{filename} - {error_msg}")
        if progress_callback:
            progress_callback(0, f"错误: {str(e)}", status='error')
        return False


def get_images_info():
    """获取图片列表信息"""
    image_dir = get_image_dir()
    images = []
    if not os.path.isdir(image_dir):
        return images

    for filename in os.listdir(image_dir):
        if filename.lower().endswith('.bmp'):
            filepath = os.path.join(image_dir, filename)
            stat = os.stat(filepath)
            images.append({
                'name': filename,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            })

    # 按文件名排序
    images.sort(key=lambda x: x['name'])
    return images


def get_upload_files():
    """获取需要转换的文件列表
    只返回uploads中存在但dist/data中没有对应bmp文件的图片"""
    files = []
    if not os.path.isdir(UPLOAD_FOLDER):
        return files

    # 获取dist目录中的所有bmp文件（用于检查）
    dist_bmp_files = set()
    dist_dir = get_image_dir()
    if os.path.isdir(dist_dir):
        for filename in os.listdir(dist_dir):
            if filename.lower().endswith('.bmp'):
                # 提取不含扩展名的文件名
                name_only = os.path.splitext(filename)[0]
                dist_bmp_files.add(name_only)

    # 遍历uploads目录中的文件
    for filename in os.listdir(UPLOAD_FOLDER):
        if allowed_file(filename):
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.isfile(filepath):
                # 提取文件名（不含扩展名）
                name_only = os.path.splitext(filename)[0]

                # 只返回没有对应bmp文件的图片
                if name_only not in dist_bmp_files:
                    stat = os.stat(filepath)
                    files.append({
                        'name': filename,
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })

    # 按修改时间排序
    files.sort(key=lambda x: x['modified'], reverse=True)
    return files


def get_all_upload_files():
    """获取uploads目录中的所有文件（用于原始图片预览）"""
    files = []
    if not os.path.isdir(UPLOAD_FOLDER):
        return files

    # 获取uploads目录中的所有文件
    for filename in os.listdir(UPLOAD_FOLDER):
        if allowed_file(filename):
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.isfile(filepath):
                stat = os.stat(filepath)
                files.append({
                    'name': filename,
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })

    # 按修改时间排序
    files.sort(key=lambda x: x['modified'], reverse=True)
    return files


@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')


@app.route('/api/images')
def api_images():
    """获取图片列表API"""
    return jsonify(get_images_info())


@app.route('/api/uploads')
def api_uploads():
    """获取上传文件列表API"""
    return jsonify(get_upload_files())


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """上传文件API - 上传后立即处理为400x600"""
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400

    if file and allowed_file(file.filename):
        # 使用原始文件名，但确保只保留安全字符（允许中文和特殊字符）
        filename = file.filename
        # 临时保存原始文件
        temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{filename}")
        file.save(temp_filepath)

        log_message(f"上传文件: {filename}")

        try:
            # 上传后立即处理为400x600大小
            processed_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            log_message(f"开始预处理: {filename}")
            prepare_image(temp_filepath, processed_filepath, target_width=400, target_height=600)
            log_message(f"预处理完成: {filename}")

            # 删除临时原始文件
            os.remove(temp_filepath)

            return jsonify({
                'success': True,
                'message': f'上传成功: {filename} (已自动处理为400x600，请转换为BMP)',
                'filename': filename
            })
        except Exception as e:
            log_message(f"预处理失败 {filename}: {str(e)}")
            # 即使预处理失败，也保留原始文件
            try:
                os.remove(temp_filepath)
            except:
                pass
            return jsonify({
                'success': True,
                'message': f'上传成功: {filename} (预处理失败，请手动转换为BMP)',
                'filename': filename
            })

    return jsonify({'error': '不支持的文件格式'}), 400


@app.route('/api/convert', methods=['POST'])
def api_convert():
    """手动转换API（支持进度追踪）"""
    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({'error': '缺少文件名'}), 400

    filename = data['filename']
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    if not os.path.exists(filepath):
        return jsonify({'error': '文件不存在'}), 404

    name_only = os.path.splitext(filename)[0]
    bmp_filename = f"{name_only}.bmp"
    bmp_path = os.path.join(get_image_dir(), bmp_filename)

    # 初始化进度
    update_progress(filename, 0, "准备转换...", 'converting')

    # 定义进度回调函数
    def progress_callback(progress, message, status='converting'):
        update_progress(filename, progress, message, status)

    # 执行转换（同步执行，但有进度追踪）
    # 注意：这里使用同步转换，实际项目中可以考虑使用异步
    result = convert_to_bmp(filepath, bmp_path, progress_callback=progress_callback)

    if result:
        update_progress(filename, 100, "转换完成!", 'completed')
        log_message(f"转换成功: {filename} -> {bmp_filename} (原始文件保留在uploads目录)")

        return jsonify({
            'success': True,
            'message': f'转换成功: {bmp_filename} (原始文件保留在uploads目录)'
        })
    else:
        update_progress(filename, 0, "转换失败", 'error')
        return jsonify({'error': '转换失败'}), 500


@app.route('/api/progress/<filename>', methods=['GET'])
def api_get_progress(filename):
    """查询转换进度API"""
    progress = get_progress(filename)
    return jsonify(progress)


@app.route('/api/delete', methods=['POST'])
def api_delete():
    """删除文件API（只删除原始图片，保留BMP文件）"""
    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({'error': '缺少文件名'}), 400

    filename = data['filename']

    # 删除上传文件
    upload_path = os.path.join(UPLOAD_FOLDER, filename)
    upload_deleted = False
    if os.path.exists(upload_path):
        os.remove(upload_path)
        upload_deleted = True

    # 注意：不再自动删除BMP文件，保留BMP文件独立存在

    if upload_deleted:
        log_message(f"删除文件: {filename}")
        return jsonify({
            'success': True,
            'message': f'删除成功',
            'upload_deleted': upload_deleted
        })
    else:
        return jsonify({'error': '文件不存在'}), 404


@app.route('/api/refresh')
def api_refresh():
    """刷新图片列表API"""
    return jsonify({
        'success': True,
        'images': get_images_info(),
        'uploads': get_upload_files()
    })


@app.route('/api/all-uploads')
def api_all_uploads():
    """获取uploads目录中的所有文件API（用于原始图片预览）"""
    return jsonify(get_all_upload_files())


@app.route('/api/delete-bmp', methods=['POST'])
def api_delete_bmp():
    """删除BMP图片API"""
    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({'error': '缺少文件名'}), 400

    filename = data['filename']
    filepath = os.path.join(get_image_dir(), filename)

    if not os.path.exists(filepath):
        return jsonify({'error': '文件不存在'}), 404

    try:
        os.remove(filepath)
        log_message(f"删除BMP文件: {filename}")
        return jsonify({
            'success': True,
            'message': f'删除成功: {filename}'
        })
    except Exception as e:
        log_message(f"删除BMP文件失败: {filename} - {e}")
        return jsonify({'error': f'删除失败: {str(e)}'}), 500


@app.route('/api/batch_convert', methods=['POST'])
def api_batch_convert():
    """批量转换API"""
    data = request.get_json()
    if not data or 'filenames' not in data:
        return jsonify({'error': '缺少文件名列表'}), 400

    filenames = data['filenames']
    if not isinstance(filenames, list) or len(filenames) == 0:
        return jsonify({'error': '文件名列表无效'}), 400

    success_count = 0
    failed_count = 0
    failed_files = []

    for filename in filenames:
        try:
            filepath = os.path.join(UPLOAD_FOLDER, filename)

            if not os.path.exists(filepath):
                failed_count += 1
                failed_files.append({'filename': filename, 'error': '文件不存在'})
                continue

            name_only = os.path.splitext(filename)[0]
            bmp_filename = f"{name_only}.bmp"
            bmp_path = os.path.join(get_image_dir(), bmp_filename)

            if convert_to_bmp(filepath, bmp_path):
                log_message(f"批量转换成功: {filename} -> {bmp_filename} (原始文件保留在uploads目录)")
                success_count += 1
            else:
                failed_count += 1
                failed_files.append({'filename': filename, 'error': '转换失败'})
        except Exception as e:
            failed_count += 1
            failed_files.append({'filename': filename, 'error': str(e)})

    return jsonify({
        'success': True,
        'total': len(filenames),
        'success_count': success_count,
        'failed_count': failed_count,
        'failed_files': failed_files,
        'message': f'批量转换完成: 成功 {success_count} 个，失败 {failed_count} 个'
    })


@app.route('/api/batch_delete', methods=['POST'])
def api_batch_delete():
    """批量删除API"""
    data = request.get_json()
    if not data or 'filenames' not in data:
        return jsonify({'error': '缺少文件名列表'}), 400

    filenames = data['filenames']
    if not isinstance(filenames, list) or len(filenames) == 0:
        return jsonify({'error': '文件名列表无效'}), 400

    success_count = 0
    failed_count = 0
    failed_files = []

    for filename in filenames:
        try:
            filepath = os.path.join(UPLOAD_FOLDER, filename)

            if not os.path.exists(filepath):
                failed_count += 1
                failed_files.append({'filename': filename, 'error': '文件不存在'})
                continue

            os.remove(filepath)
            success_count += 1
            log_message(f"删除文件: {filename}")

        except Exception as e:
            failed_count += 1
            failed_files.append({'filename': filename, 'error': str(e)})

    return jsonify({
        'success': True,
        'total': len(filenames),
        'success_count': success_count,
        'failed_count': failed_count,
        'failed_files': failed_files,
        'message': f'批量删除完成: 成功 {success_count} 个，失败 {failed_count} 个'
    })


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """提供上传文件的访问"""
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/images/<filename>')
def image_file(filename):
    """提供图片文件的访问"""
    return send_from_directory(get_image_dir(), filename)


def main():
    parser = argparse.ArgumentParser(description='EPD Web管理服务器')
    parser.add_argument('--host', default=DEFAULT_HOST, help='监听地址')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help='监听端口')
    parser.add_argument('--image-dir', default=os.environ.get('IMAGE_DIR', DIST_FOLDER), help='图片目录')
    args = parser.parse_args()

    # 优先使用环境变量中的设置
    image_dir = os.environ.get('IMAGE_DIR', args.image_dir)

    # 设置图片目录
    set_image_dir(image_dir)

    log_message(f"启动Web管理服务器")
    log_message(f"监听地址: {args.host}:{args.port}")
    log_message(f"上传目录: {UPLOAD_FOLDER}")
    log_message(f"输出目录: {get_image_dir()}")
    log_message(f"访问地址: http://{args.host}:{args.port}")

    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == '__main__':
    main()
