"""
手机端 App — 多网站音视频下载器
基于 Kivy 框架，可编译为 Android APK
"""
import os
import sys
import threading

# ── Kivy 导入 ─────────────────────────────────────────────────
import kivy
kivy.require('2.1.0')

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import (StringProperty, NumericProperty,
                              BooleanProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.utils import platform

# Android 特有导入
if platform == 'android':
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([
            Permission.INTERNET,
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.READ_EXTERNAL_STORAGE,
        ])
    except Exception:
        pass
    try:
        from android.storage import primary_external_storage_path
    except Exception:
        pass
    try:
        from jnius import autoclass
        AndroidActivity = autoclass('org.kivy.android.PythonActivity')
    except Exception:
        pass

# ── 导入共享下载引擎 ─────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from downloader_core import (
    download_media,
    check_ytdlp_update,
    import_cookies_from_json,
    normalize_url,
    get_download_dir,
    open_download_folder,
)

# ── KV 语言 UI 定义 ───────────────────────────────────────────

KV = '''
#:import platform kivy.utils.platform

<MenuScreen>:
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)

        # ── 顶部标题栏 ──
        BoxLayout:
            size_hint_y: None
            height: dp(56)
            spacing: dp(8)

            Label:
                text: '📥 音视频下载器'
                font_size: dp(20)
                bold: True
                halign: 'left'
                valign: 'middle'
                size_hint_x: 0.7

            Button:
                text: '⚙'
                font_size: dp(22)
                size_hint_x: None
                width: dp(48)
                on_release: app.open_settings()

            Button:
                text: '📂'
                font_size: dp(22)
                size_hint_x: None
                width: dp(48)
                on_release: app.open_downloads()

        # ── URL 输入区 ──
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)

            TextInput:
                id: url_input
                hint_text: '粘贴视频/音频链接...'
                multiline: False
                font_size: dp(15)
                size_hint_x: 0.7
                on_text_validate: app.add_task()

            Button:
                text: '➕ 添加'
                font_size: dp(14)
                size_hint_x: None
                width: dp(80)
                on_release: app.add_task()

        # ── 类型切换 ──
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(12)

            ToggleButton:
                id: audio_btn
                text: '🎵 音频'
                group: 'media_type'
                state: 'down'
                font_size: dp(14)
                on_release: app.set_media_type('audio')

            ToggleButton:
                id: video_btn
                text: '🎬 视频'
                group: 'media_type'
                font_size: dp(14)
                on_release: app.set_media_type('video')

        # ── 任务队列 ──
        BoxLayout:
            size_hint_y: None
            height: dp(32)
            spacing: dp(8)

            Label:
                text: '📋 下载队列'
                font_size: dp(14)
                bold: True
                halign: 'left'
                valign: 'middle'
                size_hint_x: 0.6

            Label:
                id: queue_count
                text: '0 个任务'
                font_size: dp(12)
                halign: 'right'
                valign: 'middle'
                size_hint_x: 0.4

        # ── 任务列表 ──
        RecycleView:
            id: task_list
            viewclass: 'TaskItem'
            scroll_type: ['content', 'bars']
            bar_width: dp(6)

            RecycleBoxLayout:
                default_size: None, dp(56)
                default_size_hint: 1, None
                size_hint_y: None
                height: self.minimum_height
                orientation: 'vertical'
                spacing: dp(4)

        # ── 操作按钮 ──
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)

            Button:
                text: '🗑 清空'
                font_size: dp(14)
                on_release: app.clear_queue()

            Button:
                id: start_btn
                text: '▶ 开始下载'
                font_size: dp(16)
                bold: True
                background_color: 0.2, 0.7, 0.3, 1
                on_release: app.start_download()

        # ── 下载进度 ──
        BoxLayout:
            size_hint_y: None
            height: dp(24)
            spacing: dp(8)

            Label:
                id: progress_label
                text: '等待中...'
                font_size: dp(12)
                halign: 'left'
                valign: 'middle'
                size_hint_x: 0.4

            ProgressBar:
                id: progress_bar
                max: 100
                value: 0
                size_hint_x: 0.6

        # ── 转码进度 ──
        BoxLayout:
            size_hint_y: None
            height: dp(24)
            spacing: dp(8)

            Label:
                id: encode_label
                text: ''
                font_size: dp(12)
                halign: 'left'
                valign: 'middle'
                size_hint_x: 0.4

            ProgressBar:
                id: encode_bar
                max: 100
                value: 0
                size_hint_x: 0.6

        # ── 日志 ──
        BoxLayout:
            size_hint_y: None
            height: dp(24)
            spacing: dp(8)

            Label:
                text: '📄 日志'
                font_size: dp(13)
                bold: True
                halign: 'left'
                valign: 'middle'

            Button:
                text: '清除'
                font_size: dp(12)
                size_hint_x: None
                width: dp(60)
                on_release: app.clear_log()

        RelativeLayout:
            size_hint_y: 1

            ScrollView:
                id: log_scroll
                do_scroll_x: False
                do_scroll_y: True

                Label:
                    id: log_label
                    text: '就绪'
                    font_size: dp(11)
                    color: 0.8, 0.8, 0.8, 1
                    size_hint_y: None
                    height: self.texture_size[1] + dp(10)
                    text_size: self.width - dp(10), None
                    valign: 'top'
                    halign: 'left'

                    canvas.before:
                        Color:
                            rgba: 0.12, 0.12, 0.12, 1
                        Rectangle:
                            pos: self.pos
                            size: self.size


<TaskItem>:
    # 单个任务项的显示布局
    orientation: 'horizontal'
    padding: dp(8)
    spacing: dp(8)
    size_hint_y: None
    height: dp(56)

    canvas.before:
        Color:
            rgba: 0.15, 0.15, 0.15, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(6)]

    Label:
        text: '🎵' if root.media_type == 'audio' else '🎬'
        font_size: dp(18)
        size_hint_x: None
        width: dp(32)
        halign: 'center'
        valign: 'middle'

    BoxLayout:
        orientation: 'vertical'
        spacing: dp(2)

        Label:
            text: root.url_display
            font_size: dp(13)
            bold: True
            halign: 'left'
            valign: 'middle'
            color: 1, 1, 1, 1
            text_size: self.width - dp(8), None
            shorten: True
            shorten_from: 'right'

        Label:
            text: root.status_text
            font_size: dp(11)
            halign: 'left'
            valign: 'middle'
            color: 0.6, 0.6, 0.6, 1

    Button:
        text: '✕'
        font_size: dp(16)
        size_hint_x: None
        width: dp(36)
        background_color: 0.7, 0.15, 0.15, 1
        on_release: app.remove_task(root.task_index)
        disabled: root.downloading


<SettingsPopup>:
    BoxLayout:
        orientation: 'vertical'
        padding: dp(16)
        spacing: dp(12)

        Label:
            text: '⚙ 设置'
            font_size: dp(18)
            bold: True
            size_hint_y: None
            height: dp(36)

        BoxLayout:
            size_hint_y: None
            height: dp(40)
            spacing: dp(8)

            Label:
                text: '下载目录：'
                font_size: dp(13)
                size_hint_x: 0.35
                halign: 'left'
                valign: 'middle'

            TextInput:
                id: dir_input
                text: root.current_dir
                font_size: dp(12)
                multiline: False
                size_hint_x: 0.65

        BoxLayout:
            size_hint_y: None
            height: dp(40)
            spacing: dp(8)

            Label:
                text: 'Cookies：'
                font_size: dp(13)
                size_hint_x: 0.35
                halign: 'left'
                valign: 'middle'

            Button:
                text: '📥 导入 JSON'
                font_size: dp(12)
                size_hint_x: 0.65
                on_release: root.import_cookies()

        BoxLayout:
            size_hint_y: None
            height: dp(40)
            spacing: dp(8)

            Label:
                text: '更新 yt-dlp：'
                font_size: dp(13)
                size_hint_x: 0.5
                halign: 'left'
                valign: 'middle'

            Button:
                text: '🔄 检查更新'
                font_size: dp(12)
                size_hint_x: 0.5
                on_release: root.check_update()

        BoxLayout:
            size_hint_y: None
            height: dp(40)
            spacing: dp(8)

            Label:
                id: version_label
                text: ''
                font_size: dp(11)
                color: 0.7, 0.7, 0.7, 1

        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(12)
            pos_hint: {'center_x': 0.5}

            Button:
                text: '保存'
                font_size: dp(14)
                on_release: root.save_settings()

            Button:
                text: '关闭'
                font_size: dp(14)
                on_release: root.dismiss()
'''


