"""
共享下载引擎 — 手机端 & 电脑端通用
从原 music.pyw 提取核心下载逻辑，移除所有平台专有依赖。

可独立使用：
    from downloader_core import download_media, check_ytdlp_update, import_cookies_from_json
"""

import os
import sys
import json
import subprocess
import threading
import urllib.parse
import time
import importlib

import requests
from yt_dlp import YoutubeDL, version as yt_dlp_version
from yt_dlp.utils import DownloadError, sanitize_filename

# ── Monkey-patch: Bilibili WBI 签名修复 ──────────────────────────
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

# ── 支持的网站列表 ──────────────────────────────────────────────
SUPPORTED_SITES = [
    'youtube.com', 'youtu.be', 'bilibili.com',
    'tiktok.com', 'douyin.com', 'instagram.com',
    'twitter.com', 'x.com', 'facebook.com',
    'vimeo.com', 'dailymotion.com', 'twitch.tv',
    'youku.com', 'v.qq.com', 'iqiyi.com', 'reddit.com',
]

# ── 路径工具 ────────────────────────────────────────────────────


def get_app_dir() -> str:
    """获取应用数据目录（跨平台）"""
    if sys.platform == 'android':
        # Android 上使用应用私有目录
        return os.environ.get(
            'APP_DIR',
            os.path.join(os.environ.get('EXTERNAL_STORAGE', '/sdcard'), 'VideoAudioDownloader')
        )
    # 电脑端：使用项目根目录
    base = os.path.abspath(os.path.dirname(__file__))
    if os.path.basename(base) == 'mobile':
        base = os.path.dirname(base)
    if os.path.basename(base) == '__pycache__':
        base = os.path.dirname(base)
    return base


def get_download_dir() -> str:
    """获取下载目录"""
    app_dir = get_app_dir()
    # 在 Android 上优先存到公共 Downloads 目录
    if sys.platform == 'android':
        try:
            from android.storage import primary_external_storage_path
            public = os.path.join(primary_external_storage_path(), 'Download', 'VideoAudioDownloader')
            os.makedirs(public, exist_ok=True)
            return public
        except Exception:
            pass
    d = os.path.join(app_dir, 'downloads')
    os.makedirs(d, exist_ok=True)
    return d


def get_ffmpeg_path() -> str:
    """获取 ffmpeg 可执行文件路径"""
    # Android 上通常通过 `pkg install ffmpeg` 安装，在 PATH 中
    if sys.platform == 'android':
        # 尝试查找系统 ffmpeg
        for candidate in ['ffmpeg', '/data/data/com.termux/files/usr/bin/ffmpeg']:
            try:
                subprocess.run([candidate, '-version'], capture_output=True, timeout=5)
                return candidate
            except Exception:
                continue
        return 'ffmpeg'  # 最后的 fallback

    # Windows 电脑端
    base = get_app_dir()
    ffmpeg = os.path.join(base, 'bin', 'ffmpeg.exe')
    if os.path.exists(ffmpeg):
        return ffmpeg
    return 'ffmpeg'


def get_ffprobe_path() -> str:
    """获取 ffprobe 路径"""
    ffmpeg = get_ffmpeg_path()
    if sys.platform == 'android':
        return 'ffprobe'
    ffprobe = os.path.join(os.path.dirname(ffmpeg), 'ffprobe.exe')
    if os.path.exists(ffprobe):
        return ffprobe
    return 'ffprobe'

# ── URL 规范化 ─────────────────────────────────────────────────


def normalize_url(item: str) -> str:
    """规范化 URL，支持多个网站"""
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
            cleaned = urllib.parse.urlunparse((
                parsed.scheme, parsed.netloc, parsed.path,
                parsed.params, query, parsed.fragment
            ))
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
    """如果 output template 路径不准确，则在下载目录中查找实际文件"""
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

# ── 视频编解码工具 ─────────────────────────────────────────────


