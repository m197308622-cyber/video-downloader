import os
import sys
import json
import subprocess
import threading
import urllib.parse
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
from tkinter.scrolledtext import ScrolledText
import requests
from yt_dlp import YoutubeDL, version as yt_dlp_version
from yt_dlp.utils import DownloadError, sanitize_filename

# Monkey-patch: Bilibili WBI 签名接口存在 bug，即使 try_look=1 也只返回 480p
# 改用非 WBI 的 playurl 接口才能获取 1080p+ 完整画质
import yt_dlp.extractor.bilibili as _bilibili_mod

_bilibili_original_playinfo = _bilibili_mod.BiliBiliIE._download_playinfo

def _bilibili_patched_playinfo(self, bvid, cid, headers=None, query=None, fatal=True):
    params = {'bvid': bvid, 'cid': cid, 'fnval': 4048, **(query or {})}
    if getattr(self, 'is_logged_in', False):
        params.pop('try_look', None)
    note = f'Downloading video formats for cid {cid}'
    return self._download_json(
        'https://api.bilibili.com/x/player/playurl', bvid,
        query=params, headers=headers, note=note, fatal=fatal)['data']

_bilibili_mod.BiliBiliIE._download_playinfo = _bilibili_patched_playinfo

# 支持的网站列表
SUPPORTED_SITES = [
    'youtube.com',
    'youtu.be',
    'bilibili.com',
    'tiktok.com',
    'douyin.com',
    'instagram.com',
    'twitter.com',
    'x.com',
    'facebook.com',
    'vimeo.com',
    'dailymotion.com',
    'twitch.tv',
    'youku.com',
    'v.qq.com',
    'iqiyi.com',
    'reddit.com',
]

# 保证即使执行 __pycache__ 下的 .pyc 文件，也能回退到项目根目录
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if os.path.basename(BASE_DIR) == '__pycache__':
    BASE_DIR = os.path.dirname(BASE_DIR)
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')


def normalize_url(item: str) -> str:
    """规范化URL，支持多个网站"""
    item = item.strip()
    if not item:
        return ''

    parsed = urllib.parse.urlparse(item)
    domain = parsed.netloc.lower()

    if any(site in domain for site in SUPPORTED_SITES):
        if 'bilibili.com' in domain:
            if item.startswith('BV') or item.startswith('bv'):
                return f'https://www.bilibili.com/video/{item}'
            if 'bilibili.com/video/' not in item:
                return ''
            qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            qs = [(k, v) for k, v in qs if k.lower() != 't']
            query = urllib.parse.urlencode(qs)
            cleaned = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))
            return cleaned
        elif 'douyin.com' in domain:
            if 'jingxuan' in parsed.path and 'modal_id' in parsed.query:
                qs = urllib.parse.parse_qs(parsed.query)
                modal_id = qs.get('modal_id', [None])[0]
                if modal_id:
                    return f'https://www.douyin.com/video/{modal_id}'
            if 'video/' in parsed.path:
                return item
            return item
        else:
            if not parsed.scheme:
                return 'https://' + item
            return item
    return ''


def make_unique_filename(path: str) -> str:
    """如果文件已存在，在文件名后添加 (1), (2) 等序号"""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    index = 1
    while True:
        new_path = f"{base} ({index}){ext}"
        if not os.path.exists(new_path):
            return new_path
        index += 1


def find_downloaded_file(base_path: str, download_dir: str) -> str:
    """如果 output template 路径不准确，则在下载目录中查找实际文件。"""
    if os.path.exists(base_path):
        return base_path

    base_name, base_ext = os.path.splitext(os.path.basename(base_path))
    if not os.path.isdir(download_dir):
        return base_path

    title_base = base_name
    video_id = ''
    if '-' in base_name:
        title_base, video_id = base_name.rsplit('-', 1)

    exact_matches = []
    substring_matches = []

    for name in os.listdir(download_dir):
        candidate_path = os.path.join(download_dir, name)
        if not os.path.isfile(candidate_path):
            continue
        candidate_base, candidate_ext = os.path.splitext(name)
        if candidate_ext.lower() != base_ext.lower():
            continue

        if candidate_base == base_name:
            return candidate_path

        if video_id and video_id in candidate_base:
            exact_matches.append((candidate_base, candidate_path))
        elif title_base and candidate_base.startswith(title_base):
            substring_matches.append((candidate_base, candidate_path))
        elif base_name in candidate_base or candidate_base in base_name:
            substring_matches.append((candidate_base, candidate_path))

    if exact_matches:
        exact_matches.sort(key=lambda item: (-len(item[0]), item[0]))
        return exact_matches[0][1]
    if substring_matches:
        substring_matches.sort(key=lambda item: (-len(item[0]), item[0]))
        return substring_matches[0][1]

    for ext in ['.mp4', '.mkv', '.webm', '.flv', '.mov', '.ts']:
        candidate = os.path.join(download_dir, title_base + ext)
        if os.path.exists(candidate):
            return candidate

    return base_path