# ── 任务列表项（RecycleView 的 viewclass） ────────────────────


class TaskItem(BoxLayout):
    """单个任务项的视图类"""
    url_display = StringProperty('')
    media_type = StringProperty('audio')
    status_text = StringProperty('等待中')
    task_index = NumericProperty(0)
    downloading = BooleanProperty(False)


class SettingsPopup(Popup):
    """设置弹窗"""
    current_dir = StringProperty('')

    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app = app_ref
        self.current_dir = get_download_dir()
        self.title = ''

    def import_cookies(self):
        """导入 Cookies（Android 上用文件选择器）"""
        if platform == 'android':
            try:
                from android.content import Intent
                from android import activity
                # 使用 SAF 文件选择器
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.setType('*/*')
                # 这里简化处理，实际需要 onActivityResult 回调
                self.app.log('请在文件管理器中找到 cookies.json 文件')
                self.app.log('然后复制到应用目录下')
            except Exception as e:
                self.app.log(f'导入 Cookies 失败：{e}')
        else:
            # 桌面版直接用文件对话框
            try:
                from tkinter import filedialog, Tk
                root = Tk()
                root.withdraw()
                path = filedialog.askopenfilename(
                    title='选择 Cookie-Editor 导出的 JSON 文件',
                    filetypes=[('JSON 文件', '*.json'), ('所有文件', '*.*')],
                )
                root.destroy()
                if path:
                    import_cookies_from_json(path, self.app.log)
            except Exception as e:
                self.app.log(f'导入 Cookies 失败：{e}')

    def check_update(self):
        """检查 yt-dlp 更新"""
        def task():
            check_ytdlp_update(self.app.log)
        threading.Thread(target=task, daemon=True).start()

    def save_settings(self):
        # 目录保存在 app 内部，实际下载时使用
        self.dismiss()

    def dismiss(self, *largs):
        self.app._settings_popup = None
        super().dismiss(*largs)


