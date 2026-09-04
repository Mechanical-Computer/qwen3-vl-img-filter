import os
import asyncio
import aiohttp
import argparse
from pathlib import Path
import sys
from PIL import Image
import io
from collections import defaultdict
import csv
from itertools import count

# ========== 配置 ==========
VLLM_URL = "http://127.0.0.1:8000/v1/chat/completions"
MODEL_NAME = "./Qwen3-VL-32B-Instruct-FP8"
PROMPT = "请先分析图像中的以下要素：天空颜色与亮度、远景清晰度、地面状态（干/湿/反光类型）、是否有光源眩光？然后综合判断是否有真实雨雾。仅输出“有”或“无”。"
MAX_TOKENS = 5
CONCURRENT_REQUESTS = 16
TIMEOUT_SEC = 30
OUTPUT_FILE = "rain_or_fog_images.txt"
ERROR_LOG = "processing_errors.log"
MAX_IMAGE_SIZE = 1024

# ========== 需要遍历的相机视角 CAMERA_SET ==========
CAMERA_SET = {
    'CAM_FRONT_MIDDLE', 'CAM_FRONT_LEFT', 'CAM_LEFT_FRONT',
    'CAM_RIGHT_BACK', 'CAM_RIGHT_FRONT', 'CAM_LEFT_BACK',
    'CAM_FRONT_RIGHT', 'CAM_REAR_MID'
}

# 全局统计
SCENE_STATS: dict[str, dict[str, list[bool]]] = defaultdict(lambda: {c: [] for c in CAMERA_SET})
task_queue = asyncio.Queue(maxsize=CONCURRENT_REQUESTS)
_progress = count(1)


async def query_vlm(session, image_path: str) -> bool:
    """向 vLLM 发送请求，返回是否包含雨/雾"""
    try:
        img = Image.open(image_path)
        width, height = img.size
        # 如果图片尺寸超过 MAX_IMAGE_SIZE，则进行缩放处理
        if width > MAX_IMAGE_SIZE or height > MAX_IMAGE_SIZE:
            img.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE), Image.Resampling.LANCZOS)
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG', quality=95)
            img_byte_arr = img_byte_arr.getvalue()
            import base64 # 将内存中的图片转换为 base64 编码，大图片经过处理在内存，不在本地
            encoded = base64.b64encode(img_byte_arr).decode('utf-8')
            url = f"data:image/jpeg;base64,{encoded}"
        else:
            url = f"file://{os.path.abspath(image_path)}"

    except Exception as e:
        print(f"\n🖼️ 图片处理失败 {image_path}: {e}")
        return False

    payload = {
        "model": MODEL_NAME,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": url}}
            ]
        }],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.0
    }

    try:
        async with session.post(VLLM_URL, json=payload, timeout=aiohttp.ClientTimeout(total=TIMEOUT_SEC)) as resp:
            if resp.status == 200:
                data = await resp.json()
                answer = data["choices"][0]["message"]["content"].strip()
                return "有" in answer
            else:
                error_text = await resp.text()
                print(f"\n❌ HTTP {resp.status} for {image_path}: {error_text[:50]}...")
                return False
    except Exception as e:
        print(f"\n⚠️ 请求失败 {image_path}: {str(e)}")
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{image_path}\t{str(e)}\n")
        return False


async def worker(worker_id: int, task_queue: asyncio.Queue, output_file, session: aiohttp.ClientSession):
    """工作协程：处理任务，将正样本写入文件，更新全局统计"""
    print(f"👷 启动工作协程 {worker_id}")
    
    while True:
        item = await task_queue.get()
        
        if item is None:
            task_queue.task_done()
            break
            
        img_path, cam_name, scene_root = item
        
        try:
            is_positive = await query_vlm(session, img_path)
            
            # 更新全局统计数据
            SCENE_STATS[scene_root][cam_name].append(is_positive)
            
            # 如果是正样本，写入结果文件
            if is_positive:
                output_file.write(img_path + "\n")
                output_file.flush()
            
            # 进度日志
            n = next(_progress)
            if n % 200 == 0:
                print(f"\r📊 已处理 {n} 张", end="", flush=True)
                
        except Exception as e:
            print(f"\nWorker {worker_id} error on {img_path}: {e}")
        finally:
            task_queue.task_done()
            
    print(f"\n👋 工作协程 {worker_id} 结束")