def get_video_codec(file_path: str, ffmpeg_path: str) -> str:
    """使用 ffprobe 获取视频编码格式（兼容 GBK 编码问题）"""
    ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), 'ffprobe.exe')
    if os.path.exists(ffprobe_path):
        cmd = [
            ffprobe_path,
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path,
        ]
        try:
            # 强制使用 utf-8 解码，忽略错误
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', check=True)
            return result.stdout.strip().lower()
        except Exception:
            pass

    # Fallback: 使用 ffmpeg 解析 stderr（也处理编码）
    cmd = [ffmpeg_path, '-hide_banner', '-i', file_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        stderr = result.stderr.lower()
        for line in stderr.splitlines():
            if 'stream' in line and 'video' in line and 'codec' in line:
                # 查找常见编码名
                for codec in ['av1', 'h264', 'hevc', 'vp9']:
                    if codec in line:
                        return codec
        return ''
    except Exception:
        return ''


def get_video_duration(file_path: str, ffmpeg_path: str) -> float:
    """获取视频时长（秒）"""
    ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), 'ffprobe.exe')
    if os.path.exists(ffprobe_path):
        cmd = [
            ffprobe_path,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', check=True)
            return float(result.stdout.strip())
        except Exception:
            return 0.0

    # Fallback
    cmd = [ffmpeg_path, '-i', file_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        stderr = result.stderr.lower()
        for line in stderr.splitlines():
            if 'duration:' in line:
                part = line.split('duration:')[1].split(',')[0].strip()
                h, m, s = part.split(':')
                return float(h) * 3600 + float(m) * 60 + float(s)
        return 0.0
    except Exception:
        return 0.0


def run_ffmpeg_with_progress(cmd: list[str], duration: float, progress_func, file_label: str, log_func) -> None:
    """运行 ffmpeg 并通过回调更新编码进度，同时处理编码错误。"""
    if progress_func is None:
        subprocess.run(cmd, check=True, capture_output=True)
        return

    # 使用 Popen 并强制 stderr 以 utf-8 解码
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore', bufsize=1)
    last_percent = 0
    if duration <= 0:
        progress_func(0, file_label)
    while True:
        line = proc.stderr.readline()
        if not line:
            break
        line = line.strip()
        if line.startswith('out_time_ms='):
            try:
                out_time_ms = int(line.split('=')[1])
                if duration > 0:
                    percent = min(100, int(out_time_ms / (duration * 1000000) * 100))
                    if percent != last_percent:
                        last_percent = percent
                        progress_func(percent, file_label)
            except Exception:
                pass
        elif line.startswith('progress=') and line.split('=')[1] == 'end':
            progress_func(100, file_label)
    proc.wait()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)


def repair_video_for_ae(file_path: str, log_func, encode_progress_func=None) -> str:
    """对视频文件应用 faststart，如果必要则转码为 AE 兼容 MP4。"""
    if not os.path.exists(file_path):
        return file_path

    ffmpeg_path = r'D:\编程程序\code\python\视频音频爬取器\bin\ffmpeg.exe'
    output_mp4 = file_path if file_path.lower().endswith('.mp4') else os.path.splitext(file_path)[0] + '.mp4'

    codec = get_video_codec(file_path, ffmpeg_path)
    if codec and codec != 'h264':
        log_func(f'  检测到视频编码：{codec}，将转码为 H.264 以兼容 AE')
    else:
        log_func(f'  检测到视频编码：{codec or "unknown"}，先尝试 faststart 修复')

    duration = get_video_duration(file_path, ffmpeg_path)
    temp_fixed = None

    # 如果是 h264，尝试直接移动 moov
    if codec == 'h264':
        temp_fixed = output_mp4 + '.temp.mp4'
        cmd = [
            ffmpeg_path,
            '-i', file_path,
            '-c', 'copy',
            '-movflags', '+faststart',
            '-y',
            temp_fixed,
        ]
        try:
            run_ffmpeg_with_progress(cmd, duration, encode_progress_func, os.path.basename(file_path), log_func)
            # 替换原文件
            os.replace(temp_fixed, output_mp4)
            if output_mp4 != file_path and os.path.exists(file_path) and file_path != output_mp4:
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            log_func(f'  已修复视频索引（faststart）：{os.path.basename(output_mp4)}')
            return output_mp4
        except Exception as exc:
            log_func(f'  faststart 修复失败，将尝试转码：{exc}')
            if temp_fixed and os.path.exists(temp_fixed):
                try:
                    os.remove(temp_fixed)
                except Exception:
                    pass

    # 转码为 H.264
    temp_fixed = output_mp4 + '.transcode.temp.mp4'
    cmd = [
        ffmpeg_path,
        '-i', file_path,
        '-c:v', 'libx264',
        '-profile:v', 'main',
        '-level', '4.0',
        '-pix_fmt', 'yuv420p',
        '-preset', 'medium',
        '-crf', '18',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-movflags', '+faststart',
        '-y',
        temp_fixed,
    ]
    try:
        run_ffmpeg_with_progress(cmd, duration, encode_progress_func, os.path.basename(file_path), log_func)
        os.replace(temp_fixed, output_mp4)
        if output_mp4 != file_path and os.path.exists(file_path) and file_path != output_mp4:
            try:
                os.remove(file_path)
            except Exception:
                pass
        log_func(f'  已转码为 AE 兼容 MP4：{os.path.basename(output_mp4)}')
        return output_mp4
    except Exception as exc:
        log_func(f'  转码失败：{exc}')
        if temp_fixed and os.path.exists(temp_fixed):
            try:
                os.remove(temp_fixed)
            except Exception:
                pass
        # 转码失败，返回原始文件路径（不做额外处理，后续重命名可能失败）
        return file_path


def check_and_close_downloads_folder(download_dir: str) -> bool:
    """检查downloads文件夹是否被占用，如果是则关闭explorer进程"""
    temp_file = os.path.join(download_dir, 'temp_check.txt')
    try:
        with open(temp_file, 'w') as f:
            f.write('test')
        os.remove(temp_file)
        return True  # 未被占用
    except Exception:
        # 被占用，关闭explorer
        try:
            subprocess.run(['taskkill', '/f', '/im', 'explorer.exe'], capture_output=True)
            import time
            time.sleep(2)  # 等待explorer重启
            return True
        except Exception:
            return False  # 关闭失败


def download_media(url_type_list: list[tuple[str, str]], download_dir: str, log_func, progress_func=None, encode_progress_func=None):
    if not url_type_list:
        log_func('没有可下载的链接。请先添加任务。')
        return

    os.makedirs(download_dir, exist_ok=True)

    # 检查downloads文件夹是否被占用
    if not check_and_close_downloads_folder(download_dir):
        log_func('downloads文件夹被占用，且无法关闭explorer。请手动关闭downloads文件夹后重试。')
        return

    base_opts = {
        'restrictfilenames': True,
        'noplaylist': True,
        'quiet': False,
        'no_warnings': True,
        'ignoreerrors': False,
        'continuedl': True,
        'cachedir': False,
        'cookiefile': 'cookies.txt',
        'source_address': '0.0.0.0',  # 强制使用 IPv4，解决部分网站 IPv6 不可达的问题
    }

    def ydl_progress_hook(d):
        status = d.get('status')
        if status == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            percent = int(downloaded * 100 / total) if total else 0
            filename = os.path.basename(d.get('filename', ''))
            if progress_func:
                progress_func(percent, filename)
        elif status == 'finished':
            filename = os.path.basename(d.get('filename', ''))
            if progress_func:
                progress_func(100, filename)
            log_func(f'下载完成：{filename}')

    for url, media_type in url_type_list:
        log_func(f'开始下载 [{media_type.upper()}]：{url}')
        opts = base_opts.copy()
        # Bilibili 需要专属请求头，其他网站让 yt-dlp 自行处理
        if 'bilibili.com' in url:
            opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.bilibili.com/',
                'Origin': 'https://www.bilibili.com',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            }
        info = None  # 先初始化，后续复用
        if media_type == 'audio':
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            opts['ffmpeg_location'] = r'D:\编程程序\code\python\视频音频爬取器\bin\ffmpeg.exe'
        else:
            # 视频：自动检测最高画质
            log_func('  正在检测可用画质...')
            detect_opts = base_opts.copy()
            if 'bilibili.com' in url:
                detect_opts['http_headers'] = opts.get('http_headers', {})
            detect_opts.update({'quiet': True, 'no_warnings': True, 'noplaylist': True})
            try:
                with YoutubeDL(detect_opts) as ydl_detect:
                    info = ydl_detect.extract_info(url, download=False)
                if isinstance(info, dict):
                    formats = info.get('formats', [])
                    video_fmts = [f for f in formats if f.get('vcodec') and f.get('vcodec') != 'none']
                    if video_fmts:
                        def sort_key(f):
                            h = f.get('height', 0) or 0
                            fps = f.get('fps', 0) or 0
                            br = f.get('tbr', 0) or 0
                            codec = f.get('vcodec', '')
                            codec_score = 0 if ('h264' in codec or 'avc' in codec) else 1
                            return (-h, -fps, -br, codec_score)
                        video_fmts.sort(key=sort_key)
                        best = video_fmts[0]
                        has_1080p = any((f.get('height') or 0) >= 1080 for f in video_fmts)
                        has_60fps = any((f.get('fps') or 0) >= 60 for f in video_fmts)
                        fps_text = f'{best.get("fps")}fps ' if best.get('fps') else ''
                        log_func(f'  检测到最高画质：{best.get("height", "?")}p {fps_text}编码：{best.get("vcodec", "?")}')
                        # 使用格式排序让 yt-dlp 自行选择最佳画质
                        opts['format_sort'] = ['res', 'fps', 'vcodec:h264']
                        opts['format'] = 'bestvideo+bestaudio/best'
                    else:
                        log_func('  未找到视频格式信息，使用默认画质')
                        opts['format'] = 'bestvideo+bestaudio/best'
                else:
                    log_func('  无法获取视频信息，使用默认画质')
                    opts['format'] = 'bestvideo+bestaudio/best'
            except Exception:
                log_func('  画质检测失败，使用默认画质')
                opts['format'] = 'bestvideo+bestaudio/best'

            opts['merge_output_format'] = 'mp4'
            opts['ffmpeg_location'] = r'D:\编程程序\code\python\视频音频爬取器\bin\ffmpeg.exe'
            opts['ffmpeg_args'] = ['-movflags', '+faststart']

        temp_outtmpl = os.path.join(download_dir, '%(title)s-%(id)s.%(ext)s')
        opts['outtmpl'] = temp_outtmpl
        opts['progress_hooks'] = [ydl_progress_hook]

        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])

            # 视频信息已在检测阶段获取，直接复用；音频单独提取一次
            if media_type == 'video' and isinstance(info, dict):
                pass  # info 已在检测阶段获取
            else:
                info = None

            if not isinstance(info, dict):
                log_func(f'  警告：无法获取文件信息，跳过重命名检查')
                continue

            title = sanitize_filename(info.get('title', 'video'), restricted=True)
            video_id = info.get('id', '')
            final_filename = f"{title}-{video_id}.mp4" if video_id else f"{title}.mp4"
            original_path = os.path.join(download_dir, final_filename)

            if media_type == 'video':
                if os.path.exists(original_path):
                    log_func(f'  找到最终合并文件：{os.path.basename(original_path)}')
                    repaired_path = repair_video_for_ae(original_path, log_func, encode_progress_func)
                else:
                    log_func(f'  警告：未找到合并后的视频文件 {original_path}，尝试查找候选文件')
                    candidate = find_downloaded_file(original_path, download_dir)
                    if os.path.exists(candidate):
                        log_func(f'  找到候选文件：{os.path.basename(candidate)}')
                        repaired_path = repair_video_for_ae(candidate, log_func, encode_progress_func)
                    else:
                        log_func(f'  警告：未找到最终视频文件，跳过修复')
                        repaired_path = original_path
            else:
                repaired_path = original_path

            # 避免重命名时文件被占用：先等待 0.2 秒，再尝试重命名
            final_path = make_unique_filename(repaired_path)
            if final_path != repaired_path and os.path.exists(repaired_path):
                try:
                    # 短暂休眠，释放文件句柄
                    import time
                    time.sleep(0.2)
                    os.rename(repaired_path, final_path)
                    log_func(f'  重命名为：{os.path.basename(final_path)}')
                except Exception as rename_err:
                    log_func(f'  重命名失败：{rename_err}，保留原文件名')

        except DownloadError as exc:
            log_func(f'下载失败：{url}')
            log_func(f'  错误：{exc}')
        except Exception as exc:
            log_func(f'处理时发生异常：{url}')
            log_func(f'  异常：{exc}')
        else:
            log_func(f'完成：{url}\n')


