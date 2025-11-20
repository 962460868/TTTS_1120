import gradio as gr
import requests
import time
from datetime import datetime, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import random
import logging
from PIL import Image
import io
import base64
import uuid
import sqlite3
import os
import json
import shutil
import gc  # 垃圾回收，用于及时释放内存
import queue  # 使用线程安全的队列替代list

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- API配置 ---
# 去水印
WATERMARK_API_KEY = "9394a5c6d9454cd2b31e24661dd11c3d"
WATERMARK_WEBAPP_ID = "1986469254155403266"
WATERMARK_NODE_INFO = [
    {"nodeId": "191", "fieldName": "image", "fieldValue": "placeholder.jpg", "description": "image"}
]

# 溶图打光
LIGHTING_API_KEY = "9394a5c6d9454cd2b31e24661dd11c3d"
LIGHTING_WEBAPP_ID = "1985718229576425473"
LIGHTING_NODE_INFO = [
    {"nodeId": "437", "fieldName": "image", "fieldValue": "placeholder.png", "description": "image"}
]

# 姿态迁移
POSE_API_KEY = "9394a5c6d9454cd2b31e24661dd11c3d"
POSE_WEBAPP_ID = "1975745173911154689"
POSE_NODE_INFO = [
    {"nodeId": "245", "fieldName": "image", "fieldValue": "placeholder.png", "description": "角色图片"},
    {"nodeId": "244", "fieldName": "image", "fieldValue": "placeholder.png", "description": "姿势参考图"}
]

# 姿态迁移 - 新版API（队列处理专用）
POSE_WEBAPP_ID_NEW = "1990654378698838018"
POSE_NODE_INFO_NEW = [
    {"nodeId": "6", "fieldName": "image", "fieldValue": "placeholder.jpg", "description": "角色图"},
    {"nodeId": "73", "fieldName": "image", "fieldValue": "placeholder.jpg", "description": "姿态图"},
    {"nodeId": "140", "fieldName": "value", "fieldValue": "15", "description": "强度值"}
]

# 视频修复
VIDEO_RESTORE_API_KEY = "c95f4c4d2703479abfbc55eefeb9bb71"
VIDEO_RESTORE_WEBAPP_ID = "1980134984679854082"
VIDEO_RESTORE_NODE_INFO = [
    {"nodeId": "36", "fieldName": "video", "fieldValue": "placeholder.mp4", "description": "video"}
]

# 图像优化 WAN 2.2 (新版API，支持正反提示词)
ENHANCE_API_KEY = "9394a5c6d9454cd2b31e24661dd11c3d"
ENHANCE_WEBAPP_ID_V2_2 = "1986501194824773634"
ENHANCE_NODE_INFO_V2_2 = [
    {"nodeId": "14", "fieldName": "image", "fieldValue": "placeholder.jpg", "description": "image"}
]

# 图像优化 WAN 2.2 - 写实专用API
ENHANCE_WEBAPP_ID_V2_2_REALISTIC = "1990350315130114050"
ENHANCE_NODE_INFO_V2_2_REALISTIC = [
    {"nodeId": "14", "fieldName": "image", "fieldValue": "placeholder.jpg", "description": "image"},
    {"nodeId": "69", "fieldName": "text", "fieldValue": "", "description": "text"},
    {"nodeId": "21", "fieldName": "text", "fieldValue": "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走", "description": "text"}
]

# 图像优化 WAN 2.2 - 3D卡通专用API
ENHANCE_WEBAPP_ID_V2_2_3D = "1990258505405919234"
ENHANCE_NODE_INFO_V2_2_3D = [
    {"nodeId": "38", "fieldName": "image", "fieldValue": "placeholder.jpg", "description": "image"},
    {"nodeId": "60", "fieldName": "text", "fieldValue": "8k, high quality, high detail", "description": "text"},
    {"nodeId": "4", "fieldName": "text", "fieldValue": "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走", "description": "text"}
]

# 图像优化 WAN 2.1
ENHANCE_WEBAPP_ID_V2_1 = "1947599512657453057"
ENHANCE_NODE_INFO_V2_1 = [
    {"nodeId": "38", "fieldName": "image", "fieldValue": "placeholder.png", "description": "图片输入"}
]

# 系统配置
MAX_RETRIES = 3
POLL_INTERVAL = 10  # 增加到10秒，减少API轮询频率和CPU占用
MAX_POLL_COUNT = 240
UPLOAD_TIMEOUT = 120
RUN_TASK_TIMEOUT = 60
STATUS_CHECK_TIMEOUT = 25
OUTPUT_FETCH_TIMEOUT = 90
IMAGE_DOWNLOAD_TIMEOUT = 120

# 性能优化配置（50并发，优化资源管理）
MAX_CONCURRENT_TASKS = 50  # 保持50并发不变
UI_REFRESH_INTERVAL = 2.0  # UI刷新间隔从0.5秒增加到2秒，减少CPU占用
BACKGROUND_THREAD_LOCK = threading.Lock()  # 防止无限后台线程创建
BACKGROUND_THREAD_ACTIVE = False  # 后台线程运行标志

# 素材存储配置
MATERIALS_BASE_DIR = "/home/user/TEST1/outputs"
MATERIALS_DB_PATH = os.path.join(MATERIALS_BASE_DIR, "materials.db")
RETENTION_DAYS = 14  # 素材保留天数

# 错误关键词
CONCURRENT_LIMIT_ERRORS = [
    "concurrent limit", "too many requests", "rate limit",
    "队列已满", "并发限制", "服务忙碌", "CONCURRENT_LIMIT_EXCEEDED", "TOO_MANY_REQUESTS"
]

TIMEOUT_ERRORS = [
    "read timed out", "connection timeout", "timeout", "timed out"
]

# --- 辅助函数 ---
def image_to_base64(image):
    """将 PIL Image 转换为 base64 字符串"""
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"

def create_comparison_html(original_image, enhanced_image):
    """创建图像对比滑块的 HTML - 纯 JavaScript 实现，无需外部库"""
    original_b64 = image_to_base64(original_image)
    enhanced_b64 = image_to_base64(enhanced_image)

    # 生成唯一 ID 避免多个实例冲突
    unique_id = f"comp_{int(time.time() * 1000)}"

    html = f"""
    <div class="comparison-wrapper-{unique_id}" style="width: 100%; max-width: 1000px; margin: 20px auto; padding: 20px; background: #f8f9fa; border-radius: 12px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);">
        <div class="comparison-container-{unique_id}" style="position: relative; width: 100%; overflow: hidden; border-radius: 8px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15); user-select: none;">
            <!-- 优化后的图片（底层，完整显示）-->
            <img src="{enhanced_b64}" alt="优化后" style="display: block; width: 100%; height: auto; border-radius: 8px;">

            <!-- 原图（顶层，通过 clip-path 控制显示区域）-->
            <div class="original-overlay-{unique_id}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; overflow: hidden; clip-path: inset(0 100% 0 0);">
                <img src="{original_b64}" alt="原图" style="display: block; width: 100%; height: auto; border-radius: 8px;">
            </div>

            <!-- 分割线和滑块 -->
            <div class="slider-line-{unique_id}" style="position: absolute; top: 0; left: 0%; width: 3px; height: 100%; background: white; box-shadow: 0 0 10px rgba(0,0,0,0.5); cursor: ew-resize; z-index: 10;">
                <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 40px; height: 40px; background: white; border-radius: 50%; box-shadow: 0 2px 8px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center;">
                    <div style="width: 0; height: 0; border-top: 8px solid transparent; border-bottom: 8px solid transparent; border-right: 8px solid #666; margin-right: 2px;"></div>
                    <div style="width: 0; height: 0; border-top: 8px solid transparent; border-bottom: 8px solid transparent; border-left: 8px solid #666; margin-left: 2px;"></div>
                </div>
            </div>

            <!-- 标签 -->
            <div style="position: absolute; top: 20px; left: 20px; padding: 10px 20px; background: rgba(0, 0, 0, 0.75); color: white; border-radius: 6px; font-size: 15px; font-weight: 600; z-index: 5; backdrop-filter: blur(4px);">
                📷 原图
            </div>
            <div style="position: absolute; top: 20px; right: 20px; padding: 10px 20px; background: rgba(0, 0, 0, 0.75); color: white; border-radius: 6px; font-size: 15px; font-weight: 600; z-index: 5; backdrop-filter: blur(4px);">
                ✨ 优化后
            </div>
        </div>

        <!-- 提示信息 -->
        <div style="text-align: center; margin-top: 20px; padding: 15px; background: white; border-radius: 8px; color: #495057; font-size: 14px; line-height: 1.6; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);">
            <div style="margin-bottom: 10px;">
                💡 <strong style="color: #0066cc;">使用说明</strong>：拖动中间的滑块可以对比原图和优化后的效果
            </div>
            <div>
                ⬅️ <strong style="color: #0066cc;">向左滑动</strong>：查看原图 |
                ➡️ <strong style="color: #0066cc;">向右滑动</strong>：查看优化后 |
                默认显示优化后的效果
            </div>
            <div style="margin-top: 15px;">
                <a href="{enhanced_b64}" download="optimized_image.png" style="display: inline-block; padding: 10px 24px; background: #0066cc; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; transition: all 0.3s;">
                    📥 下载优化后的图片
                </a>
            </div>
        </div>
    </div>

    <script>
    (function() {{
        const container = document.querySelector('.comparison-container-{unique_id}');
        const overlay = document.querySelector('.original-overlay-{unique_id}');
        const sliderLine = document.querySelector('.slider-line-{unique_id}');

        if (!container || !overlay || !sliderLine) return;

        let isDragging = false;

        // 初始化位置（默认显示优化后，即原图被完全裁剪）
        function setPosition(percentage) {{
            percentage = Math.max(0, Math.min(100, percentage));
            const clipPercentage = 100 - percentage;
            overlay.style.clipPath = `inset(0 ${{clipPercentage}}% 0 0)`;
            sliderLine.style.left = percentage + '%';
        }}

        // 设置初始位置为 0%（完全显示优化后的图）
        setPosition(0);

        function handleMove(e) {{
            if (!isDragging && e.type !== 'click') return;

            const rect = container.getBoundingClientRect();
            let x;

            if (e.type.includes('touch')) {{
                x = e.touches[0].clientX;
            }} else {{
                x = e.clientX;
            }}

            const percentage = ((x - rect.left) / rect.width) * 100;
            setPosition(percentage);
        }}

        // 鼠标事件
        sliderLine.addEventListener('mousedown', (e) => {{
            isDragging = true;
            e.preventDefault();
        }});

        document.addEventListener('mousemove', handleMove);

        document.addEventListener('mouseup', () => {{
            isDragging = false;
        }});

        // 触摸事件（移动端支持）
        sliderLine.addEventListener('touchstart', (e) => {{
            isDragging = true;
            e.preventDefault();
        }});

        document.addEventListener('touchmove', handleMove);

        document.addEventListener('touchend', () => {{
            isDragging = false;
        }});

        // 点击容器直接跳转
        container.addEventListener('click', handleMove);

        // 键盘支持
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'ArrowLeft') {{
                const currentLeft = parseFloat(sliderLine.style.left) || 0;
                setPosition(currentLeft - 5);
            }} else if (e.key === 'ArrowRight') {{
                const currentLeft = parseFloat(sliderLine.style.left) || 0;
                setPosition(currentLeft + 5);
            }}
        }});
    }})();
    </script>
    """

    return html

# --- 核心API函数 ---
def is_concurrent_limit_error(error_msg):
    error_lower = error_msg.lower()
    return any(keyword in error_lower for keyword in CONCURRENT_LIMIT_ERRORS)

def is_timeout_error(error_msg):
    error_lower = error_msg.lower()
    return any(keyword in error_lower for keyword in TIMEOUT_ERRORS)

def upload_file_with_retry(file_data, file_name, api_key, max_retries=3):
    for attempt in range(max_retries):
        try:
            url = 'https://www.runninghub.cn/task/openapi/upload'
            files = {'file': (file_name, file_data)}
            data = {'apiKey': api_key, 'fileType': 'image'}

            response = requests.post(url, files=files, data=data, timeout=UPLOAD_TIMEOUT)
            response.raise_for_status()

            result = response.json()
            if result.get("code") == 0:
                return result['data']['fileName']
            else:
                raise Exception(f"上传失败: {result.get('msg', '未知错误')}")

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
                continue
            else:
                raise Exception(f"上传超时，已重试{max_retries}次")
        except Exception as e:
            if attempt < max_retries - 1 and is_timeout_error(str(e)):
                time.sleep((attempt + 1) * 2)
                continue
            else:
                raise

def run_task_with_retry(api_key, webapp_id, node_info_list, max_retries=3, instance_type=None):
    for attempt in range(max_retries):
        try:
            url = 'https://www.runninghub.cn/task/openapi/ai-app/run'
            headers = {'Host': 'www.runninghub.cn', 'Content-Type': 'application/json'}
            payload = {
                "apiKey": api_key,
                "webappId": webapp_id,
                "nodeInfoList": node_info_list
            }

            if instance_type:
                payload["instanceType"] = instance_type

            response = requests.post(url, headers=headers, json=payload, timeout=RUN_TASK_TIMEOUT)
            response.raise_for_status()

            result = response.json()
            if result.get("code") != 0:
                raise Exception(f"任务发起失败: {result.get('msg', '未知错误')}")
            return result['data']['taskId']

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 3)
                continue
            else:
                raise Exception(f"启动任务超时，已重试{max_retries}次")
        except Exception as e:
            if attempt < max_retries - 1 and is_timeout_error(str(e)):
                time.sleep((attempt + 1) * 3)
                continue
            else:
                raise