def get_video_codec(file_path: str) -> str:
    """使用 ffprobe 获取视频编码格式"""
    ffprobe = get_ffprobe_path()
    cmd = [
        ffprobe,
        '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding='utf-8', errors='ignore', check=True)
        return result.stdout.strip().lower()
    except Exception:
        return ''


def get_video_duration(file_path: str) -> float:
    """获取视频时长（秒）"""
    ffprobe = get_ffprobe_path()
    cmd = [
        ffprobe,
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding='utf-8', errors='ignore', check=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def run_ffmpeg_with_progress(cmd: list[str], duration: float,
                              progress_func, file_label: str, log_func) -> None:
    """运行 ffmpeg 并通过回调更新编码进度"""
    if progress_func is None:
        subprocess.run(cmd, check=True, capture_output=True)
        return

    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True,
                            encoding='utf-8', errors='ignore', bufsize=1)
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


def repair_video_for_ae(file_path: str, log_func,
                        encode_progress_func=None) -> str:
    """对视频文件应用 faststart，必要时转码为 H.264"""
    if not os.path.exists(file_path):
        return file_path

    ffmpeg = get_ffmpeg_path()
    output_mp4 = file_path if file_path.lower().endswith('.mp4') \
        else os.path.splitext(file_path)[0] + '.mp4'

    codec = get_video_codec(file_path)
    if codec and codec != 'h264':
        log_func(f'  检测到视频编码：{codec}，将转码为 H.264')
    else:
        log_func(f'  检测到视频编码：{codec or "unknown"}，先尝试 faststart 修复')

    duration = get_video_duration(file_path)
    temp_fixed = None

    # 如果是 h264，尝试直接移动 moov
    if codec == 'h264':
        temp_fixed = output_mp4 + '.temp.mp4'
        cmd = [
            ffmpeg, '-i', file_path,
            '-c', 'copy',
            '-movflags', '+faststart',
            '-y', temp_fixed,
        ]
        try:
            run_ffmpeg_with_progress(cmd, duration, encode_progress_func,
                                     os.path.basename(file_path), log_func)
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
        ffmpeg, '-i', file_path,
        '-c:v', 'libx264',
        '-profile:v', 'main',
        '-level', '4.0',
        '-pix_fmt', 'yuv420p',
        '-preset', 'medium',
        '-crf', '18',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-movflags', '+faststart',
        '-y', temp_fixed,
    ]
    try:
        run_ffmpeg_with_progress(cmd, duration, encode_progress_func,
                                 os.path.basename(file_path), log_func)
        os.replace(temp_fixed, output_mp4)
        if output_mp4 != file_path and os.path.exists(file_path) and file_path != output_mp4:
            try:
                os.remove(file_path)
            except Exception:
                pass
        log_func(f'  已转码为 MP4：{os.path.basename(output_mp4)}')
        return output_mp4
    except Exception as exc:
        log_func(f'  转码失败：{exc}')
        if temp_fixed and os.path.exists(temp_fixed):
            try:
                os.remove(temp_fixed)
            except Exception:
                pass
        return file_path

# ── 主下载函数 ─────────────────────────────────────────────────