def safe_insert(text_widget: ScrolledText, message: str):
    text_widget.configure(state='normal')
    text_widget.insert(tk.END, message + '\n')
    text_widget.see(tk.END)
    text_widget.configure(state='disabled')


def on_add_to_queue(url_entry: tk.Entry, type_var: tk.StringVar, queue_listbox: tk.Listbox, log_widget: ScrolledText):
    raw_url = url_entry.get().strip()
    if not raw_url:
        messagebox.showwarning('提示', '请输入支持的网站链接')
        return

    normalized_url = normalize_url(raw_url)
    if not normalized_url:
        messagebox.showwarning('提示', '无效的链接，请检查是否为支持的网站')
        return

    media_type = type_var.get()
    display_text = f'[{media_type.upper()}] {normalized_url}'
    queue_listbox.insert(tk.END, (display_text, normalized_url, media_type))
    url_entry.delete(0, tk.END)
    safe_insert(log_widget, f'已添加到队列：{display_text}')


def on_remove_selected(queue_listbox: tk.Listbox, log_widget: ScrolledText):
    selected = queue_listbox.curselection()
    if not selected:
        messagebox.showinfo('提示', '请先选中要移除的任务')
        return
    for idx in reversed(selected):
        item_text = queue_listbox.get(idx)[0]
        queue_listbox.delete(idx)
        safe_insert(log_widget, f'已移除队列项：{item_text}')