def get_task_status(api_key, task_id):
    try:
        url = 'https://www.runninghub.cn/task/openapi/status'
        response = requests.post(url, json={'apiKey': api_key, 'taskId': task_id}, timeout=STATUS_CHECK_TIMEOUT)
        response.raise_for_status()
        return response.json().get('data')
    except requests.exceptions.Timeout:
        return "CHECKING"
    except:
        return "UNKNOWN"

def fetch_task_outputs(api_key, task_id, task_type="watermark"):
    """获取任务结果"""
    try:
        url = 'https://www.runninghub.cn/task/openapi/outputs'
        response = requests.post(url, json={'apiKey': api_key, 'taskId': task_id}, timeout=OUTPUT_FETCH_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if data.get("code") == 0 and data.get("data"):
            if task_type == "pose":
                file_urls = []
                for output_item in data["data"]:
                    file_url = output_item.get("fileUrl")
                    if file_url:
                        file_urls.append(file_url)
                if file_urls:
                    return file_urls
            else:
                file_url = data["data"][0].get("fileUrl")
                if file_url:
                    return file_url

        raise Exception(f"获取结果失败: {data.get('msg', '未找到结果')}")

    except requests.exceptions.Timeout:
        raise Exception("获取结果超时，请稍后重试")

def download_result_image(url):
    try:
        response = requests.get(url, stream=True, timeout=IMAGE_DOWNLOAD_TIMEOUT)
        response.raise_for_status()
        return response.content
    except requests.exceptions.Timeout:
        raise Exception("下载图片超时")

# --- 素材存储和数据库管理 ---
def init_materials_storage():
    """初始化素材存储目录和数据库"""
    # 创建目录结构
    os.makedirs(MATERIALS_BASE_DIR, exist_ok=True)
    os.makedirs(os.path.join(MATERIALS_BASE_DIR, "image_enhance"), exist_ok=True)
    os.makedirs(os.path.join(MATERIALS_BASE_DIR, "watermark_removal"), exist_ok=True)
    os.makedirs(os.path.join(MATERIALS_BASE_DIR, "pose_transfer"), exist_ok=True)
    os.makedirs(os.path.join(MATERIALS_BASE_DIR, "video_restore"), exist_ok=True)
    os.makedirs(os.path.join(MATERIALS_BASE_DIR, "thumbnails"), exist_ok=True)

    # 创建数据库表
    conn = sqlite3.connect(MATERIALS_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS materials (
            id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            parameters TEXT,
            original_path TEXT,
            result_paths TEXT NOT NULL,
            thumbnail_path TEXT,
            file_size INTEGER,
            status TEXT DEFAULT 'completed'
        )
    ''')

    # 创建索引以加速查询（性能优化）
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_task_type ON materials(task_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON materials(created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON materials(status)')

    conn.commit()
    conn.close()
    logger.info("✅ 素材存储系统初始化完成（含数据库索引）")

def create_thumbnail(image_path, thumb_path, size=(200, 200), quality=70):
    """
    生成缩略图（优化版：更小尺寸，更低质量，更快加载）

    Args:
        image_path: 原始图片路径
        thumb_path: 缩略图保存路径
        size: 缩略图尺寸（默认200x200，从300x300优化）
        quality: JPEG质量（默认70，从85优化）
    """
    try:
        img = Image.open(image_path)
        # 转换RGBA到RGB
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        img.thumbnail(size, Image.LANCZOS)
        img.save(thumb_path, "JPEG", quality=quality, optimize=True)
        return thumb_path
    except Exception as e:
        logger.error(f"生成缩略图失败: {e}")
        return None

def save_material_to_storage(task_id, task_type, parameters, original_data, result_data_list):
    """
    保存素材到永久存储

    Args:
        task_id: 任务ID
        task_type: 任务类型 (image_enhance/watermark_removal/pose_transfer/video_restore)
        parameters: 参数字典
        original_data: 原始文件数据（bytes）
        result_data_list: 结果文件数据列表 [(data, ext)]，ext为扩展名如'png'或'mp4'

    Returns:
        保存的文件路径字典
    """
    try:
        # 创建日期子目录
        date_str = datetime.now().strftime("%Y-%m-%d")
        task_dir = os.path.join(MATERIALS_BASE_DIR, task_type, date_str)
        os.makedirs(task_dir, exist_ok=True)

        # 保存原始文件
        original_path = None
        if original_data:
            original_ext = 'png' if task_type != 'video_restore' else 'mp4'
            original_path = os.path.join(task_dir, f"{task_id}_original.{original_ext}")
            with open(original_path, 'wb') as f:
                f.write(original_data)

        # 保存结果文件
        result_paths = []
        for idx, (data, ext) in enumerate(result_data_list):
            if len(result_data_list) > 1:
                result_path = os.path.join(task_dir, f"{task_id}_result_{idx+1}.{ext}")
            else:
                result_path = os.path.join(task_dir, f"{task_id}_result.{ext}")

            with open(result_path, 'wb') as f:
                f.write(data)
            result_paths.append(result_path)

        # 生成缩略图（仅图片类）
        thumbnail_path = None
        if task_type != 'video_restore' and result_paths:
            thumb_path = os.path.join(MATERIALS_BASE_DIR, "thumbnails", f"{task_id}_thumb.jpg")
            thumbnail_path = create_thumbnail(result_paths[0], thumb_path)

        # 计算文件大小
        file_size = sum(os.path.getsize(p) for p in result_paths if os.path.exists(p))
        if original_path and os.path.exists(original_path):
            file_size += os.path.getsize(original_path)

        # 保存到数据库
        conn = sqlite3.connect(MATERIALS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO materials (id, task_type, created_at, parameters, original_path, result_paths, thumbnail_path, file_size, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            task_id,
            task_type,
            datetime.now().isoformat(),
            json.dumps(parameters, ensure_ascii=False),
            original_path,
            json.dumps(result_paths),
            thumbnail_path,
            file_size,
            'completed'
        ))
        conn.commit()
        conn.close()

        logger.info(f"📦 素材已保存: {task_id} [{task_type}]")
        return {
            'original_path': original_path,
            'result_paths': result_paths,
            'thumbnail_path': thumbnail_path
        }

    except Exception as e:
        logger.error(f"保存素材失败: {e}")
        return None

def cleanup_old_materials():
    """清理14天前的素材"""
    try:
        cutoff_date = datetime.now() - timedelta(days=RETENTION_DAYS)
        cutoff_str = cutoff_date.isoformat()

        conn = sqlite3.connect(MATERIALS_DB_PATH)
        cursor = conn.cursor()

        # 查询需要删除的素材
        cursor.execute('SELECT id, original_path, result_paths, thumbnail_path FROM materials WHERE created_at < ?', (cutoff_str,))
        old_materials = cursor.fetchall()

        deleted_count = 0
        for material_id, original_path, result_paths_json, thumbnail_path in old_materials:
            try:
                # 删除原始文件
                if original_path and os.path.exists(original_path):
                    os.remove(original_path)

                # 删除结果文件
                result_paths = json.loads(result_paths_json)
                for path in result_paths:
                    if os.path.exists(path):
                        os.remove(path)

                # 删除缩略图
                if thumbnail_path and os.path.exists(thumbnail_path):
                    os.remove(thumbnail_path)

                deleted_count += 1
            except Exception as e:
                logger.error(f"删除文件失败 {material_id}: {e}")

        # 从数据库中删除记录
        cursor.execute('DELETE FROM materials WHERE created_at < ?', (cutoff_str,))
        conn.commit()
        conn.close()

        if deleted_count > 0:
            logger.info(f"🗑️ 自动清理完成：删除了 {deleted_count} 个过期素材（{RETENTION_DAYS}天前）")

        return deleted_count

    except Exception as e:
        logger.error(f"清理旧素材失败: {e}")
        return 0

def start_cleanup_scheduler():
    """启动定期清理调度器（每天清理一次）"""
    def cleanup_task():
        while True:
            try:
                cleanup_old_materials()
            except Exception as e:
                logger.error(f"定期清理任务出错: {e}")
            # 每24小时执行一次
            time.sleep(86400)

    cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
    cleanup_thread.start()
    logger.info("⏰ 定期清理调度器已启动（每24小时执行一次）")

# --- 处理函数 ---
def process_watermark(image):
    """去水印处理"""
    if image is None:
        return None, "❌ 请上传图片"

    try:
        # 转换图片格式
        img = Image.fromarray(image)
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # 上传文件
        yield None, "⏳ 正在上传图片..."
        uploaded_filename = upload_file_with_retry(img_byte_arr, "input.png", WATERMARK_API_KEY)

        # 构建节点信息
        node_info_list = copy.deepcopy(WATERMARK_NODE_INFO)
        for node in node_info_list:
            if node["nodeId"] == "191":
                node["fieldValue"] = uploaded_filename

        # 启动任务
        yield None, "⏳ 正在启动去水印任务..."
        task_id = run_task_with_retry(WATERMARK_API_KEY, WATERMARK_WEBAPP_ID, node_info_list)

        # 轮询状态
        poll_count = 0
        while poll_count < MAX_POLL_COUNT:
            time.sleep(POLL_INTERVAL)
            poll_count += 1
            status = get_task_status(WATERMARK_API_KEY, task_id)

            progress = min(90, 35 + (55 * poll_count / MAX_POLL_COUNT))
            yield None, f"⏳ 处理中... {int(progress)}%"

            if status == "SUCCESS":
                break
            elif status == "FAILED":
                raise Exception("API任务处理失败")

        if poll_count >= MAX_POLL_COUNT:
            raise Exception("任务超时")

        # 获取结果
        yield None, "⏳ 正在下载结果..."
        result_url = fetch_task_outputs(WATERMARK_API_KEY, task_id, "watermark")
        result_data = download_result_image(result_url)

        # 转换为图片
        result_image = Image.open(io.BytesIO(result_data))

        yield result_image, "✅ 去水印完成！"

    except Exception as e:
        yield None, f"❌ 处理失败: {str(e)}"

def process_lighting(image):
    """溶图打光处理"""
    if image is None:
        return None, "❌ 请上传图片"

    try:
        # 转换图片格式
        img = Image.fromarray(image)
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # 上传文件
        yield None, "⏳ 正在上传图片..."
        uploaded_filename = upload_file_with_retry(img_byte_arr, "input.png", LIGHTING_API_KEY)

        # 构建节点信息
        node_info_list = copy.deepcopy(LIGHTING_NODE_INFO)
        for node in node_info_list:
            if node["nodeId"] == "437":
                node["fieldValue"] = uploaded_filename

        # 启动任务
        yield None, "⏳ 正在启动溶图打光任务..."
        task_id = run_task_with_retry(LIGHTING_API_KEY, LIGHTING_WEBAPP_ID, node_info_list, instance_type="plus")

        # 轮询状态
        poll_count = 0
        while poll_count < MAX_POLL_COUNT:
            time.sleep(POLL_INTERVAL)
            poll_count += 1
            status = get_task_status(LIGHTING_API_KEY, task_id)

            progress = min(90, 35 + (55 * poll_count / MAX_POLL_COUNT))
            yield None, f"⏳ 处理中... {int(progress)}%"

            if status == "SUCCESS":
                break
            elif status == "FAILED":
                raise Exception("API任务处理失败")

        if poll_count >= MAX_POLL_COUNT:
            raise Exception("任务超时")

        # 获取结果
        yield None, "⏳ 正在下载结果..."
        result_url = fetch_task_outputs(LIGHTING_API_KEY, task_id, "lighting")
        result_data = download_result_image(result_url)

        # 转换为图片
        result_image = Image.open(io.BytesIO(result_data))

        yield result_image, "✅ 溶图打光完成！"

    except Exception as e:
        yield None, f"❌ 处理失败: {str(e)}"

def process_pose(character_image, reference_image):
    """姿态迁移处理"""
    if character_image is None or reference_image is None:
        return None, "❌ 请同时上传角色图片和姿势参考图"

    try:
        # 转换角色图片
        char_img = Image.fromarray(character_image)
        char_byte_arr = io.BytesIO()
        char_img.save(char_byte_arr, format='PNG')
        char_byte_arr = char_byte_arr.getvalue()

        # 转换参考图片
        ref_img = Image.fromarray(reference_image)
        ref_byte_arr = io.BytesIO()
        ref_img.save(ref_byte_arr, format='PNG')
        ref_byte_arr = ref_byte_arr.getvalue()

        # 上传角色图片
        yield None, "⏳ 正在上传角色图片..."
        char_filename = upload_file_with_retry(char_byte_arr, "character.png", POSE_API_KEY)

        # 上传参考图片
        yield None, "⏳ 正在上传姿势参考图..."
        ref_filename = upload_file_with_retry(ref_byte_arr, "reference.png", POSE_API_KEY)

        # 构建节点信息
        node_info_list = copy.deepcopy(POSE_NODE_INFO)
        for node in node_info_list:
            if node["nodeId"] == "245":
                node["fieldValue"] = char_filename
            elif node["nodeId"] == "244":
                node["fieldValue"] = ref_filename

        # 启动任务
        yield None, "⏳ 正在启动姿态迁移任务..."
        task_id = run_task_with_retry(POSE_API_KEY, POSE_WEBAPP_ID, node_info_list)

        # 轮询状态
        poll_count = 0
        while poll_count < MAX_POLL_COUNT:
            time.sleep(POLL_INTERVAL)
            poll_count += 1
            status = get_task_status(POSE_API_KEY, task_id)

            progress = min(90, 35 + (55 * poll_count / MAX_POLL_COUNT))
            yield None, f"⏳ 处理中... {int(progress)}%"

            if status == "SUCCESS":
                break
            elif status == "FAILED":
                raise Exception("API任务处理失败")

        if poll_count >= MAX_POLL_COUNT:
            raise Exception("任务超时")

        # 获取结果
        yield None, "⏳ 正在下载结果..."
        result_urls = fetch_task_outputs(POSE_API_KEY, task_id, "pose")

        # 下载第一个结果（如果有多个结果，取第一个）
        if result_urls:
            result_data = download_result_image(result_urls[0])
            result_image = Image.open(io.BytesIO(result_data))
            yield result_image, f"✅ 姿态迁移完成！生成了 {len(result_urls)} 个结果"
        else:
            raise Exception("未找到结果")

    except Exception as e:
        yield None, f"❌ 处理失败: {str(e)}"

# --- 队列管理（支持50并发） ---
# 全局队列和处理标志
enhance_queue_global = []
watermark_queue_global = []  # 去水印队列
lighting_queue_global = []  # 融图打光队列
pose_queue_global = []  # 姿态迁移队列
video_restore_queue_global = []  # 视频修复队列

# 线程安全的任务队列（用于后台处理）
task_queue = queue.Queue()  # 待处理任务队列

processing_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=50)  # 50并发（图像优化、去水印、融图打光、姿态迁移共享）
video_executor = ThreadPoolExecutor(max_workers=5)  # 5并发（视频修复专用）

# 使用字典而不是set，记录任务ID和开始时间，便于泄漏检测和清理
active_tasks = {}  # {task_id: start_time}
video_active_tasks = {}  # {task_id: start_time}

# 任务超时时间（秒）- 防止任务泄漏
TASK_TIMEOUT = 3600  # 1小时超时自动清理

# --- 风格提示词预设 ---
STYLE_PROMPTS = {
    "默认": {
        "positive": "",
        "negative": ""
    },
    "写实": {
        "positive": "photorealistic, 8k uhd, raw photo, dslr, soft lighting, high quality, film grain, Fujifilm XT3, sharp focus, detailed skin texture, volumetric fog, cinematic composition, (specific lighting: natural light/golden hour/studio lighting), shot on 35mm/50mm/85mm lens, bokeh, ultra detailed, professional photography",
        "negative": "cartoon, cg, 3d render, unreal, anime, illustration, painting, sketch, drawing, artwork, low quality, blurry, pixelated, jpeg artifacts, bad anatomy, deformed, mutated, disfigured, poorly drawn face, extra limbs, duplicate, worst quality, watermark, signature, text"
    },
    "3D卡通": {
        "positive": "3d render, pixar style, disney style, octane render, blender, unreal engine 5, cute character design, stylized, volumetric lighting, soft shadows, vibrant colors, high detail, 8k, cartoon aesthetic, smooth surfaces, professional 3d artwork, trending on artstation, perfect topology, clean geometry",
        "negative": "realistic, photorealistic, real photo, photograph, 2d, flat, sketch, low poly, low quality, blurry, pixelated, bad anatomy, deformed, poorly modeled, bad topology, artifacts, glitches, worst quality, low detail, amateur, noise, grain, dirty render"
    }
}

def add_to_queue(files, version, style, queue_state):
    """添加文件到队列（自动触发）"""
    global enhance_queue_global

    if not files:
        return None, queue_state, render_queue_dataframe(queue_state), "⚠️ 未选择文件"

    # 初始化队列
    if queue_state is None:
        queue_state = []

    # 添加新文件到队列
    for file in files:
        file_id = str(uuid.uuid4())[:8]
        item = {
            "id": file_id,
            "file": file,
            "version": version,
            "style": style,  # 添加风格参数
            "status": "pending",
            "original": None,
            "enhanced": None,
            "error": None,
            "start_time": None  # 开始处理的时间
        }
        queue_state.append(item)
        enhance_queue_global.append(item)

    # 启动后台处理（如果未在处理中）
    start_background_processing()

    # 清空文件选择器并更新显示
    return None, queue_state, render_queue_dataframe(queue_state), f"✅ 已添加 {len(files)} 张图片到队列，正在处理中..."

def cleanup_stale_tasks():
    """清理超时的僵尸任务，防止active_tasks泄漏"""
    global active_tasks, video_active_tasks

    current_time = time.time()

    # 清理图像任务
    stale_tasks = []
    for task_id, start_time in active_tasks.items():
        if current_time - start_time > TASK_TIMEOUT:
            stale_tasks.append(task_id)
            logger.warning(f"⚠️ 清理超时任务: {task_id} (运行时长: {int(current_time - start_time)}秒)")

    for task_id in stale_tasks:
        active_tasks.pop(task_id, None)

    # 清理视频任务
    stale_video_tasks = []
    for task_id, start_time in video_active_tasks.items():
        if current_time - start_time > TASK_TIMEOUT:
            stale_video_tasks.append(task_id)
            logger.warning(f"⚠️ 清理超时视频任务: {task_id} (运行时长: {int(current_time - start_time)}秒)")

    for task_id in stale_video_tasks:
        video_active_tasks.pop(task_id, None)

def background_task_processor():
    """单一后台线程处理所有任务（防止无限线程创建）"""
    global BACKGROUND_THREAD_ACTIVE

    logger.info("🚀 后台任务处理线程已启动")

    while BACKGROUND_THREAD_ACTIVE:
        try:
            # 定期清理僵尸任务
            cleanup_stale_tasks()

            with processing_lock:
                # 获取所有待处理的任务
                pending_enhance_tasks = [task for task in enhance_queue_global if task["status"] == "pending"]
                pending_watermark_tasks = [task for task in watermark_queue_global if task["status"] == "pending"]
                pending_lighting_tasks = [task for task in lighting_queue_global if task["status"] == "pending"]
                pending_pose_tasks = [task for task in pose_queue_global if task["status"] == "pending"]

                # 合并所有待处理任务
                all_pending_tasks = pending_enhance_tasks + pending_watermark_tasks + pending_lighting_tasks + pending_pose_tasks

                # 计算可用槽位
                available_slots = 50 - len(active_tasks)

                # 提交新任务到线程池
                for task in all_pending_tasks[:available_slots]:
                    if task["id"] not in active_tasks:
                        active_tasks[task["id"]] = time.time()  # 记录开始时间
                        task_type_map = {
                            "watermark": "去水印",
                            "lighting": "融图打光",
                            "pose": "姿态迁移",
                        }
                        task_type = task_type_map.get(task.get("task_type"), "图像优化")
                        logger.info(f"🚀 提交任务到线程池: {task['id']} [{task_type}] (当前活跃: {len(active_tasks)}/50)")

                        # 根据任务类型选择处理函数
                        if task.get("task_type") == "watermark":
                            executor.submit(process_watermark_item_wrapper, task)
                        elif task.get("task_type") == "lighting":
                            executor.submit(process_lighting_item_wrapper, task)
                        elif task.get("task_type") == "pose":
                            executor.submit(process_pose_item_wrapper, task)
                        else:
                            executor.submit(process_single_item_wrapper, task)

            # 非阻塞等待（降低CPU占用）
            time.sleep(2)

        except Exception as e:
            logger.error(f"❌ 后台任务处理线程异常: {e}")
            time.sleep(5)

    logger.info("🛑 后台任务处理线程已停止")

def start_background_processing():
    """启动后台处理线程（只启动一次，防止无限线程创建）"""
    global BACKGROUND_THREAD_ACTIVE

    # 使用锁防止重复启动
    with BACKGROUND_THREAD_LOCK:
        if not BACKGROUND_THREAD_ACTIVE:
            BACKGROUND_THREAD_ACTIVE = True
            thread = threading.Thread(target=background_task_processor, daemon=True, name="BackgroundTaskProcessor")
            thread.start()
            logger.info("✅ 后台任务处理线程已创建")

def start_video_processing():
    """启动视频修复后台处理线程（限制2并发，视频处理更消耗资源）"""
    global video_active_tasks

    with processing_lock:
        # 获取所有待处理的视频修复任务
        pending_video_tasks = [task for task in video_restore_queue_global if task["status"] == "pending"]

        # 计算可以启动的新任务数量（视频处理限制为2，避免内存溢出）
        available_slots = min(2 - len(video_active_tasks), 5 - len(video_active_tasks))

        # 提交新任务到视频线程池
        for task in pending_video_tasks[:available_slots]:
            if task["id"] not in video_active_tasks:
                video_active_tasks.add(task["id"])
                logger.info(f"🚀 提交视频修复任务到线程池: {task['id']} (当前活跃: {len(video_active_tasks)}/5)")
                video_executor.submit(process_video_restore_item_wrapper, task)

def process_single_item_wrapper(item):
    """包装器：处理单个任务并更新活跃任务集"""
    global active_tasks

    try:
        process_single_item(item)
    except Exception as e:
        logger.error(f"处理任务失败: {e}")
        item["status"] = "error"
        item["error"] = str(e)
    finally:
        # 任务完成后从活跃字典中移除（防止泄漏）
        with processing_lock:
            active_tasks.pop(item["id"], None)

        # 强制垃圾回收，及时释放内存
        gc.collect()

def process_single_item(item):
    """处理单个图片优化任务"""
    try:
        # 更新状态为处理中，记录开始时间
        item["status"] = "processing"
        item["start_time"] = time.time()  # 记录开始时间用于倒计时
        logger.info(f"📝 任务 {item['id']} 状态: pending -> processing")

        # 读取图片文件
        img_data = item["file"]
        img = Image.open(io.BytesIO(img_data))

        # 保存原图（转为PNG）
        original_buffer = io.BytesIO()
        img.save(original_buffer, format='PNG')
        item["original"] = original_buffer.getvalue()

        # 根据版本和风格选择配置
        version = item["version"]
        style = item.get("style", "默认")
        instance_type = None  # 默认不指定实例类型

        if version == "WAN 2.1":
            # WAN 2.1 所有风格都使用原版本API
            webapp_id = ENHANCE_WEBAPP_ID_V2_1
            node_info = ENHANCE_NODE_INFO_V2_1
            image_node_id = "38"
        else:  # WAN 2.2
            # WAN 2.2 根据风格选择不同的API
            if style == "写实":
                # WAN 2.2 + 写实使用专用API
                webapp_id = ENHANCE_WEBAPP_ID_V2_2_REALISTIC
                node_info = ENHANCE_NODE_INFO_V2_2_REALISTIC
                image_node_id = "14"
                instance_type = "plus"  # 写实API需要plus实例
                logger.info(f"🎨 任务 {item['id']} 使用WAN 2.2 写实专用API (plus)")
            elif style == "3D卡通":
                # WAN 2.2 + 3D卡通使用专用API
                webapp_id = ENHANCE_WEBAPP_ID_V2_2_3D
                node_info = ENHANCE_NODE_INFO_V2_2_3D
                image_node_id = "38"
                logger.info(f"🎨 任务 {item['id']} 使用WAN 2.2 3D卡通专用API")
            else:
                # WAN 2.2 + 默认使用原版本API
                webapp_id = ENHANCE_WEBAPP_ID_V2_2
                node_info = ENHANCE_NODE_INFO_V2_2
                image_node_id = "14"

        # 上传文件
        logger.info(f"⬆️ 任务 {item['id']} 开始上传文件到API")
        uploaded_filename = upload_file_with_retry(item["original"], f"input_{item['id']}.png", ENHANCE_API_KEY)

        # 构建节点信息
        node_info_list = copy.deepcopy(node_info)
        for node in node_info_list:
            if node["nodeId"] == image_node_id:
                node["fieldValue"] = uploaded_filename

        # 添加风格提示词
        # WAN 2.2的3D卡通和写实已经在API配置中包含了提示词，不需要额外添加
        # 仅对WAN 2.2的默认，以及WAN 2.1的所有风格添加提示词
        if not (version == "WAN 2.2" and style in ["3D卡通", "写实"]):
            if style != "默认" and style in STYLE_PROMPTS:
                prompts = STYLE_PROMPTS[style]

                # 根据版本选择不同的nodeId
                if version == "WAN 2.2":
                    positive_node_id = "66"  # WAN 2.2的正向提示词节点
                    negative_node_id = "21"  # WAN 2.2的反向提示词节点
                else:  # WAN 2.1
                    positive_node_id = "60"  # WAN 2.1的正向提示词节点
                    negative_node_id = "4"   # WAN 2.1的反向提示词节点

                # 添加正向提示词
                if prompts["positive"]:
                    node_info_list.append({
                        "nodeId": positive_node_id,
                        "fieldName": "text",
                        "fieldValue": prompts["positive"],
                        "description": "text"
                    })

                # 添加反向提示词
                if prompts["negative"]:
                    node_info_list.append({
                        "nodeId": negative_node_id,
                        "fieldName": "text",
                        "fieldValue": prompts["negative"],
                        "description": "text"
                    })

                logger.info(f"🎨 任务 {item['id']} 应用风格: {style} [正向节点:{positive_node_id}, 反向节点:{negative_node_id}]")

        # 启动任务
        logger.info(f"🎬 任务 {item['id']} 提交API处理请求 [{version}] instance_type={instance_type}")
        task_id = run_task_with_retry(ENHANCE_API_KEY, webapp_id, node_info_list, instance_type=instance_type)

        # 轮询状态
        poll_count = 0
        while poll_count < MAX_POLL_COUNT:
            time.sleep(POLL_INTERVAL)
            poll_count += 1
            status = get_task_status(ENHANCE_API_KEY, task_id)

            if status == "SUCCESS":
                break
            elif status == "FAILED":
                raise Exception("API任务处理失败")

        if poll_count >= MAX_POLL_COUNT:
            raise Exception("任务超时")

        # 获取结果
        logger.info(f"⬇️ 任务 {item['id']} 开始下载结果")
        result_url = fetch_task_outputs(ENHANCE_API_KEY, task_id, "enhance")
        result_data = download_result_image(result_url)

        # 保存优化后的图片（强制转换为PNG格式）
        result_image = Image.open(io.BytesIO(result_data))
        logger.info(f"📸 任务 {item['id']} API返回图片格式: {result_image.format}")

        # 如果图片有透明通道(RGBA)，转换为RGB
        if result_image.mode == 'RGBA':
            # 创建白色背景
            background = Image.new('RGB', result_image.size, (255, 255, 255))
            background.paste(result_image, mask=result_image.split()[3])  # 使用alpha通道作为mask
            result_image = background
        elif result_image.mode != 'RGB':
            result_image = result_image.convert('RGB')

        enhanced_buffer = io.BytesIO()
        result_image.save(enhanced_buffer, format='PNG')
        item["enhanced"] = enhanced_buffer.getvalue()
        logger.info(f"💾 任务 {item['id']} 已转换并保存为PNG格式")

        # 保存到永久存储
        try:
            save_material_to_storage(
                task_id=item["id"],
                task_type="image_enhance",
                parameters={"version": version, "style": style},
                original_data=item["original"],
                result_data_list=[(item["enhanced"], 'png')]
            )
        except Exception as e:
            logger.error(f"保存素材到永久存储失败: {e}")

        # 更新状态为完成
        item["status"] = "completed"
        logger.info(f"✅ 任务 {item['id']} 完成！状态: processing -> completed")

    except Exception as e:
        item["status"] = "error"
        item["error"] = str(e)
        logger.error(f"❌ 任务 {item['id']} 失败: {str(e)}")
        raise

def get_queue_status(queue_state):
    """获取队列状态（定时刷新）"""
    if queue_state is None:
        return queue_state, []
    return queue_state, render_queue_dataframe(queue_state)

def render_queue_dataframe(queue_state):
    """渲染队列为DataFrame数据（带倒计时）"""
    if not queue_state:
        return []

    # 生成DataFrame数据
    data = []
    for item in queue_state:
        # 显示模型版本
        model_version = item.get("version", "---")

        # 显示风格
        style = item.get("style", "默认")

        # 状态显示逻辑
        status = item["status"]
        if status == "pending":
            status_display = "⏳ 等待中"
        elif status == "processing":
            # 倒计时逻辑：从2分30秒开始
            start_time = item.get("start_time")
            if start_time:
                elapsed = time.time() - start_time
                remaining = 150 - elapsed  # 150秒 = 2分30秒

                if remaining > 0:
                    # 显示倒计时
                    minutes = int(remaining // 60)
                    seconds = int(remaining % 60)
                    status_display = f"预计还剩{minutes}:{seconds:02d}"
                else:
                    # 超时了还在处理
                    status_display = "全力处理中~"
            else:
                status_display = "🔄 处理中"
        elif status == "completed":
            status_display = "✅ 已完成"
        elif status == "error":
            status_display = "❌ 失败"
        else:
            status_display = "未知"

        # 操作列
        view_text = "点击查看" if status == "completed" else "---"

        data.append([
            item["id"],
            status_display,
            model_version,
            style,
            view_text
        ])

    return data

def handle_dataframe_click(evt: gr.SelectData, queue_state):
    """处理DataFrame点击事件（显示图片）"""
    if not queue_state or evt.index[0] >= len(queue_state):
        return None, None

    row_index = evt.index[0]
    item = queue_state[row_index]

    # 显示图片
    if item["status"] == "completed" and item["original"] and item["enhanced"]:
        # 转换为PIL Image
        original_img = Image.open(io.BytesIO(item["original"]))
        enhanced_img = Image.open(io.BytesIO(item["enhanced"]))

        # 统一高度到800px，保持宽高比
        target_height = 800

        # 调整原图大小
        orig_width, orig_height = original_img.size
        if orig_height != target_height:
            scale = target_height / orig_height
            new_width = int(orig_width * scale)
            original_img = original_img.resize((new_width, target_height), Image.LANCZOS)

        # 调整优化图大小
        enh_width, enh_height = enhanced_img.size
        if enh_height != target_height:
            scale = target_height / enh_height
            new_width = int(enh_width * scale)
            enhanced_img = enhanced_img.resize((new_width, target_height), Image.LANCZOS)

        # 将PIL Image保存为PNG临时文件，确保Gradio以PNG格式处理
        import tempfile

        # 保存原图为PNG
        with tempfile.NamedTemporaryFile(delete=False, suffix='_original.png', mode='wb') as f:
            original_img.save(f, format='PNG')
            original_temp_path = f.name

        # 保存优化图为PNG
        with tempfile.NamedTemporaryFile(delete=False, suffix='_enhanced.png', mode='wb') as f:
            enhanced_img.save(f, format='PNG')
            enhanced_temp_path = f.name

        return original_temp_path, enhanced_temp_path

    return None, None

def clear_queue():
    """清空图像优化队列"""
    global enhance_queue_global
    enhance_queue_global = []
    return None, [], "✅ 队列已清空"

# --- 去水印队列管理函数 ---
def add_watermark_to_queue(files, queue_state):
    """添加文件到去水印队列（自动触发）"""
    global watermark_queue_global

    if not files:
        return None, queue_state, render_watermark_queue_dataframe(queue_state), "⚠️ 未选择文件"

    # 初始化队列
    if queue_state is None:
        queue_state = []

    # 添加新文件到队列
    for file in files:
        file_id = str(uuid.uuid4())[:8]
        item = {
            "id": file_id,
            "file": file,
            "task_type": "watermark",  # 标记为去水印任务
            "status": "pending",
            "original": None,
            "result": None,
            "error": None,
            "start_time": None
        }
        queue_state.append(item)
        watermark_queue_global.append(item)

    # 启动后台处理
    start_background_processing()

    # 清空文件选择器并更新显示
    return None, queue_state, render_watermark_queue_dataframe(queue_state), f"✅ 已添加 {len(files)} 张图片到队列，正在处理中..."

def process_watermark_item_wrapper(item):
    """包装器：处理单个去水印任务并更新活跃任务集"""
    global active_tasks

    try:
        process_watermark_item(item)
    except Exception as e:
        logger.error(f"去水印任务失败: {e}")
        item["status"] = "error"
        item["error"] = str(e)
    finally:
        # 任务完成后从活跃字典中移除（防止泄漏）
        with processing_lock:
            active_tasks.pop(item["id"], None)

        # 强制垃圾回收，及时释放内存
        gc.collect()

def process_watermark_item(item):
    """处理单个去水印任务"""
    try:
        # 更新状态为处理中，记录开始时间
        item["status"] = "processing"
        item["start_time"] = time.time()
        logger.info(f"📝 去水印任务 {item['id']} 状态: pending -> processing")

        # 读取图片文件
        img_data = item["file"]
        img = Image.open(io.BytesIO(img_data))

        # 保存原图（转为PNG）
        original_buffer = io.BytesIO()
        img.save(original_buffer, format='PNG')
        item["original"] = original_buffer.getvalue()

        # 转换图片格式
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # 上传文件
        logger.info(f"⬆️ 去水印任务 {item['id']} 开始上传文件到API")
        uploaded_filename = upload_file_with_retry(img_byte_arr, "input.png", WATERMARK_API_KEY)

        # 构建节点信息
        node_info_list = copy.deepcopy(WATERMARK_NODE_INFO)
        for node in node_info_list:
            if node["nodeId"] == "191":
                node["fieldValue"] = uploaded_filename

        # 启动任务
        logger.info(f"🎬 去水印任务 {item['id']} 提交API处理请求")
        task_id = run_task_with_retry(WATERMARK_API_KEY, WATERMARK_WEBAPP_ID, node_info_list)

        # 轮询状态
        poll_count = 0
        while poll_count < MAX_POLL_COUNT:
            time.sleep(POLL_INTERVAL)
            poll_count += 1
            status = get_task_status(WATERMARK_API_KEY, task_id)

            if status == "SUCCESS":
                break
            elif status == "FAILED":
                raise Exception("API任务处理失败")

        if poll_count >= MAX_POLL_COUNT:
            raise Exception("任务超时")

        # 获取结果
        logger.info(f"⬇️ 去水印任务 {item['id']} 开始下载结果")
        result_url = fetch_task_outputs(WATERMARK_API_KEY, task_id, "watermark")
        result_data = download_result_image(result_url)

        # 转换为图片并保存为PNG
        result_image = Image.open(io.BytesIO(result_data))

        # 如果图片有透明通道(RGBA)，转换为RGB
        if result_image.mode == 'RGBA':
            background = Image.new('RGB', result_image.size, (255, 255, 255))
            background.paste(result_image, mask=result_image.split()[3])
            result_image = background
        elif result_image.mode != 'RGB':
            result_image = result_image.convert('RGB')

        result_buffer = io.BytesIO()
        result_image.save(result_buffer, format='PNG')
        item["result"] = result_buffer.getvalue()
        logger.info(f"💾 去水印任务 {item['id']} 已保存为PNG格式")

        # 保存到永久存储
        try:
            save_material_to_storage(
                task_id=item["id"],
                task_type="watermark_removal",
                parameters={},
                original_data=item["original"],
                result_data_list=[(item["result"], 'png')]
            )
        except Exception as e:
            logger.error(f"保存素材到永久存储失败: {e}")

        # 更新状态为完成
        item["status"] = "completed"
        logger.info(f"✅ 去水印任务 {item['id']} 完成！")

    except Exception as e:
        item["status"] = "error"
        item["error"] = str(e)
        logger.error(f"❌ 去水印任务 {item['id']} 失败: {str(e)}")
        raise

def get_watermark_queue_status(queue_state):
    """获取去水印队列状态（定时刷新）"""
    if queue_state is None:
        return queue_state, []
    return queue_state, render_watermark_queue_dataframe(queue_state)

def render_watermark_queue_dataframe(queue_state):
    """渲染去水印队列为DataFrame数据"""
    if not queue_state:
        return []

    data = []
    for item in queue_state:
        # 状态显示逻辑
        status = item["status"]
        if status == "pending":
            status_display = "⏳ 等待中"
        elif status == "processing":
            start_time = item.get("start_time")
            if start_time:
                elapsed = time.time() - start_time
                remaining = 120 - elapsed  # 120秒 = 2分钟

                if remaining > 0:
                    minutes = int(remaining // 60)
                    seconds = int(remaining % 60)
                    status_display = f"预计还剩{minutes}:{seconds:02d}"
                else:
                    status_display = "全力处理中~"
            else:
                status_display = "🔄 处理中"
        elif status == "completed":
            status_display = "✅ 已完成"
        elif status == "error":
            status_display = "❌ 失败"
        else:
            status_display = "未知"

        # 操作列
        view_text = "点击查看" if status == "completed" else "---"

        data.append([
            item["id"],
            status_display,
            view_text
        ])

    return data

def handle_watermark_dataframe_click(evt: gr.SelectData, queue_state):
    """处理去水印DataFrame点击事件"""
    if not queue_state or evt.index[0] >= len(queue_state):
        return None, None

    row_index = evt.index[0]
    item = queue_state[row_index]

    # 显示图片
    if item["status"] == "completed" and item["original"] and item["result"]:
        # 转换为PIL Image
        original_img = Image.open(io.BytesIO(item["original"]))
        result_img = Image.open(io.BytesIO(item["result"]))

        # 统一高度到800px
        target_height = 800

        # 调整原图大小
        orig_width, orig_height = original_img.size
        if orig_height != target_height:
            scale = target_height / orig_height
            new_width = int(orig_width * scale)
            original_img = original_img.resize((new_width, target_height), Image.LANCZOS)

        # 调整结果图大小
        result_width, result_height = result_img.size
        if result_height != target_height:
            scale = target_height / result_height
            new_width = int(result_width * scale)
            result_img = result_img.resize((new_width, target_height), Image.LANCZOS)

        # 保存为PNG临时文件
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix='_original.png', mode='wb') as f:
            original_img.save(f, format='PNG')
            original_temp_path = f.name

        with tempfile.NamedTemporaryFile(delete=False, suffix='_watermark_removed.png', mode='wb') as f:
            result_img.save(f, format='PNG')
            result_temp_path = f.name

        return original_temp_path, result_temp_path

    return None, None

def clear_watermark_queue():
    """清空去水印队列"""
    global watermark_queue_global
    watermark_queue_global = []
    return None, [], "✅ 队列已清空"

# --- 姿态迁移队列管理函数 ---
def add_pose_to_queue(character_files, pose_files, strength, queue_state):
    """添加文件到姿态迁移队列（自动触发）"""
    global pose_queue_global

    if not character_files or not pose_files:
        return None, None, queue_state, render_pose_queue_dataframe(queue_state), "⚠️ 请同时上传角色图和姿态图"

    # 初始化队列
    if queue_state is None:
        queue_state = []

    # 添加新任务到队列（按较少的文件数量配对）
    min_count = min(len(character_files), len(pose_files))
    for i in range(min_count):
        file_id = str(uuid.uuid4())[:8]
        item = {
            "id": file_id,
            "character_file": character_files[i],
            "pose_file": pose_files[i],
            "strength": strength,
            "task_type": "pose",  # 标记为姿态迁移任务
            "status": "pending",
            "character_original": None,
            "result_1": None,
            "result_2": None,
            "error": None,
            "start_time": None
        }
        queue_state.append(item)
        pose_queue_global.append(item)

    # 启动后台处理
    start_background_processing()

    # 清空文件选择器并更新显示
    return None, None, queue_state, render_pose_queue_dataframe(queue_state), f"✅ 已添加 {min_count} 个任务到队列，正在处理中..."

def process_pose_item_wrapper(item):
    """包装器：处理单个姿态迁移任务并更新活跃任务集"""
    global active_tasks

    try:
        process_pose_item(item)
    except Exception as e:
        logger.error(f"姿态迁移任务失败: {e}")
        item["status"] = "error"
        item["error"] = str(e)
    finally:
        # 任务完成后从活跃字典中移除（防止泄漏）
        with processing_lock:
            active_tasks.pop(item["id"], None)

        # 强制垃圾回收，及时释放内存
        gc.collect()

def process_pose_item(item):
    """处理单个姿态迁移任务"""
    try:
        # 更新状态为处理中，记录开始时间
        item["status"] = "processing"
        item["start_time"] = time.time()
        logger.info(f"📝 姿态迁移任务 {item['id']} 状态: pending -> processing")

        # 读取角色图片
        char_data = item["character_file"]
        char_img = Image.open(io.BytesIO(char_data))

        # 保存角色原图（转为PNG）
        character_buffer = io.BytesIO()
        char_img.save(character_buffer, format='PNG')
        item["character_original"] = character_buffer.getvalue()

        # 读取姿态图片
        pose_data = item["pose_file"]
        pose_img = Image.open(io.BytesIO(pose_data))

        # 转换图片为PNG格式用于上传
        char_byte_arr = io.BytesIO()
        char_img.save(char_byte_arr, format='PNG')
        char_byte_arr = char_byte_arr.getvalue()

        pose_byte_arr = io.BytesIO()
        pose_img.save(pose_byte_arr, format='PNG')
        pose_byte_arr = pose_byte_arr.getvalue()

        # 上传角色图片
        logger.info(f"⬆️ 姿态迁移任务 {item['id']} 开始上传角色图到API")
        char_filename = upload_file_with_retry(char_byte_arr, "character.jpg", POSE_API_KEY)

        # 上传姿态图片
        logger.info(f"⬆️ 姿态迁移任务 {item['id']} 开始上传姿态图到API")
        pose_filename = upload_file_with_retry(pose_byte_arr, "pose.jpg", POSE_API_KEY)

        # 构建节点信息
        node_info_list = copy.deepcopy(POSE_NODE_INFO_NEW)
        for node in node_info_list:
            if node["nodeId"] == "6":  # 角色图
                node["fieldValue"] = char_filename
            elif node["nodeId"] == "73":  # 姿态图
                node["fieldValue"] = pose_filename
            elif node["nodeId"] == "140":  # 强度值
                node["fieldValue"] = str(int(item["strength"]))

        # 启动任务
        logger.info(f"🎬 姿态迁移任务 {item['id']} 提交API处理请求 (强度: {item['strength']})")
        task_id = run_task_with_retry(POSE_API_KEY, POSE_WEBAPP_ID_NEW, node_info_list)

        # 轮询状态
        poll_count = 0
        while poll_count < MAX_POLL_COUNT:
            time.sleep(POLL_INTERVAL)
            poll_count += 1
            status = get_task_status(POSE_API_KEY, task_id)

            if status == "SUCCESS":
                break
            elif status == "FAILED":
                raise Exception("API任务处理失败")

        if poll_count >= MAX_POLL_COUNT:
            raise Exception("任务超时")

        # 获取结果
        logger.info(f"⬇️ 姿态迁移任务 {item['id']} 开始下载结果")
        result_urls = fetch_task_outputs(POSE_API_KEY, task_id, "pose")

        # 下载两张结果图片
        if result_urls and len(result_urls) >= 2:
            # 下载第一张结果图
            result_data_1 = download_result_image(result_urls[0])
            result_image_1 = Image.open(io.BytesIO(result_data_1))

            # 如果图片有透明通道(RGBA)，转换为RGB
            if result_image_1.mode == 'RGBA':
                background = Image.new('RGB', result_image_1.size, (255, 255, 255))
                background.paste(result_image_1, mask=result_image_1.split()[3])
                result_image_1 = background
            elif result_image_1.mode != 'RGB':
                result_image_1 = result_image_1.convert('RGB')

            result_buffer_1 = io.BytesIO()
            result_image_1.save(result_buffer_1, format='PNG')
            item["result_1"] = result_buffer_1.getvalue()

            # 下载第二张结果图
            result_data_2 = download_result_image(result_urls[1])
            result_image_2 = Image.open(io.BytesIO(result_data_2))

            # 如果图片有透明通道(RGBA)，转换为RGB
            if result_image_2.mode == 'RGBA':
                background = Image.new('RGB', result_image_2.size, (255, 255, 255))
                background.paste(result_image_2, mask=result_image_2.split()[3])
                result_image_2 = background
            elif result_image_2.mode != 'RGB':
                result_image_2 = result_image_2.convert('RGB')

            result_buffer_2 = io.BytesIO()
            result_image_2.save(result_buffer_2, format='PNG')
            item["result_2"] = result_buffer_2.getvalue()

            logger.info(f"💾 姿态迁移任务 {item['id']} 已保存两张PNG格式图片")

            # 保存到永久存储
            try:
                save_material_to_storage(
                    task_id=item["id"],
                    task_type="pose_transfer",
                    parameters={"strength": item["strength"]},
                    original_data=item["character_original"],
                    result_data_list=[(item["result_1"], 'png'), (item["result_2"], 'png')]
                )
            except Exception as e:
                logger.error(f"保存素材到永久存储失败: {e}")

            # 更新状态为完成
            item["status"] = "completed"
            logger.info(f"✅ 姿态迁移任务 {item['id']} 完成！")
        else:
            raise Exception(f"API返回结果数量不足，期望2张，实际{len(result_urls) if result_urls else 0}张")

    except Exception as e:
        item["status"] = "error"
        item["error"] = str(e)
        logger.error(f"❌ 姿态迁移任务 {item['id']} 失败: {str(e)}")
        raise

def get_pose_queue_status(queue_state):
    """获取姿态迁移队列状态（定时刷新）"""
    if queue_state is None:
        return queue_state, []
    return queue_state, render_pose_queue_dataframe(queue_state)

def render_pose_queue_dataframe(queue_state):
    """渲染姿态迁移队列为DataFrame数据"""
    if not queue_state:
        return []

    data = []
    for item in queue_state:
        # 状态显示逻辑
        status = item["status"]
        if status == "pending":
            status_display = "⏳ 等待中"
        elif status == "processing":
            start_time = item.get("start_time")
            if start_time:
                elapsed = time.time() - start_time
                remaining = 150 - elapsed  # 150秒 = 2分30秒

                if remaining > 0:
                    minutes = int(remaining // 60)
                    seconds = int(remaining % 60)
                    status_display = f"预计还剩{minutes}:{seconds:02d}"
                else:
                    status_display = "全力处理中~"
            else:
                status_display = "🔄 处理中"
        elif status == "completed":
            status_display = "✅ 已完成"
        elif status == "error":
            status_display = "❌ 失败"
        else:
            status_display = "未知"

        # 强度值
        strength_display = str(int(item.get("strength", 15)))

        # 操作列
        view_text = "点击查看" if status == "completed" else "---"

        data.append([
            item["id"],
            status_display,
            strength_display,
            view_text
        ])

    return data

def handle_pose_dataframe_click(evt: gr.SelectData, queue_state):
    """处理姿态迁移DataFrame点击事件"""
    if not queue_state or evt.index[0] >= len(queue_state):
        return None, None

    row_index = evt.index[0]
    item = queue_state[row_index]

    # 显示两张结果图片
    if item["status"] == "completed" and item["result_1"] and item["result_2"]:
        # 转换为PIL Image
        result_img_1 = Image.open(io.BytesIO(item["result_1"]))
        result_img_2 = Image.open(io.BytesIO(item["result_2"]))

        # 统一高度到800px
        target_height = 800

        # 调整第一张结果图大小
        width_1, height_1 = result_img_1.size
        if height_1 != target_height:
            scale = target_height / height_1
            new_width = int(width_1 * scale)
            result_img_1 = result_img_1.resize((new_width, target_height), Image.LANCZOS)

        # 调整第二张结果图大小
        width_2, height_2 = result_img_2.size
        if height_2 != target_height:
            scale = target_height / height_2
            new_width = int(width_2 * scale)
            result_img_2 = result_img_2.resize((new_width, target_height), Image.LANCZOS)

        # 保存为PNG临时文件
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix='_pose_result_1.png', mode='wb') as f:
            result_img_1.save(f, format='PNG')
            result_1_temp_path = f.name

        with tempfile.NamedTemporaryFile(delete=False, suffix='_pose_result_2.png', mode='wb') as f:
            result_img_2.save(f, format='PNG')
            result_2_temp_path = f.name

        return result_1_temp_path, result_2_temp_path

    return None, None

def clear_pose_queue():
    """清空姿态迁移队列"""
    global pose_queue_global
    pose_queue_global = []
    return None, None, None, [], "✅ 队列已清空"

# --- 融图打光队列管理函数 ---
def add_lighting_to_queue(files, queue_state):
    """添加文件到融图打光队列（自动触发）"""
    global lighting_queue_global

    if not files:
        return None, queue_state, render_lighting_queue_dataframe(queue_state), "⚠️ 未选择文件"

    # 初始化队列
    if queue_state is None:
        queue_state = []

    # 添加新文件到队列
    for file in files:
        file_id = str(uuid.uuid4())[:8]
        item = {
            "id": file_id,
            "file": file,
            "task_type": "lighting",  # 标记为融图打光任务
            "status": "pending",
            "original": None,
            "result": None,
            "error": None,
            "start_time": None
        }
        queue_state.append(item)
        lighting_queue_global.append(item)

    # 启动后台处理
    start_background_processing()

    # 清空文件选择器并更新显示
    return None, queue_state, render_lighting_queue_dataframe(queue_state), f"✅ 已添加 {len(files)} 张图片到队列，正在处理中..."

def process_lighting_item_wrapper(item):
    """包装器：处理单个融图打光任务并更新活跃任务集"""
    global active_tasks

    try:
        process_lighting_item(item)
    except Exception as e:
        logger.error(f"融图打光任务失败: {e}")
        item["status"] = "error"
        item["error"] = str(e)
    finally:
        # 任务完成后从活跃字典中移除（防止泄漏）
        with processing_lock:
            active_tasks.pop(item["id"], None)

        # 强制垃圾回收，及时释放内存
        gc.collect()

def process_lighting_item(item):
    """处理单个融图打光任务"""
    try:
        # 更新状态为处理中，记录开始时间
        item["status"] = "processing"
        item["start_time"] = time.time()
        logger.info(f"📝 融图打光任务 {item['id']} 状态: pending -> processing")

        # 读取图片文件
        img_data = item["file"]
        img = Image.open(io.BytesIO(img_data))

        # 保存原图（转为PNG）
        original_buffer = io.BytesIO()
        img.save(original_buffer, format='PNG')
        item["original"] = original_buffer.getvalue()

        # 转换图片格式
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # 上传文件
        logger.info(f"⬆️ 融图打光任务 {item['id']} 开始上传文件到API")
        uploaded_filename = upload_file_with_retry(img_byte_arr, "input.png", LIGHTING_API_KEY)

        # 构建节点信息
        node_info_list = copy.deepcopy(LIGHTING_NODE_INFO)
        for node in node_info_list:
            if node["nodeId"] == "437":
                node["fieldValue"] = uploaded_filename

        # 启动任务（使用plus实例类型）
        logger.info(f"🎬 融图打光任务 {item['id']} 提交API处理请求")
        task_id = run_task_with_retry(LIGHTING_API_KEY, LIGHTING_WEBAPP_ID, node_info_list, instance_type="plus")

        # 轮询状态
        poll_count = 0
        while poll_count < MAX_POLL_COUNT:
            time.sleep(POLL_INTERVAL)
            poll_count += 1
            status = get_task_status(LIGHTING_API_KEY, task_id)

            if status == "SUCCESS":
                break
            elif status == "FAILED":
                raise Exception("API任务处理失败")

        if poll_count >= MAX_POLL_COUNT:
            raise Exception("任务超时")

        # 获取结果
        logger.info(f"⬇️ 融图打光任务 {item['id']} 开始下载结果")
        result_url = fetch_task_outputs(LIGHTING_API_KEY, task_id, "lighting")
        result_data = download_result_image(result_url)

        # 转换为图片并保存
        result_image = Image.open(io.BytesIO(result_data))
        result_buffer = io.BytesIO()
        result_image.save(result_buffer, format='PNG')
        item["result"] = result_buffer.getvalue()
        logger.info(f"💾 融图打光任务 {item['id']} 已保存为PNG格式")

        # 保存到永久存储
        try:
            save_material_to_storage(
                task_id=item["id"],
                task_type="lighting",
                parameters={},
                original_data=item["original"],
                result_data_list=[(item["result"], 'png')]
            )
        except Exception as e:
            logger.error(f"保存素材到永久存储失败: {e}")

        # 更新状态为完成
        item["status"] = "completed"
        logger.info(f"✅ 融图打光任务 {item['id']} 完成！")

    except Exception as e:
        item["status"] = "error"
        item["error"] = str(e)
        logger.error(f"❌ 融图打光任务 {item['id']} 失败: {str(e)}")
        raise

def get_lighting_queue_status(queue_state):
    """获取融图打光队列状态（定时刷新）"""
    if queue_state is None:
        return queue_state, []
    return queue_state, render_lighting_queue_dataframe(queue_state)

def render_lighting_queue_dataframe(queue_state):
    """渲染融图打光队列为DataFrame数据"""
    if not queue_state:
        return []

    data = []
    for item in queue_state:
        # 状态显示逻辑
        status = item["status"]
        if status == "pending":
            status_display = "⏳ 等待中"
        elif status == "processing":
            start_time = item.get("start_time")
            if start_time:
                elapsed = time.time() - start_time
                remaining = 180 - elapsed  # 180秒 = 3分钟（融图打光可能需要更长时间）

                if remaining > 0:
                    minutes = int(remaining // 60)
                    seconds = int(remaining % 60)
                    status_display = f"预计还剩{minutes}:{seconds:02d}"
                else:
                    status_display = "全力处理中~"
            else:
                status_display = "🔄 处理中"
        elif status == "completed":
            status_display = "✅ 已完成"
        elif status == "error":
            status_display = "❌ 失败"
        else:
            status_display = "未知"

        # 操作列
        view_text = "点击查看" if status == "completed" else "---"

        data.append([
            item["id"],
            status_display,
            view_text
        ])

    return data

def handle_lighting_dataframe_click(evt: gr.SelectData, queue_state):
    """处理融图打光DataFrame点击事件"""
    if not queue_state or evt.index[0] >= len(queue_state):
        return None, None

    row_index = evt.index[0]
    item = queue_state[row_index]

    # 显示图片
    if item["status"] == "completed" and item["original"] and item["result"]:
        # 转换为PIL Image
        original_img = Image.open(io.BytesIO(item["original"]))
        result_img = Image.open(io.BytesIO(item["result"]))

        # 统一高度到800px
        target_height = 800

        # 调整原图大小
        orig_width, orig_height = original_img.size
        if orig_height != target_height:
            scale = target_height / orig_height
            new_width = int(orig_width * scale)
            original_img = original_img.resize((new_width, target_height), Image.LANCZOS)

        # 调整结果图大小
        result_width, result_height = result_img.size
        if result_height != target_height:
            scale = target_height / result_height
            new_width = int(result_width * scale)
            result_img = result_img.resize((new_width, target_height), Image.LANCZOS)

        # 保存为PNG临时文件
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix='_original.png', mode='wb') as f:
            original_img.save(f, format='PNG')
            original_temp_path = f.name

        with tempfile.NamedTemporaryFile(delete=False, suffix='_lighting.png', mode='wb') as f:
            result_img.save(f, format='PNG')
            result_temp_path = f.name

        return original_temp_path, result_temp_path

    return None, None

def clear_lighting_queue():
    """清空融图打光队列"""
    global lighting_queue_global
    lighting_queue_global = []
    return None, [], "✅ 队列已清空"

# --- 视频修复队列管理函数 ---
def add_video_restore_to_queue(files, queue_state):
    """添加视频文件到修复队列（自动触发）"""
    global video_restore_queue_global

    if not files:
        return None, queue_state, render_video_restore_queue_dataframe(queue_state), "⚠️ 未选择文件"

    # 初始化队列
    if queue_state is None:
        queue_state = []

    # 添加新文件到队列
    for file in files:
        file_id = str(uuid.uuid4())[:8]
        item = {
            "id": file_id,
            "file": file,
            "task_type": "video_restore",  # 标记为视频修复任务
            "status": "pending",
            "result_video": None,
            "error": None,
            "start_time": None
        }
        queue_state.append(item)
        video_restore_queue_global.append(item)

    # 启动后台处理
    start_video_processing()

    # 清空文件选择器并更新显示
    return None, queue_state, render_video_restore_queue_dataframe(queue_state), f"✅ 已添加 {len(files)} 个视频到队列，正在处理中..."

def process_video_restore_item_wrapper(item):
    """包装器：处理单个视频修复任务并更新活跃任务集"""
    global video_active_tasks

    try:
        process_video_restore_item(item)
    except Exception as e:
        logger.error(f"视频修复任务失败: {e}")
        item["status"] = "error"
        item["error"] = str(e)
    finally:
        # 任务完成后从活跃字典中移除（防止泄漏）
        with processing_lock:
            video_active_tasks.pop(item["id"], None)

        # 强制垃圾回收，及时释放内存（视频处理占用更多内存）
        gc.collect()

def process_video_restore_item(item):
    """处理单个视频修复任务"""
    try:
        # 更新状态为处理中，记录开始时间
        item["status"] = "processing"
        item["start_time"] = time.time()
        logger.info(f"📝 视频修复任务 {item['id']} 状态: pending -> processing")

        # 读取视频文件
        video_data = item["file"]

        # 上传视频文件
        logger.info(f"⬆️ 视频修复任务 {item['id']} 开始上传视频到API")
        uploaded_filename = upload_file_with_retry(video_data, f"input_{item['id']}.mp4", VIDEO_RESTORE_API_KEY)

        # 构建节点信息
        node_info_list = copy.deepcopy(VIDEO_RESTORE_NODE_INFO)
        for node in node_info_list:
            if node["nodeId"] == "36":
                node["fieldValue"] = uploaded_filename

        # 启动任务
        logger.info(f"🎬 视频修复任务 {item['id']} 提交API处理请求")
        task_id = run_task_with_retry(VIDEO_RESTORE_API_KEY, VIDEO_RESTORE_WEBAPP_ID, node_info_list, instance_type="plus")

        # 轮询状态
        poll_count = 0
        while poll_count < MAX_POLL_COUNT:
            time.sleep(POLL_INTERVAL)
            poll_count += 1
            status = get_task_status(VIDEO_RESTORE_API_KEY, task_id)

            if status == "SUCCESS":
                break
            elif status == "FAILED":
                raise Exception("API任务处理失败")

        if poll_count >= MAX_POLL_COUNT:
            raise Exception("任务超时")

        # 获取结果
        logger.info(f"⬇️ 视频修复任务 {item['id']} 开始下载结果")
        result_url = fetch_task_outputs(VIDEO_RESTORE_API_KEY, task_id, "video")
        result_data = download_result_image(result_url)  # 虽然函数名是image，但也可以下载视频

        # 保存视频文件
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='_restored.mp4', mode='wb') as f:
            f.write(result_data)
            item["result_video"] = f.name

        logger.info(f"💾 视频修复任务 {item['id']} 已保存为MP4格式")

        # 保存到永久存储
        try:
            save_material_to_storage(
                task_id=item["id"],
                task_type="video_restore",
                parameters={},
                original_data=None,  # 视频文件较大，不保存原始文件
                result_data_list=[(result_data, 'mp4')]
            )
        except Exception as e:
            logger.error(f"保存素材到永久存储失败: {e}")

        # 更新状态为完成
        item["status"] = "completed"
        logger.info(f"✅ 视频修复任务 {item['id']} 完成！")

    except Exception as e:
        item["status"] = "error"
        item["error"] = str(e)
        logger.error(f"❌ 视频修复任务 {item['id']} 失败: {str(e)}")
        raise

def get_video_restore_queue_status(queue_state):
    """获取视频修复队列状态（定时刷新）"""
    if queue_state is None:
        return queue_state, []
    return queue_state, render_video_restore_queue_dataframe(queue_state)

def render_video_restore_queue_dataframe(queue_state):
    """渲染视频修复队列为DataFrame数据"""
    if not queue_state:
        return []

    data = []
    for item in queue_state:
        # 状态显示逻辑
        status = item["status"]
        if status == "pending":
            status_display = "⏳ 等待中"
        elif status == "processing":
            start_time = item.get("start_time")
            if start_time:
                elapsed = time.time() - start_time
                remaining = 300 - elapsed  # 300秒 = 5分钟（视频处理时间较长）

                if remaining > 0:
                    minutes = int(remaining // 60)
                    seconds = int(remaining % 60)
                    status_display = f"预计还剩{minutes}:{seconds:02d}"
                else:
                    status_display = "全力处理中~"
            else:
                status_display = "🔄 处理中"
        elif status == "completed":
            status_display = "✅ 已完成"
        elif status == "error":
            status_display = "❌ 失败"
        else:
            status_display = "未知"

        # 操作列
        view_text = "点击查看" if status == "completed" else "---"

        data.append([
            item["id"],
            status_display,
            view_text
        ])

    return data

def handle_video_restore_dataframe_click(evt: gr.SelectData, queue_state):
    """处理视频修复DataFrame点击事件"""
    if not queue_state or evt.index[0] >= len(queue_state):
        return None

    row_index = evt.index[0]
    item = queue_state[row_index]

    # 显示视频
    if item["status"] == "completed" and item["result_video"]:
        return item["result_video"]

    return None

def clear_video_restore_queue():
    """清空视频修复队列"""
    global video_restore_queue_global
    video_restore_queue_global = []
    return None, [], [], "✅ 队列已清空"

# --- 生成素材管理函数 ---
def get_materials(task_type_filter="全部", date_filter="全部", search_query="", limit=20, offset=0):
    """
    获取素材列表（支持分批加载）

    Args:
        task_type_filter: 类型筛选
        date_filter: 日期筛选
        search_query: 搜索关键词
        limit: 每批返回记录数（默认20）
        offset: 偏移量（用于分批加载）
    """
    try:
        conn = sqlite3.connect(MATERIALS_DB_PATH)
        cursor = conn.cursor()

        # 构建查询
        query = "SELECT id, task_type, created_at, parameters, thumbnail_path, result_paths FROM materials WHERE 1=1"
        params = []

        # 类型筛选
        if task_type_filter != "全部":
            task_type_map = {
                "图像优化": "image_enhance",
                "去水印": "watermark_removal",
                "融图打光": "lighting",
                "姿态迁移": "pose_transfer",
                "视频修复": "video_restore"
            }
            query += " AND task_type = ?"
            params.append(task_type_map[task_type_filter])

        # 日期筛选
        if date_filter == "今天":
            cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            query += " AND created_at >= ?"
            params.append(cutoff.isoformat())
        elif date_filter == "最近7天":
            cutoff = datetime.now() - timedelta(days=7)
            query += " AND created_at >= ?"
            params.append(cutoff.isoformat())
        elif date_filter == "最近30天":
            cutoff = datetime.now() - timedelta(days=30)
            query += " AND created_at >= ?"
            params.append(cutoff.isoformat())

        # 搜索查询
        if search_query:
            query += " AND id LIKE ?"
            params.append(f"%{search_query}%")

        query += f" ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}"

        cursor.execute(query, params)
        materials = cursor.fetchall()
        conn.close()

        return materials

    except Exception as e:
        logger.error(f"查询素材失败: {e}")
        return []

def get_materials_count(task_type_filter="全部", date_filter="全部", search_query=""):
    """获取符合条件的素材总数"""
    try:
        conn = sqlite3.connect(MATERIALS_DB_PATH)
        cursor = conn.cursor()

        # 构建查询
        query = "SELECT COUNT(*) FROM materials WHERE 1=1"
        params = []

        # 类型筛选
        if task_type_filter != "全部":
            task_type_map = {
                "图像优化": "image_enhance",
                "去水印": "watermark_removal",
                "融图打光": "lighting",
                "姿态迁移": "pose_transfer",
                "视频修复": "video_restore"
            }
            query += " AND task_type = ?"
            params.append(task_type_map[task_type_filter])

        # 日期筛选
        if date_filter == "今天":
            cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            query += " AND created_at >= ?"
            params.append(cutoff.isoformat())
        elif date_filter == "最近7天":
            cutoff = datetime.now() - timedelta(days=7)
            query += " AND created_at >= ?"
            params.append(cutoff.isoformat())
        elif date_filter == "最近30天":
            cutoff = datetime.now() - timedelta(days=30)
            query += " AND created_at >= ?"
            params.append(cutoff.isoformat())

        # 搜索查询
        if search_query:
            query += " AND id LIKE ?"
            params.append(f"%{search_query}%")

        cursor.execute(query, params)
        count = cursor.fetchone()[0]
        conn.close()

        return count

    except Exception as e:
        logger.error(f"查询素材总数失败: {e}")
        return 0

def render_materials_gallery(materials):
    """渲染素材为Gallery格式"""
    gallery_data = []

    task_type_display = {
        "image_enhance": "图像优化",
        "watermark_removal": "去水印",
        "lighting": "融图打光",
        "pose_transfer": "姿态迁移",
        "video_restore": "视频修复"
    }

    for material in materials:
        material_id, task_type, created_at, parameters_json, thumbnail_path, result_paths_json = material

        # 使用缩略图或第一个结果文件
        if thumbnail_path and os.path.exists(thumbnail_path):
            image_path = thumbnail_path
        else:
            result_paths = json.loads(result_paths_json)
            if result_paths and os.path.exists(result_paths[0]):
                image_path = result_paths[0]
            else:
                continue  # 跳过没有图片的素材

        # 创建标签
        created_time = datetime.fromisoformat(created_at).strftime("%Y-%m-%d %H:%M")
        type_label = task_type_display.get(task_type, task_type)
        caption = f"{type_label} | {created_time}\nID: {material_id}"

        gallery_data.append((image_path, caption))

    return gallery_data

def get_material_details(material_id):
    """获取资产详情"""
    try:
        conn = sqlite3.connect(MATERIALS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, task_type, created_at, parameters, original_path, result_paths, file_size
            FROM materials WHERE id = ?
        ''', (material_id,))
        material = cursor.fetchone()
        conn.close()

        if material:
            material_id, task_type, created_at, parameters_json, original_path, result_paths_json, file_size = material

            task_type_display = {
                "image_enhance": "图像优化",
                "watermark_removal": "去水印",
                "pose_transfer": "姿态迁移",
                "video_restore": "视频修复"
            }

            parameters = json.loads(parameters_json) if parameters_json else {}
            result_paths = json.loads(result_paths_json)

            # 格式化信息
            info = f"""
**资产ID:** {material_id}
**类型:** {task_type_display.get(task_type, task_type)}
**创建时间:** {datetime.fromisoformat(created_at).strftime("%Y-%m-%d %H:%M:%S")}
**文件大小:** {file_size / 1024 / 1024:.2f} MB
**参数:** {json.dumps(parameters, ensure_ascii=False, indent=2)}
**结果文件数量:** {len(result_paths)}
"""

            # 返回结果文件路径用于预览
            preview_paths = result_paths if task_type != "video_restore" else result_paths

            return info, original_path if original_path and os.path.exists(original_path) else None, preview_paths

    except Exception as e:
        logger.error(f"获取资产详情失败: {e}")

    return "未找到资产", None, []

def delete_material(material_id):
    """删除资产"""
    try:
        conn = sqlite3.connect(MATERIALS_DB_PATH)
        cursor = conn.cursor()

        # 获取文件路径
        cursor.execute('SELECT original_path, result_paths, thumbnail_path FROM materials WHERE id = ?', (material_id,))
        result = cursor.fetchone()

        if result:
            original_path, result_paths_json, thumbnail_path = result

            # 删除文件
            if original_path and os.path.exists(original_path):
                os.remove(original_path)

            result_paths = json.loads(result_paths_json)
            for path in result_paths:
                if os.path.exists(path):
                    os.remove(path)

            if thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)

            # 从数据库删除
            cursor.execute('DELETE FROM materials WHERE id = ?', (material_id,))
            conn.commit()
            conn.close()

            logger.info(f"🗑️ 已删除资产: {material_id}")
            return True, f"✅ 已删除资产 {material_id}"

    except Exception as e:
        logger.error(f"删除资产失败: {e}")
        return False, f"❌ 删除失败: {str(e)}"

    return False, "❌ 未找到资产"