def download_media(url_type_list: list[tuple[str, str]],
                   download_dir: str,
                   log_func,
                   progress_func=None,
                   encode_progress_func=None):
    """
    下载媒体文件。

    参数:
        url_type_list: [(url, media_type), ...]
            media_type: 'audio' | 'video'
        download_dir: 下载目录
        log_func: 日志回调 log_func(message: str)
        progress_func: 下载进度回调 progress_func(percent: int, filename: str)
        encode_progress_func: 编码进度回调 encode_progress_func(percent: int, filename: str)
    """
    if not url_type_list:
        log_func('没有可下载的链接。请先添加任务。')
        return

    os.makedirs(download_dir, exist_ok=True)

    cookies_file = os.path.join(get_app_dir(), 'cookies.txt')
    if not os.path.exists(cookies_file):
        cookies_file = 'cookies.txt'

    base_opts = {
        'restrictfilenames': True,
        'noplaylist': True,
        'quiet': False,
        'no_warnings': True,
        'ignoreerrors': False,
        'continuedl': True,
        'cachedir': False,
        'source_address': '0.0.0.0',
    }
    if os.path.exists(cookies_file):
        base_opts['cookiefile'] = cookies_file

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

        # Bilibili 需要专属请求头
        if 'bilibili.com' in url:
            opts['http_headers'] = {
                'User-Agent': (
                    'Mozilla/5.0 (Linux; Android 14; Pixel 8) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Mobile Safari/537.36'
                ),
                'Referer': 'https://www.bilibili.com/',
                'Origin': 'https://www.bilibili.com',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            }
        else:
            opts['http_headers'] = {
                'User-Agent': (
                    'Mozilla/5.0 (Linux; Android 14; Pixel 8) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Mobile Safari/537.36'
                ),
            }

        info = None
        ffmpeg_path = get_ffmpeg_path()

        if media_type == 'audio':
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            opts['ffmpeg_location'] = ffmpeg_path
        else:
            # 视频：检测可用画质
            log_func('  正在检测可用画质...')
            detect_opts = base_opts.copy()
            detect_opts.update({
                'quiet': True, 'no_warnings': True, 'noplaylist': True,
                'http_headers': opts.get('http_headers', {}),
            })
            try:
                with YoutubeDL(detect_opts) as ydl_detect:
                    info = ydl_detect.extract_info(url, download=False)
                if isinstance(info, dict):
                    formats = info.get('formats', [])
                    video_fmts = [f for f in formats
                                  if f.get('vcodec') and f.get('vcodec') != 'none']
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
                        fps_text = f'{best.get("fps")}fps ' if best.get('fps') else ''
                        log_func(f'  检测到最高画质：{best.get("height", "?")}p '
                                 f'{fps_text}编码：{best.get("vcodec", "?")}')
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
            opts['ffmpeg_location'] = ffmpeg_path

        temp_outtmpl = os.path.join(download_dir, '%(title)s-%(id)s.%(ext)s')
        opts['outtmpl'] = temp_outtmpl
        opts['progress_hooks'] = [ydl_progress_hook]

        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])

            if media_type == 'video' and isinstance(info, dict):
                pass
            else:
                info = None

            if not isinstance(info, dict):
                log_func('  警告：无法获取文件信息，跳过重命名检查')
                continue

            title = sanitize_filename(info.get('title', 'video'), restricted=True)
            video_id = info.get('id', '')
            final_filename = f"{title}-{video_id}.mp4" if video_id else f"{title}.mp4"
            original_path = os.path.join(download_dir, final_filename)

            if media_type == 'video':
                if os.path.exists(original_path):
                    log_func(f'  找到最终合并文件：{os.path.basename(original_path)}')
                    repaired_path = repair_video_for_ae(
                        original_path, log_func, encode_progress_func)
                else:
                    log_func(
                        f'  警告：未找到合并后的视频文件，尝试查找候选文件')
                    candidate = find_downloaded_file(original_path, download_dir)
                    if os.path.exists(candidate):
                        log_func(f'  找到候选文件：{os.path.basename(candidate)}')
                        repaired_path = repair_video_for_ae(
                            candidate, log_func, encode_progress_func)
                    else:
                        log_func('  警告：未找到最终视频文件，跳过修复')
                        repaired_path = original_path
            else:
                repaired_path = original_path

            # 重命名避免覆盖
            final_path = make_unique_filename(repaired_path)
            if final_path != repaired_path and os.path.exists(repaired_path):
                try:
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


def check_ytdlp_update(log_func) -> str:
    """检查 yt-dlp 是否有新版本，需要时自动更新。返回版本号。"""
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

        log_func(f'发现新版本 {latest_ver}（当前 {current_ver}），正在自动更新...')
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-U', 'yt-dlp'],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
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
    """从 Cookie-Editor 导出的 JSON 文件导入 cookies"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
    except Exception as e:
        log_func(f'读取文件失败：{e}')
        return False

    if not isinstance(cookies, list):
        log_func('JSON 格式错误：期望数组')
        return False

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
        lines.append(
            f'{domain}\t{include_sub}\t{path}\t{secure}\t{exp_int}\t{name}\t{value}')

    # 确定 cookies 文件路径
    cookies_path = os.path.join(get_app_dir(), 'cookies.txt')

    try:
        with open(cookies_path, 'r', encoding='utf-8') as f:
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

    with open(cookies_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    log_func(f'已导入 {len(lines)} 条 cookies，域名：{", ".join(sorted(domains))}')
    return True


def open_download_folder(download_dir: str, log_func) -> None:
    """打开下载目录（跨平台）"""
    if sys.platform == 'android':
        # Android 上无法直接打开文件管理器，提示用户路径
        log_func(f'文件已保存到：{download_dir}')
        log_func('请使用系统文件管理器查看')
        return
    try:
        os.startfile(download_dir)
    except Exception as exc:
        log_func(f'打开目录失败：{exc}')