def on_start_click(queue_listbox: tk.Listbox, log_widget: ScrolledText, button: tk.Button,
                   progress_var: tk.DoubleVar, progress_label: tk.Label,
                   encode_progress_var: tk.DoubleVar, encode_progress_label: tk.Label,
                   window: tk.Tk):
    if queue_listbox.size() == 0:
        messagebox.showwarning('提示', '队列为空，请先添加任务')
        return

    tasks = []
    for i in range(queue_listbox.size()):
        display_text, url, media_type = queue_listbox.get(i)
        tasks.append((url, media_type))

    button.config(state='disabled')
    safe_insert(log_widget, f'开始批量下载，共 {len(tasks)} 个任务...')
    progress_var.set(0)
    progress_label.config(text='下载进度：0%')
    encode_progress_var.set(0)
    encode_progress_label.config(text='编码进度：0%')

    def log_message(message: str):
        log_widget.after(0, lambda: safe_insert(log_widget, message))

    def update_progress(percent: int, filename: str):
        def inner():
            progress_var.set(percent)
            progress_label.config(text=f'下载进度：{percent}%  文件：{filename}')
        log_widget.after(0, inner)

    def update_encode_progress(percent: int, filename: str):
        def inner():
            encode_progress_var.set(percent)
            encode_progress_label.config(text=f'编码进度：{percent}%  文件：{filename}')
        log_widget.after(0, inner)

    def worker():
        try:
            download_media(tasks, DOWNLOAD_DIR, log_message, update_progress, update_encode_progress)
        except Exception as e:
            log_message(f'下载过程发生异常：{e}')
        finally:
            window.after(0, lambda: button.config(state='normal'))
        log_message('所有下载任务结束。')
        try:
            os.startfile(DOWNLOAD_DIR)
            log_message(f'已打开下载目录：{DOWNLOAD_DIR}')
        except Exception as exc:
            log_message(f'打开目录失败：{exc}')

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def check_ytdlp_update(log_func) -> str:
    """检查 yt-dlp 是否有新版本，需要时自动更新。返回状态消息。"""
    current_ver = yt_dlp_version.__version__
    log_func(f'当前 yt-dlp 版本：{current_ver}')
    try:
        resp = requests.get(
            'https://pypi.org/pypi/yt-dlp/json',
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        latest_ver = data['info']['version']

        def parse_ver(v):
            parts = v.replace('-', '.').split('.')
            return tuple(int(x) for x in parts[:3])

        if parse_ver(latest_ver) <= parse_ver(current_ver):
            log_func(f'yt-dlp 已是最新版（{current_ver}），无需更新')
            return current_ver

        log_func(f'发现 yt-dlp 新版本 {latest_ver}（当前 {current_ver}），正在自动更新...')
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-U', 'yt-dlp'],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            # 重新导入以获取新版本
            import importlib
            import yt_dlp
            importlib.reload(yt_dlp)
            from yt_dlp import version as new_ver
            log_func(f'yt-dlp 已更新至 {new_ver.__version__}')
            return new_ver.__version__
        else:
            log_func(f'自动更新失败：{result.stderr.strip()[:200]}')
            return current_ver
    except requests.exceptions.Timeout:
        log_func('连接 PyPI 超时，跳过版本检查')
        return current_ver
    except requests.exceptions.RequestException as e:
        log_func(f'连接 PyPI 失败（{e}），跳过版本检查')
        return current_ver
    except Exception as e:
        log_func(f'版本检查异常（不影响使用）：{e}')
        return current_ver


def import_cookies_from_json(filepath: str, log_func) -> bool:
    """从 Cookie-Editor 导出的 JSON 文件导入 cookies 到 cookies.txt"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
    except Exception as e:
        log_func(f'读取文件失败：{e}')
        return False

    if not isinstance(cookies, list):
        log_func('JSON 格式错误：期望数组')
        return False

    # 去重（同名取最后一条）
    seen = {}
    for c in cookies:
        name = c.get('name')
        if not name or c.get('session'):
            continue
        seen[name] = c
    cookies = list(seen.values())

    domains = set()
    lines = []
    for c in cookies:
        domain = c.get('domain', '')
        if not domain:
            continue
        domains.add(domain)
        if not c.get('hostOnly', False) and not domain.startswith('.'):
            domain = '.' + domain
        include_sub = 'TRUE' if domain.startswith('.') else 'FALSE'
        path = c.get('path', '/')
        secure = 'TRUE' if c.get('secure') else 'FALSE'
        exp = c.get('expirationDate')
        if exp is None:
            continue
        exp_int = int(exp)
        name = c['name']
        value = c.get('value', '')
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        lines.append(f'{domain}\t{include_sub}\t{path}\t{secure}\t{exp_int}\t{name}\t{value}')

    # 读原文件，移除同名域名的旧条目
    try:
        with open('cookies.txt', 'r', encoding='utf-8') as f:
            old_lines = f.readlines()
    except FileNotFoundError:
        old_lines = []

    blocked = set()
    for d in domains:
        blocked.add(d)
        blocked.add(d.lstrip('.'))
    new_lines = [l for l in old_lines if not any(b in l for b in blocked)]
    new_lines.append('\n')
    new_lines.extend(l + '\n' for l in lines)

    with open('cookies.txt', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    log_func(f'已导入 {len(lines)} 条 cookies，域名：{", ".join(sorted(domains))}')
    return True


def create_gui() -> None:
    window = tk.Tk()
    window.title('多网站音视频下载器（队列模式）')
    window.geometry('800x650')

    global log_box
    log_box = None  # 稍后创建

    frame_input = tk.Frame(window)
    frame_input.pack(fill=tk.X, padx=10, pady=10)

    tk.Label(frame_input, text='视频链接：').grid(row=0, column=0, sticky='w', padx=(0, 5))
    url_entry = tk.Entry(frame_input, width=60)
    url_entry.grid(row=0, column=1, padx=(0, 10), sticky='ew')

    type_var = tk.StringVar(value='audio')
    tk.Radiobutton(frame_input, text='音频', variable=type_var, value='audio').grid(row=0, column=2, padx=(0, 5))
    tk.Radiobutton(frame_input, text='视频', variable=type_var, value='video').grid(row=0, column=3, padx=(0, 10))

    add_btn = tk.Button(frame_input, text='添加到队列', command=lambda: on_add_to_queue(url_entry, type_var, queue_listbox, log_box))
    add_btn.grid(row=0, column=4)

    frame_input.columnconfigure(1, weight=1)

    frame_queue = tk.Frame(window)
    frame_queue.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    tk.Label(frame_queue, text='下载队列（右键可移除，或选中后点击“移除选中”）').pack(anchor='w')
    queue_listbox = tk.Listbox(frame_queue, height=8)
    queue_listbox.pack(fill=tk.BOTH, expand=True, pady=(2, 5))

    frame_queue_btns = tk.Frame(frame_queue)
    frame_queue_btns.pack(fill=tk.X)
    remove_btn = tk.Button(frame_queue_btns, text='移除选中', command=lambda: on_remove_selected(queue_listbox, log_box))
    remove_btn.pack(side=tk.LEFT, padx=(0, 10))
    clear_btn = tk.Button(frame_queue_btns, text='清空队列', command=lambda: (queue_listbox.delete(0, tk.END), safe_insert(log_box, '队列已清空')))
    clear_btn.pack(side=tk.LEFT)
    cookies_btn = tk.Button(frame_queue_btns, text='导入 Cookies', command=lambda: (
        safe_insert(log_box, import_cookies_from_json(
            filedialog.askopenfilename(
                title='选择 Cookie-Editor 导出的 JSON 文件',
                filetypes=[('JSON 文件', '*.json'), ('所有文件', '*.*')],
            ), lambda msg: safe_insert(log_box, msg)) and 'Cookies 导入成功' or 'Cookies 导入失败')
    ))
    cookies_btn.pack(side=tk.LEFT, padx=(10, 0))

    frame_control = tk.Frame(window)
    frame_control.pack(fill=tk.X, padx=10, pady=(0, 10))

    frame_download_progress = tk.Frame(frame_control)
    frame_download_progress.pack(fill=tk.X, pady=(0, 5))
    progress_var = tk.DoubleVar(value=0)
    progress_bar = ttk.Progressbar(frame_download_progress, variable=progress_var, maximum=100)
    progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
    progress_label = tk.Label(frame_download_progress, text='下载进度：0%')
    progress_label.pack(side=tk.LEFT)

    frame_encode_progress = tk.Frame(frame_control)
    frame_encode_progress.pack(fill=tk.X, pady=(0, 5))
    encode_progress_var = tk.DoubleVar(value=0)
    encode_progress_bar = ttk.Progressbar(frame_encode_progress, variable=encode_progress_var, maximum=100)
    encode_progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
    encode_progress_label = tk.Label(frame_encode_progress, text='编码进度：0%')
    encode_progress_label.pack(side=tk.LEFT)

    start_btn = tk.Button(frame_control, text='开始下载', width=12,
                          command=lambda: on_start_click(queue_listbox, log_box, start_btn, progress_var, progress_label, encode_progress_var, encode_progress_label, window))
    start_btn.pack(anchor='e')

    tk.Label(window, text='下载日志：').pack(anchor='w', padx=10)
    log_box = ScrolledText(window, height=14, state='disabled', wrap='word')
    log_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    # 启动时后台检查 yt-dlp 更新
    def startup_check():
        safe_insert(log_box, '正在启动...')
        check_ytdlp_update(lambda msg: safe_insert(log_box, msg))
    window.after(100, lambda: threading.Thread(target=startup_check, daemon=True).start())

    window.mainloop()


if __name__ == '__main__':
    create_gui()