def find_samples_directories(root_path: Path):
    """
    递归查找所有包含 'samples_third_ann_data' 的目录。
    遍历逻辑：
    1. 递归搜索，直到找到名为 'samples_third_ann_data' 的文件夹。
    2. 检查该文件夹的父目录是否包含 'rino-'。
    3. 如果是，则记录该 'samples_third_ann_data' 目录的路径。
    4. 遇到 'backup' 文件夹则跳过，不再进入。
    """
    print(f"🔍 开始在 {root_path} 中查找 samples_third_ann_data 目录...")
    samples_dirs = []
    
    for dirpath, dirnames, filenames in os.walk(root_path):
        # 检查当前路径是否包含 'backup'，如果是，则清空 dirnames，停止向下遍历
        if 'backup' in dirpath:
            dirnames[:] = []  # 清空子目录列表，阻止 os.walk 进入
            continue
            
        # 检查当前目录是否是 'samples_third_ann_data'
        if os.path.basename(dirpath) == 'samples_third_ann_data':
            parent_dir = Path(dirpath).parent
            if 'rino-' in parent_dir.name:
                print(f"📁 找到目标目录: {dirpath}")
                samples_dirs.append(Path(dirpath))
            # 如果是 samples_third_ann_data 但不是 rino-xxx 的子目录，也跳过它
            # (虽然不太可能，但以防万一)
            dirnames[:] = []

    print(f"✅ 找到 {len(samples_dirs)} 个符合条件的 samples_third_ann_data 目录。")
    return samples_dirs


def scan_camera_jpg_from_samples_dirs(samples_dirs):
    """
    从找到的 samples_third_ann_data 目录列表开始扫描。
    遍历每个 samples_third_ann_data 目录下的所有 clip 子目录及其相机文件夹，产出图片路径。
    """
    count = 0
    print("🔍 开始扫描相机图片...")

    for samples_root in samples_dirs:
        print(f"   扫描 samples_third_ann_data 目录: {samples_root}")

        # 检查 samples_third_ann_data 目录是否存在
        if not samples_root.exists():
            print(f"   ❌ 错误: {samples_root} 不存在！")
            continue

        # 查找所有的 clip 子目录
        clip_dirs = [d for d in samples_root.iterdir() if d.is_dir()]
        if not clip_dirs:
            print(f"   ⚠️ 警告: {samples_root} 下没有找到任何 clip 子目录，跳过。")
            continue

        for clip_dir in clip_dirs:
            print(f"       处理 clip 目录: {clip_dir}")
            subdirs = {d.name for d in clip_dir.iterdir() if d.is_dir()}
            if not CAMERA_SET.issubset(subdirs):
                print(f"   ⚠️  警告: {clip_dir} 缺少部分相机目录，跳过。")
                print(f"       需要: {CAMERA_SET}")
                print(f"       找到: {subdirs}")
                continue  # 跳过此 clip 目录

            print(f"       ✓ 包含所有必需的相机目录。开始扫描图片...")
            # 遍历8个相机目录
            for cam in CAMERA_SET:
                cam_dir = clip_dir / cam
                if not cam_dir.exists():
                    print(f"   ⚠️  警告: {cam_dir} 不存在，跳过。")
                    continue
                elif not cam_dir.is_dir():
                    print(f"   ⚠️  警告: {cam_dir} 不是一个目录，跳过。")
                    continue

                jpg_files = list(cam_dir.glob("*.jpg"))
                print(f"       - {cam}: 搜索 {cam_dir}, 找到 {len(jpg_files)} 张 .jpg 文件")

                for fname in jpg_files:
                    yield str(fname.resolve()), cam, str(samples_root.resolve())
                    count += 1

                    # 每1000张打印进度
                    if count % 1000 == 0:
                        print(f"       ⏳ 累计产出: {count} 张")

    print(f"✅ 扫描完成，总计产出: {count} 张")
    return count  # 返回计数