# --- Gradio界面 ---
def create_interface():
    # 自定义CSS（优化版：简化样式以加快加载）
    custom_css = """
    /* 优化加载性能 - 使用GPU加速 */
    * {
        will-change: auto;
    }
    /* 下载按钮放大效果 */
    .image-frame button[title*="Download"] {
        transform: scale(1.3);
        transform: translateZ(0);  /* GPU加速 */
    }
    .image-frame button[title*="Download"]:hover {
        transform: scale(1.5);
    }
    """

    with gr.Blocks(title="RunningHub AI - 智能图片处理工具", theme=gr.themes.Soft(), css=custom_css) as demo:
        gr.Markdown("""
        # 🎨 RunningHub AI - 智能图片处理工具

        专业的AI图像优化服务，支持多种风格转换
        """)

        with gr.Tabs():
            # 图像优化（第一栏 - 队列上传 - 自动处理 + DataFrame列表）
            with gr.Tab("🎨 图像优化"):
                with gr.Row():
                    # 左侧：上传和控制区（缩小占比）
                    with gr.Column(scale=1):
                        gr.Markdown("### 📤 上传图片")
                        gr.Markdown("*拖拽或点击选择，自动进入队列*")
                        enhance_version = gr.Radio(
                            choices=["WAN 2.2", "WAN 2.1"],
                            value="WAN 2.2",
                            label="模型版本"
                        )
                        enhance_style = gr.Radio(
                            choices=["默认", "写实", "3D卡通"],
                            value="默认",
                            label="风格"
                        )
                        gr.Markdown("💡 **建议**：单张图片不超过10MB，支持JPG/PNG格式")
                        enhance_files = gr.File(
                            label="选择图片（支持多选）",
                            file_count="multiple",
                            file_types=["image"],
                            type="binary"
                        )
                        clear_btn = gr.Button("🗑️ 清空队列", size="sm")

                        gr.Markdown("---")
                        enhance_status = gr.Textbox(label="状态", interactive=False, lines=2)

                    # 右侧：队列展示区
                    with gr.Column(scale=4):
                        gr.Markdown("### 📊 处理队列")
                        queue_display = gr.Dataframe(
                            headers=["ID", "状态", "模型", "风格", "操作"],
                            datatype=["str", "str", "str", "str", "str"],
                            label="队列列表（点击行查看详情）",
                            interactive=False
                        )

                        gr.Markdown("#### 🖼️ 图片查看（点击列表行查看，Tabs切换对比）")
                        with gr.Tabs():
                            with gr.Tab("📷 原图"):
                                enhance_original = gr.Image(label="原图", show_label=False, height=600, type="filepath")
                            with gr.Tab("🎨 优化后"):
                                enhance_enhanced = gr.Image(label="优化后", show_label=False, height=600, show_download_button=True, type="filepath")

                # 隐藏的队列状态
                queue_state = gr.State(value=None)

                # 自动处理：文件上传时自动添加到队列
                enhance_files.upload(
                    fn=add_to_queue,
                    inputs=[enhance_files, enhance_version, enhance_style, queue_state],
                    outputs=[enhance_files, queue_state, queue_display, enhance_status]
                )

                # 点击列表行显示图片
                queue_display.select(
                    fn=handle_dataframe_click,
                    inputs=[queue_state],
                    outputs=[enhance_original, enhance_enhanced]
                )

                # 清空队列
                clear_btn.click(
                    fn=clear_queue,
                    outputs=[queue_state, queue_display, enhance_status]
                )

                # 定时刷新队列显示（使用UI_REFRESH_INTERVAL优化性能）
                timer = gr.Timer(value=UI_REFRESH_INTERVAL, active=True)
                timer.tick(
                    fn=get_queue_status,
                    inputs=[queue_state],
                    outputs=[queue_state, queue_display]
                )

            # 去水印（第二栏 - 队列处理）
            with gr.Tab("🚿 去水印"):
                with gr.Row():
                    # 左侧：上传和控制区
                    with gr.Column(scale=1):
                        gr.Markdown("### 📤 上传图片")
                        gr.Markdown("*拖拽或点击选择，自动进入队列*")
                        gr.Markdown("💡 **建议**：单张图片不超过10MB，支持JPG/PNG格式")
                        watermark_files = gr.File(
                            label="选择图片（支持多选）",
                            file_count="multiple",
                            file_types=["image"],
                            type="binary"
                        )
                        clear_watermark_btn = gr.Button("🗑️ 清空队列", size="sm")

                        gr.Markdown("---")
                        watermark_status = gr.Textbox(label="状态", interactive=False, lines=2)

                    # 右侧：队列展示区
                    with gr.Column(scale=4):
                        gr.Markdown("### 📊 处理队列")
                        watermark_queue_display = gr.Dataframe(
                            headers=["ID", "状态", "操作"],
                            datatype=["str", "str", "str"],
                            label="队列列表（点击行查看详情）",
                            interactive=False
                        )

                        gr.Markdown("#### 🖼️ 图片查看（点击列表行查看，Tabs切换对比）")
                        with gr.Tabs():
                            with gr.Tab("📷 原图"):
                                watermark_original = gr.Image(label="原图", show_label=False, height=600, type="filepath")
                            with gr.Tab("✨ 去水印后"):
                                watermark_result = gr.Image(label="去水印后", show_label=False, height=600, show_download_button=True, type="filepath")

                # 隐藏的队列状态
                watermark_queue_state = gr.State(value=None)

                # 自动处理：文件上传时自动添加到队列
                watermark_files.upload(
                    fn=add_watermark_to_queue,
                    inputs=[watermark_files, watermark_queue_state],
                    outputs=[watermark_files, watermark_queue_state, watermark_queue_display, watermark_status]
                )

                # 点击列表行显示图片
                watermark_queue_display.select(
                    fn=handle_watermark_dataframe_click,
                    inputs=[watermark_queue_state],
                    outputs=[watermark_original, watermark_result]
                )

                # 清空队列
                clear_watermark_btn.click(
                    fn=clear_watermark_queue,
                    outputs=[watermark_queue_state, watermark_queue_display, watermark_status]
                )

                # 定时刷新队列显示（使用UI_REFRESH_INTERVAL优化性能）
                watermark_timer = gr.Timer(value=UI_REFRESH_INTERVAL, active=True)
                watermark_timer.tick(
                    fn=get_watermark_queue_status,
                    inputs=[watermark_queue_state],
                    outputs=[watermark_queue_state, watermark_queue_display]
                )

            # 融图打光（第三栏 - 队列处理）
            with gr.Tab("💡 融图打光"):
                with gr.Row():
                    # 左侧：上传和控制区
                    with gr.Column(scale=1):
                        gr.Markdown("### 📤 上传图片")
                        gr.Markdown("*拖拽或点击选择，自动进入队列*")
                        gr.Markdown("💡 **建议**：单张图片不超过10MB，支持JPG/PNG格式")
                        lighting_files = gr.File(
                            label="选择图片（支持多选）",
                            file_count="multiple",
                            file_types=["image"],
                            type="binary"
                        )
                        clear_lighting_btn = gr.Button("🗑️ 清空队列", size="sm")

                        gr.Markdown("---")
                        lighting_status = gr.Textbox(label="状态", interactive=False, lines=2)

                    # 右侧：队列展示区
                    with gr.Column(scale=4):
                        gr.Markdown("### 📊 处理队列")
                        lighting_queue_display = gr.Dataframe(
                            headers=["ID", "状态", "操作"],
                            datatype=["str", "str", "str"],
                            label="队列列表（点击行查看详情）",
                            interactive=False
                        )

                        gr.Markdown("#### 🖼️ 图片查看（点击列表行查看，Tabs切换对比）")
                        with gr.Tabs():
                            with gr.Tab("📷 原图"):
                                lighting_original = gr.Image(label="原图", show_label=False, height=600, type="filepath")
                            with gr.Tab("✨ 打光后"):
                                lighting_result = gr.Image(label="打光后", show_label=False, height=600, show_download_button=True, type="filepath")

                # 隐藏的队列状态
                lighting_queue_state = gr.State(value=None)

                # 自动处理：文件上传时自动添加到队列
                lighting_files.upload(
                    fn=add_lighting_to_queue,
                    inputs=[lighting_files, lighting_queue_state],
                    outputs=[lighting_files, lighting_queue_state, lighting_queue_display, lighting_status]
                )

                # 点击列表行显示图片
                lighting_queue_display.select(
                    fn=handle_lighting_dataframe_click,
                    inputs=[lighting_queue_state],
                    outputs=[lighting_original, lighting_result]
                )

                # 清空队列
                clear_lighting_btn.click(
                    fn=clear_lighting_queue,
                    outputs=[lighting_queue_state, lighting_queue_display, lighting_status]
                )

                # 定时刷新队列显示（使用UI_REFRESH_INTERVAL优化性能）
                lighting_timer = gr.Timer(value=UI_REFRESH_INTERVAL, active=True)
                lighting_timer.tick(
                    fn=get_lighting_queue_status,
                    inputs=[lighting_queue_state],
                    outputs=[lighting_queue_state, lighting_queue_display]
                )

            # 姿态迁移（第四栏 - 队列处理）
            with gr.Tab("🎭 姿态迁移"):
                with gr.Row():
                    # 左侧：上传和控制区
                    with gr.Column(scale=1):
                        gr.Markdown("### 📤 上传图片")
                        gr.Markdown("*分别上传角色图和姿态图，点击开始处理按钮*")
                        gr.Markdown("💡 **建议**：单张图片不超过10MB")

                        pose_character_files = gr.File(
                            label="角色图（支持多选）",
                            file_count="multiple",
                            file_types=["image"],
                            type="binary"
                        )

                        pose_pose_files = gr.File(
                            label="姿态图（支持多选）",
                            file_count="multiple",
                            file_types=["image"],
                            type="binary"
                        )

                        pose_strength = gr.Slider(
                            minimum=4,
                            maximum=15,
                            value=4,
                            step=1,
                            label="强度值 (4=角色相似度 ←→ 15=姿态相似度)"
                        )

                        # 开始处理按钮
                        start_pose_btn = gr.Button("🚀 开始处理", variant="primary", size="lg")

                        clear_pose_btn = gr.Button("🗑️ 清空队列", size="sm")

                        gr.Markdown("---")
                        pose_status = gr.Textbox(label="状态", interactive=False, lines=2)

                    # 右侧：队列展示区
                    with gr.Column(scale=4):
                        gr.Markdown("### 📊 处理队列")
                        pose_queue_display = gr.Dataframe(
                            headers=["ID", "状态", "强度", "操作"],
                            datatype=["str", "str", "str", "str"],
                            label="队列列表（点击行查看详情）",
                            interactive=False
                        )

                        gr.Markdown("#### 🖼️ 结果查看（点击列表行查看）")
                        with gr.Row():
                            pose_result_1 = gr.Image(label="结果图 1", show_label=True, height=600, show_download_button=True, type="filepath")
                            pose_result_2 = gr.Image(label="结果图 2", show_label=True, height=600, show_download_button=True, type="filepath")

                # 隐藏的队列状态
                pose_queue_state = gr.State(value=None)

                # 点击"开始处理"按钮触发
                start_pose_btn.click(
                    fn=add_pose_to_queue,
                    inputs=[pose_character_files, pose_pose_files, pose_strength, pose_queue_state],
                    outputs=[pose_character_files, pose_pose_files, pose_queue_state, pose_queue_display, pose_status]
                )

                # 点击列表行显示图片
                pose_queue_display.select(
                    fn=handle_pose_dataframe_click,
                    inputs=[pose_queue_state],
                    outputs=[pose_result_1, pose_result_2]
                )

                # 清空队列
                clear_pose_btn.click(
                    fn=clear_pose_queue,
                    outputs=[pose_character_files, pose_pose_files, pose_queue_state, pose_queue_display, pose_status]
                )

                # 定时刷新队列显示（使用UI_REFRESH_INTERVAL优化性能）
                pose_timer = gr.Timer(value=UI_REFRESH_INTERVAL, active=True)
                pose_timer.tick(
                    fn=get_pose_queue_status,
                    inputs=[pose_queue_state],
                    outputs=[pose_queue_state, pose_queue_display]
                )

            # 视频修复（第四栏 - 队列处理）
            with gr.Tab("🎬 视频修复"):
                with gr.Row():
                    # 左侧：上传和控制区
                    with gr.Column(scale=1):
                        gr.Markdown("### 📤 上传视频")
                        gr.Markdown("*拖拽或点击选择，自动进入队列*")
                        gr.Markdown("💡 **建议**：单个视频不超过50MB，处理较大视频可能需要较长时间")
                        video_restore_files = gr.File(
                            label="选择视频（支持多选）",
                            file_count="multiple",
                            file_types=["video"],
                            type="binary"
                        )
                        clear_video_btn = gr.Button("🗑️ 清空队列", size="sm")

                        gr.Markdown("---")
                        video_restore_status = gr.Textbox(label="状态", interactive=False, lines=2)

                    # 右侧：队列展示区
                    with gr.Column(scale=4):
                        gr.Markdown("### 📊 处理队列")
                        video_restore_queue_display = gr.Dataframe(
                            headers=["ID", "状态", "操作"],
                            datatype=["str", "str", "str"],
                            label="队列列表（点击行查看详情）",
                            interactive=False
                        )

                        gr.Markdown("#### 🎥 视频预览（点击列表行查看）")
                        video_restore_result = gr.Video(label="修复后的视频", show_label=True, height=600)

                # 隐藏的队列状态
                video_restore_queue_state = gr.State(value=None)

                # 自动处理：文件上传时自动添加到队列
                video_restore_files.upload(
                    fn=add_video_restore_to_queue,
                    inputs=[video_restore_files, video_restore_queue_state],
                    outputs=[video_restore_files, video_restore_queue_state, video_restore_queue_display, video_restore_status]
                )

                # 点击列表行显示视频
                video_restore_queue_display.select(
                    fn=handle_video_restore_dataframe_click,
                    inputs=[video_restore_queue_state],
                    outputs=[video_restore_result]
                )

                # 清空队列
                clear_video_btn.click(
                    fn=clear_video_restore_queue,
                    outputs=[video_restore_files, video_restore_queue_state, video_restore_queue_display, video_restore_status]
                )

                # 定时刷新队列显示（使用UI_REFRESH_INTERVAL优化性能）
                video_restore_timer = gr.Timer(value=UI_REFRESH_INTERVAL, active=True)
                video_restore_timer.tick(
                    fn=get_video_restore_queue_status,
                    inputs=[video_restore_queue_state],
                    outputs=[video_restore_queue_state, video_restore_queue_display]
                )

            # 资产管理（第五栏）
            with gr.Tab("📦 资产管理"):
                gr.Markdown("### 🗂️ 资产库")
                gr.Markdown("💡 **提示**：点击「🔄 刷新」加载资产，点击「⬇️ 加载更多」查看更多资产")

                with gr.Row():
                    # 左侧：筛选和资产库
                    with gr.Column(scale=3):
                        # 筛选控制栏
                        with gr.Row():
                            materials_type_filter = gr.Dropdown(
                                choices=["全部", "图像优化", "去水印", "融图打光", "姿态迁移", "视频修复"],
                                value="全部",
                                label="类型筛选",
                                scale=1
                            )
                            materials_date_filter = gr.Dropdown(
                                choices=["全部", "今天", "最近7天", "最近30天"],
                                value="全部",
                                label="日期筛选",
                                scale=1
                            )
                            materials_search = gr.Textbox(
                                label="搜索ID",
                                placeholder="输入资产ID搜索...",
                                scale=2
                            )
                            materials_refresh_btn = gr.Button("🔄 刷新", size="sm", scale=0)

                        # 资产展示Gallery（卡片式布局 - 优化加载速度）
                        materials_gallery = gr.Gallery(
                            label="资产库",
                            show_label=False,
                            columns=4,
                            rows=3,  # 从4行减少到3行，加快初始渲染
                            height=600,  # 相应调整高度
                            object_fit="cover",
                            show_download_button=False
                        )

                        # 加载更多按钮和状态显示
                        with gr.Row():
                            materials_load_more_btn = gr.Button("⬇️ 加载更多 (每次20个)", variant="secondary", size="lg")
                            materials_count_display = gr.Markdown("*已加载: 0 / 总计: 0*")

                    # 右侧：资产详情
                    with gr.Column(scale=2):
                        gr.Markdown("### 📋 资产详情")

                        # 选中的资产ID（隐藏）
                        selected_material_id = gr.State(value=None)

                        material_info = gr.Markdown("*点击左侧资产查看详情*")

                        gr.Markdown("---")

                        # 图片预览
                        material_result_1 = gr.Image(label="结果 1", show_label=True, height=350, type="filepath", show_download_button=False)
                        material_result_2 = gr.Image(label="结果 2", show_label=True, height=350, type="filepath", visible=False, show_download_button=False)

                        # 视频预览
                        material_video = gr.Video(label="结果视频", show_label=True, height=400, visible=False)

                        gr.Markdown("---")

                        # 操作按钮
                        with gr.Row():
                            material_download_btn = gr.Button("📥 下载原图PNG", variant="primary", size="lg", visible=False)
                            material_delete_btn = gr.Button("🗑️ 删除", variant="stop", size="lg")

                        material_download_file = gr.File(label="下载文件", visible=False)
                        material_delete_status = gr.Textbox(label="状态", interactive=False, visible=False)

                # 隐藏的状态变量
                materials_offset = gr.State(value=0)  # 当前加载的偏移量
                materials_current_data = gr.State(value=[])  # 当前已加载的数据

                # 加载资产列表的函数（刷新 - 重新从头加载）
                def load_materials_list(type_filter, date_filter, search_query):
                    """刷新资产列表，从头开始加载"""
                    materials = get_materials(type_filter, date_filter, search_query, limit=20, offset=0)
                    gallery_data = render_materials_gallery(materials)
                    total_count = get_materials_count(type_filter, date_filter, search_query)
                    loaded_count = len(gallery_data)
                    count_text = f"*已加载: {loaded_count} / 总计: {total_count}*"

                    return gallery_data, 20, gallery_data, count_text  # gallery, new_offset, current_data, count_display

                # 加载更多资产的函数
                def load_more_materials(type_filter, date_filter, search_query, current_offset, current_data):
                    """加载更多资产，追加到现有列表"""
                    materials = get_materials(type_filter, date_filter, search_query, limit=20, offset=current_offset)
                    new_gallery_data = render_materials_gallery(materials)

                    # 合并新数据到现有数据
                    updated_data = current_data + new_gallery_data

                    total_count = get_materials_count(type_filter, date_filter, search_query)
                    loaded_count = len(updated_data)
                    count_text = f"*已加载: {loaded_count} / 总计: {total_count}*"

                    new_offset = current_offset + 20

                    return updated_data, new_offset, updated_data, count_text  # gallery, new_offset, current_data, count_display

                # 查看资产详情的函数
                def view_material_detail(evt: gr.SelectData, gallery_data):
                    if not gallery_data or evt.index >= len(gallery_data):
                        return None, "未选择资产", None, None, gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)

                    # 从caption中提取ID
                    caption = gallery_data[evt.index][1]
                    material_id = caption.split("ID: ")[1].strip() if "ID: " in caption else None

                    if not material_id:
                        return None, "无法获取资产ID", None, None, gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)

                    # 获取详情
                    info, original_path, result_paths = get_material_details(material_id)

                    # 判断是否为视频
                    is_video = len(result_paths) > 0 and result_paths[0].endswith('.mp4')

                    if is_video:
                        # 视频资产
                        return (
                            material_id,
                            info,
                            None,
                            None,
                            gr.update(visible=False),
                            gr.update(visible=False),
                            gr.update(value=result_paths[0] if result_paths else None, visible=True),
                            gr.update(visible=False)  # 视频不显示下载原图按钮
                        )
                    else:
                        # 图片资产
                        result_1 = result_paths[0] if len(result_paths) > 0 else None
                        result_2 = result_paths[1] if len(result_paths) > 1 else None

                        return (
                            material_id,
                            info,
                            result_1,
                            result_2,
                            gr.update(visible=True),
                            gr.update(visible=True if result_2 else False),
                            gr.update(visible=False),
                            gr.update(visible=True)  # 图片显示下载按钮
                        )

                # 下载原图PNG的函数
                def download_original_png(material_id):
                    if not material_id:
                        return gr.update(visible=False)

                    try:
                        conn = sqlite3.connect(MATERIALS_DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute('SELECT result_paths FROM materials WHERE id = ?', (material_id,))
                        result = cursor.fetchone()
                        conn.close()

                        if result:
                            result_paths = json.loads(result[0])
                            # 返回第一个结果文件（原图PNG）
                            if result_paths and os.path.exists(result_paths[0]):
                                return gr.update(value=result_paths[0], visible=True)

                    except Exception as e:
                        logger.error(f"下载原图失败: {e}")

                    return gr.update(visible=False)

                # 删除资产的函数
                def delete_selected_material(material_id, type_filter, date_filter, search_query):
                    if not material_id:
                        return gr.update(value="⚠️ 未选择资产", visible=True), None, 0, [], "*已加载: 0 / 总计: 0*"

                    success, message = delete_material(material_id)

                    # 刷新列表（返回值：gallery, offset, current_data, count_text）
                    gallery, offset, current_data, count_text = load_materials_list(type_filter, date_filter, search_query)

                    return gr.update(value=message, visible=True), gallery, offset, current_data, count_text

                # 移除自动加载以优化页面初始加载速度
                # 资产管理改为懒加载：仅在用户首次点击刷新按钮或筛选时才加载
                # demo.load(...) 已移除

                # 筛选和刷新（重新从头加载）
                materials_type_filter.change(
                    fn=load_materials_list,
                    inputs=[materials_type_filter, materials_date_filter, materials_search],
                    outputs=[materials_gallery, materials_offset, materials_current_data, materials_count_display]
                )

                materials_date_filter.change(
                    fn=load_materials_list,
                    inputs=[materials_type_filter, materials_date_filter, materials_search],
                    outputs=[materials_gallery, materials_offset, materials_current_data, materials_count_display]
                )

                materials_search.submit(
                    fn=load_materials_list,
                    inputs=[materials_type_filter, materials_date_filter, materials_search],
                    outputs=[materials_gallery, materials_offset, materials_current_data, materials_count_display]
                )

                materials_refresh_btn.click(
                    fn=load_materials_list,
                    inputs=[materials_type_filter, materials_date_filter, materials_search],
                    outputs=[materials_gallery, materials_offset, materials_current_data, materials_count_display]
                )

                # 加载更多按钮
                materials_load_more_btn.click(
                    fn=load_more_materials,
                    inputs=[materials_type_filter, materials_date_filter, materials_search, materials_offset, materials_current_data],
                    outputs=[materials_gallery, materials_offset, materials_current_data, materials_count_display]
                )

                # 点击Gallery查看详情
                materials_gallery.select(
                    fn=view_material_detail,
                    inputs=[materials_gallery],
                    outputs=[selected_material_id, material_info, material_result_1, material_result_2, material_result_1, material_result_2, material_video, material_download_btn]
                )

                # 下载原图PNG
                material_download_btn.click(
                    fn=download_original_png,
                    inputs=[selected_material_id],
                    outputs=[material_download_file]
                )

                # 删除资产
                material_delete_btn.click(
                    fn=delete_selected_material,
                    inputs=[selected_material_id, materials_type_filter, materials_date_filter, materials_search],
                    outputs=[material_delete_status, materials_gallery, materials_offset, materials_current_data, materials_count_display]
                )

    return demo

if __name__ == "__main__":
    # 初始化素材存储系统
    logger.info("🔧 正在初始化素材存储系统...")
    init_materials_storage()

    # 启动定期清理调度器
    start_cleanup_scheduler()

    # 创建界面
    demo = create_interface()

    # 配置队列系统以优化并发处理
    demo.queue(
        max_size=100,  # 最大队列长度
        default_concurrency_limit=20  # 默认并发限制
    )

    # 启动服务
    demo.launch(
        server_name="0.0.0.0",
        server_port=7870,  # 测试端口
        share=False,
        allowed_paths=[MATERIALS_BASE_DIR],  # 允许访问素材目录
        max_file_size="50mb",  # 最大文件大小限制
        show_api=False  # 关闭API文档以减少开销
    )