# ── 主界面 Screen ────────────────────────────────────────────


class MenuScreen(Screen):
    """主界面"""
    pass


# ── 主 App ────────────────────────────────────────────────────


class DownloaderApp(App):
    """音视频下载器 Android App"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.media_type = 'audio'
        self.task_list = []      # [(url, media_type, display_url), ...]
        self.task_data = []      # RecycleView 数据
        self.is_downloading = False
        self._settings_popup = None
        self._log_buffer = []
        self._update_ytdlp_done = False

    def build(self):
        self.title = '音视频下载器'
        self.icon = ''

        Builder.load_string(KV)
        screen = MenuScreen()

        # 启动后初始化
        Clock.schedule_once(self._on_start, 0.5)
        return screen

    def _on_start(self, dt):
        """应用启动后的初始化"""
        self.log('📱 音视频下载器已启动')
        self.log(f'📁 下载目录：{get_download_dir()}')
        self.log(f'🤖 平台：{platform}')

        # 检查支持的网站
        from downloader_core import SUPPORTED_SITES
        self.log(f'🌐 支持 {len(SUPPORTED_SITES)} 个网站')

        # 后台检查更新
        def check():
            if not self._update_ytdlp_done:
                self._update_ytdlp_done = True
                check_ytdlp_update(self.log)
        threading.Thread(target=check, daemon=True).start()

    # ── UI 操作方法 ──────────────────────────────────────────

    def set_media_type(self, mt: str):
        self.media_type = mt

    def add_task(self):
        """从输入框添加任务到队列"""
        screen = self.root
        if not screen:
            return
        url_input = screen.ids.url_input
        raw_url = url_input.text.strip()
        if not raw_url:
            return

        norm_url = normalize_url(raw_url)
        if not norm_url:
            self.log(f'❌ 无效链接：{raw_url}')
            url_input.text = ''
            return

        # 截断显示用 URL
        display = norm_url[:50] + '...' if len(norm_url) > 50 else norm_url
        self.task_list.append((norm_url, self.media_type, display))
        self._refresh_task_list()
        url_input.text = ''
        self.log(f'✅ 已添加：[{self.media_type.upper()}] {norm_url}')

    def remove_task(self, index: int):
        """从队列移除任务"""
        if 0 <= index < len(self.task_list):
            removed = self.task_list.pop(index)
            self.log(f'🗑 已移除：{removed[2]}')
            self._refresh_task_list()

    def clear_queue(self):
        """清空队列"""
        self.task_list.clear()
        self._refresh_task_list()
        self.log('🗑 队列已清空')

    def _refresh_task_list(self):
        """刷新 RecycleView 的数据"""
        screen = self.root
        if not screen:
            return

        self.task_data = []
        for i, (url, mt, display) in enumerate(self.task_list):
            self.task_data.append({
                'url_display': display,
                'media_type': mt,
                'status_text': '等待中',
                'task_index': i,
                'downloading': self.is_downloading,
            })

        screen.ids.task_list.data = self.task_data
        screen.ids.queue_count.text = f'{len(self.task_list)} 个任务'

    def start_download(self):
        """开始批量下载"""
        if not self.task_list:
            self.log('⚠️ 队列为空，请先添加任务')
            return

        if self.is_downloading:
            self.log('⏳ 正在下载中，请等待完成')
            return

        self.is_downloading = True
        screen = self.root
        screen.ids.start_btn.text = '⏳ 下载中...'
        screen.ids.start_btn.disabled = True

        # 更新所有任务状态
        self._refresh_task_list()

        tasks = [(url, mt) for url, mt, _ in self.task_list]
        download_dir = get_download_dir()
        self.log(f'▶️ 开始下载 {len(tasks)} 个任务...')
        self.log(f'📁 保存到：{download_dir}')

        def worker():
            try:
                download_media(
                    tasks, download_dir,
                    log_func=self.log,
                    progress_func=self._on_progress,
                    encode_progress_func=self._on_encode_progress,
                )
                self.log('✅ 所有下载任务完成！')
            except Exception as e:
                self.log(f'❌ 下载过程异常：{e}')
            finally:
                self.is_downloading = False
                Clock.schedule_once(lambda dt: self._on_download_done(), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_done(self):
        """下载完成后的 UI 恢复"""
        screen = self.root
        if not screen:
            return
        screen.ids.start_btn.text = '▶ 开始下载'
        screen.ids.start_btn.disabled = False
        screen.ids.progress_bar.value = 0
        screen.ids.progress_label.text = '等待中...'
        screen.ids.encode_bar.value = 0
        screen.ids.encode_label.text = ''
        self._refresh_task_list()

    def _on_progress(self, percent: int, filename: str):
        """下载进度回调（在工作线程中调用）"""
        def update(dt):
            screen = self.root
            if not screen:
                return
            screen.ids.progress_bar.value = percent
            screen.ids.progress_label.text = f'📥 {percent}%  {filename or ""}'
        Clock.schedule_once(update, 0)

    def _on_encode_progress(self, percent: int, filename: str):
        """编码进度回调"""
        def update(dt):
            screen = self.root
            if not screen:
                return
            screen.ids.encode_bar.value = percent
            screen.ids.encode_label.text = f'🎞 {percent}%  {filename or ""}'
        Clock.schedule_once(update, 0)

    # ── 日志系统 ─────────────────────────────────────────────

    def log(self, message: str):
        """添加日志（线程安全）"""
        def update(dt):
            screen = self.root
            if not screen:
                self._log_buffer.append(message)
                return

            log_label = screen.ids.log_label
            current = log_label.text
            if current == '就绪':
                current = ''
            lines = current.split('\n')
            lines.append(message)
            # 保留最近 200 行
            if len(lines) > 200:
                lines = lines[-200:]
            log_label.text = '\n'.join(lines)

            # 自动滚动到底部
            scroll = screen.ids.log_scroll
            scroll.scroll_y = 0

        # 处理启动前缓存的日志
        while self._log_buffer:
            msg = self._log_buffer.pop(0)
            Clock.schedule_once(lambda dt, m=msg: self._flush_log(m), 0)

        Clock.schedule_once(update, 0)

    def _flush_log(self, message: str):
        """刷新启动前的缓存日志"""
        screen = self.root
        if not screen:
            return
        log_label = screen.ids.log_label
        if log_label.text == '就绪':
            log_label.text = ''
        lines = log_label.text.split('\n')
        lines.append(message)
        if len(lines) > 200:
            lines = lines[-200:]
        log_label.text = '\n'.join(lines)

    def clear_log(self):
        """清除日志"""
        screen = self.root
        if not screen:
            return
        screen.ids.log_label.text = '就绪'

    # ── 功能按钮 ─────────────────────────────────────────────

    def open_settings(self):
        """打开设置弹窗"""
        if self._settings_popup:
            self._settings_popup.dismiss()
        self._settings_popup = SettingsPopup(self)
        self._settings_popup.open()

    def open_downloads(self):
        """打开下载目录"""
        d = get_download_dir()
        if platform == 'android':
            self.log(f'📁 下载目录：{d}')
            # 尝试用 SAF 打开
            try:
                import webbrowser
                webbrowser.open(f'content://com.android.externalstorage.documents/document/primary%3ADownload%2FVideoAudioDownloader')
            except Exception:
                pass
        else:
            open_download_folder(d, self.log)


# ── 入口 ──────────────────────────────────────────────────────

if __name__ == '__main__':
    DownloaderApp().run()