def evaluate_and_log():
    """统计符合条件的场景"""
    hit_scenes = []
    
    with open("qualified_scenes.csv", "w", newline='', encoding='utf-8') as f_csv:
        writer = csv.writer(f_csv)
        writer.writerow(["samples_third_ann_data_path", "true_cameras"])
        
        for scene_root, cam_dict in SCENE_STATS.items():
            true_cameras = 0
            
            for cam, bool_list in cam_dict.items():
                if not bool_list:
                    continue
                # 正样本超过一半
                if sum(bool_list) > len(bool_list) / 2:
                    true_cameras += 1
                    
            if true_cameras >= 4:  
                hit_scenes.append(scene_root)
                writer.writerow([scene_root, true_cameras])
                print(f"[HIT] {Path(scene_root).name} ({scene_root})  ->  {true_cameras}/8 视角为 True")
                
    return hit_scenes

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root_dir", help="顶层目录，如 /media/train_data/")
    args = parser.parse_args()

    root_path = Path(args.root_dir).expanduser().resolve()
    print(f"🚀 启动扫描: {root_path}")

    # 第一步：查找所有符合条件的 samples_third_ann_data 目录
    samples_directories = find_samples_directories(root_path) # 修正：调用 find_samples_directories

    if not samples_directories:
        print("❌ 未找到任何符合条件的 samples_third_ann_data 目录，程序退出。")
        return

    print(f"--- 调试信息：开始详细扫描 ---")
    # 第二步：详细扫描并统计
    total_found_files = 0
    for samples_root in samples_directories: 
        print(f"详细检查 {samples_root}:")
        for clip_dir in [d for d in samples_root.iterdir() if d.is_dir()]:
            print(f"  检查 clip 目录 {clip_dir}:")
            for cam in CAMERA_SET:
                cam_dir = clip_dir / cam
                if cam_dir.exists() and cam_dir.is_dir():
                    jpg_count = len(list(cam_dir.glob("*.jpg")))
                    print(f"    - {cam}: {jpg_count} 张 .jpg 文件")
                    total_found_files += jpg_count
                else:
                    print(f"    - {cam}: 目录不存在或非目录")
    print(f"--- 调试信息结束：总共找到 {total_found_files} 张 .jpg 文件 ---")

    # 第三步：创建 aiohttp 会话
    connector = aiohttp.TCPConnector(limit=CONCURRENT_REQUESTS, limit_per_host=CONCURRENT_REQUESTS)
    async with aiohttp.ClientSession(connector=connector) as session:

        # 打开输出文件，供 worker 共享
        with open(OUTPUT_FILE, "a", encoding="utf-8") as output_file:

            # 启动 workers
            worker_tasks = [
                asyncio.create_task(worker(i, task_queue, output_file, session))
                for i in range(CONCURRENT_REQUESTS)
            ]

            # 第四步：边扫描边下发任务
            scan_count = 0
            generator = scan_camera_jpg_from_samples_dirs(samples_directories) # 修正：传入列表

            try:
                for img_path, cam, scene_root in generator:
                    await task_queue.put((img_path, cam, scene_root))
                    scan_count += 1

                print(f"\n✅ 扫描+下发完成: {scan_count} 张")

                # 发送退出信号给所有 workers
                for _ in range(CONCURRENT_REQUESTS):
                    await task_queue.put(None)

                # 等待所有任务完成
                await task_queue.join()
                # 等待所有 worker 协程结束
                await asyncio.gather(*worker_tasks, return_exceptions=True)

                # 统计并输出符合条件的场景
                hit_list = evaluate_and_log()
                print(f"\n🎯 最终找到 {len(hit_list)} 个场景符合要求")

            except KeyboardInterrupt:
                print("\n🛑 用户中断程序")
                for t in worker_tasks:
                    t.cancel()


if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())