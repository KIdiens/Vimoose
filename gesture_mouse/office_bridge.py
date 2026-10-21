"""Office 工作线程与短期授权。COM 对象只在创建它们的线程使用。"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from dataclasses import dataclass, replace
from uuid import uuid4



@dataclass(frozen=True, slots=True)
class OfficeTarget:
    kind: str
    key: str
    hwnd: int
    label: str


@dataclass(frozen=True, slots=True)
class OfficeStatus:
    token: str = ""
    target: OfficeTarget | None = None
    documents: tuple[OfficeTarget, ...] = ()
    message: str = "等待 PowerPoint 全屏放映，或选择 Word 文档"
    checked_ns: int = 0
    sent: int = 0
    latency_ms: float = 0.


class WindowsOfficeAdapter:
    """仅连接已运行的 Office；不启动程序、不激活窗口。"""

    def __init__(self, safe_mode=False):
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        self.comtypes = comtypes
        self.client = comtypes.client
        self.safe_mode = safe_mode
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p
        self.user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.user32.GetWindow.restype = ctypes.c_void_p
        self.user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        self.user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        self.user32.IsWindowEnabled.argtypes = [ctypes.c_void_p]
        self.apps = {}
        self.word_windows = {}
        self.ppt_windows = {}
        self.bound_word = ""
        self._documents = ()
        self._last_documents = 0.
        self.diagnostic_error = ""

    def close(self):
        self.apps.clear()
        self.word_windows.clear()
        self.comtypes.CoUninitialize()

    def _app(self, name):
        if name not in self.apps:
            try:
                self.apps[name] = self.client.GetActiveObject(name, dynamic=True)
            except Exception:
                return None
        return self.apps.get(name)

    def _class(self, hwnd):
        value = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, value, len(value))
        return value.value

    def _pid(self, hwnd):
        value = ctypes.c_ulong()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(value))
        return value.value

    def _document_hwnd(self, window):
        try:
            return int(window.HWND)
        except Exception:
            # 部分 Office 16 的 HWND 不对 IDispatch 开放；只允许唯一的
            # “真实 POWERPNT 进程 + 编辑窗口类 + 完整文档标题”关联。
            caption = str(window.Caption)
            if not caption:
                return 0
            matches = []
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
            self.user32.GetWindowTextW.argtypes = [ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_int]
            def visit(hwnd,_):
                if self._class(hwnd) != "PPTFrameClass" or not self._is_powerpoint(self._pid(hwnd)):
                    return True
                title = ctypes.create_unicode_buffer(2048)
                self.user32.GetWindowTextW(hwnd,title,len(title))
                if title.value == caption or title.value.startswith(caption+" - "):
                    matches.append(int(hwnd))
                return True
            callback = callback_type(visit)
            self.user32.EnumWindows(callback,0)
            return matches[0] if len(matches)==1 else 0

    def _show_hwnd(self, app, show):
        """HWND 是部分 Office 版本的受限成员；唯一全屏放映时作保守原生关联。"""
        try:
            return int(show.HWND)
        except Exception:
            if int(app.SlideShowWindows.Count) != 1 or not bool(show.IsFullScreen):
                return 0
            windows = []
            processes = set()
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
            self.user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
            def visit(hwnd,_):
                if self._class(hwnd) in ("PPTFrameClass", "screenClass", "PodiumParent"):
                    pid = self._pid(hwnd)
                    if self._is_powerpoint(pid):
                        processes.add(pid)
                        if self._class(hwnd) == "screenClass" and self.user32.IsWindowVisible(hwnd):
                            windows.append(int(hwnd))
                return True
            callback = callback_type(visit)
            self.user32.EnumWindows(callback,0)
            # 多进程或多放映无法可靠关联时，禁止猜测文档和窗口。
            return windows[0] if len(windows) == 1 and len(processes) == 1 else 0

    @staticmethod
    def _is_powerpoint(pid):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p,ctypes.c_ulong,
                                                     ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)]
        handle = kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            return False
        try:
            value = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(value))
            return (bool(kernel.QueryFullProcessImageNameW(handle,0,value,ctypes.byref(size)))
                    and value.value.replace("/","\\").rsplit("\\",1)[-1].upper() == "POWERPNT.EXE")
        finally:
            kernel.CloseHandle(handle)

    def _unobstructed(self, hwnd):
        # 菜单、系统菜单、弹出菜单、移动窗口等模式全部拒绝输入。
        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [("cbSize",ctypes.c_ulong),("flags",ctypes.c_ulong),
                        ("active",ctypes.c_void_p),("focus",ctypes.c_void_p),
                        ("capture",ctypes.c_void_p),("menu",ctypes.c_void_p),
                        ("move",ctypes.c_void_p),("caret",ctypes.c_void_p),
                        ("rect",ctypes.c_long*4)]
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        thread = self.user32.GetWindowThreadProcessId(hwnd, None)
        if not self.user32.GetGUIThreadInfo(thread, ctypes.byref(info)):
            return False
        return (bool(self.user32.IsWindowEnabled(hwnd)) and not info.flags & 0x1e
                and not any(self.user32.GetAsyncKeyState(k) & 0x8000
                            for k in (0x10,0x11,0x12,0x5b,0x5c)))

    def documents(self):
        if time.monotonic()-self._last_documents < .5:
            return self._documents
        self._last_documents = time.monotonic()
        found, windows = [], {}
        app = self._app("Word.Application")
        if app is not None:
            try:
                for i in range(1,int(app.Windows.Count)+1):
                    w = app.Windows.Item(i)
                    hwnd = int(w.Hwnd)
                    # 文档名只在界面显示，不写入日志；键包含完整文档身份和句柄。
                    key = f"word:{hwnd}:{w.Document.FullName}"
                    found.append(OfficeTarget("word",key,hwnd,str(w.Caption)))
                    windows[key] = w
            except Exception:
                self.apps.pop("Word.Application",None)
        self.word_windows = windows
        self._documents = tuple(found)
        if self.bound_word and self.bound_word not in windows:
            self.bound_word = ""
        return self._documents

    def scan(self, word_key):
        docs = self.documents()
        self.bound_word = word_key if word_key in self.word_windows else ""
        hwnd = int(self.user32.GetForegroundWindow() or 0)
        if not hwnd or not self._unobstructed(hwnd):
            return None, docs, "非目标窗口、菜单、对话框或修饰键按下"
        ppt = self._app("PowerPoint.Application")
        if ppt is not None:
            try:
                for i in range(1,int(ppt.SlideShowWindows.Count)+1):
                    show = ppt.SlideShowWindows.Item(i)
                    shwnd = self._show_hwnd(ppt,show)
                    if not shwnd:
                        continue
                    if not bool(show.IsFullScreen):
                        continue
                    # 演讲者视图仅允许专用原生窗口类；绝不放行普通 PPT 编辑框。
                    presenter = (self._class(hwnd) == "PodiumParent"
                                 and self._pid(hwnd) == self._pid(shwnd))
                    if hwnd == shwnd or presenter:
                        key = f"ppt:{shwnd}:{show.Presentation.FullName}"
                        return OfficeTarget("ppt",key,hwnd,"PowerPoint 放映"), docs, "PPT 翻页已就绪"
            except Exception as error:
                self.apps.pop("PowerPoint.Application",None)
                self.diagnostic_error = f"{type(error).__name__}: {error}"
                return None, docs, "PowerPoint 接口不可用，已暂停"
        target = next((d for d in docs if d.key == self.bound_word and d.hwnd == hwnd),None)
        if target:
            try:
                w = self.word_windows[target.key]
                if bool(w.Application.ProtectedViewWindows.Count):
                    return None, docs, "Word 保护视图中禁止控制"
                if str(w.Document.FullName) != target.key.split(":",2)[2]:
                    return None, docs, "文档已更换，请重新绑定"
            except Exception:
                return None, docs, "Word 接口不可用，已暂停"
            return target, docs, "Word 文档演示已就绪"
        return None, docs, "等待目标放映／文档处于前台"

    def execute(self, target, direction):
        # 执行点二次核验，且将按下和释放一次性提交，避免留下按键。
        if int(self.user32.GetForegroundWindow() or 0) != target.hwnd or not self._unobstructed(target.hwnd):
            return False
        if self.safe_mode:
            return True
        if target.kind == "word":
            w = self.word_windows.get(target.key)
            if w is None:
                return False
            if direction > 0:
                w.LargeScroll(1,0,0,0)
            else:
                w.LargeScroll(0,1,0,0)
        elif target.kind == "ppt-edit":
            w = self.ppt_windows.get(target.key)
            if w is None or str(w.Presentation.FullName) != target.key.split(":",2)[2]:
                return False
            if int(w.Selection.Type) == 3:
                return False
            try:
                current = int(w.View.Slide.SlideIndex)
            except Exception:
                current = int(w.Selection.SlideRange.Item(1).SlideIndex)
            index = max(1,min(int(w.Presentation.Slides.Count),current+direction))
            w.View.GotoSlide(index)
        else:
            from gesture_mouse.mouse import INPUT, KEYBDINPUT
            key = 0x22 if direction > 0 else 0x21
            values = (INPUT*2)(INPUT(type=1,ki=KEYBDINPUT(wVk=key)),
                               INPUT(type=1,ki=KEYBDINPUT(wVk=key,dwFlags=2)))
            self.user32.SendInput.argtypes = [ctypes.c_uint,ctypes.POINTER(INPUT),ctypes.c_int]
            if self.user32.SendInput(2, values, ctypes.sizeof(INPUT)) != 2:
                # 可能只接受了按下。仅补发释放，不重试翻页或重新按下。
                release = (INPUT*1)(INPUT(type=1,ki=KEYBDINPUT(wVk=key,dwFlags=2)))
                self.user32.SendInput(1,release,ctypes.sizeof(INPUT))
                raise OSError("Office 翻页键提交失败，请检查权限")
        return True

    def scan_auto(self):
        """跟随前台文档，不抢焦点；编辑中的文字选区不接收翻页动作。"""
        hwnd = int(self.user32.GetForegroundWindow() or 0)
        docs = self.documents()
        word = next((d.key for d in docs if d.hwnd == hwnd), "")
        target, docs, reason = self.scan(word)
        if target:
            return target, docs, reason
        self.ppt_windows.clear()
        if not hwnd or self._class(hwnd) != "PPTFrameClass" or not self._unobstructed(hwnd):
            return None, docs, "日常鼠标 · 自动等待 PPT／Word"
        app = self._app("PowerPoint.Application")
        if app is None:
            return None,docs,"PowerPoint 接口不可用，翻页已暂停"
        try:
            if int(app.ProtectedViewWindows.Count):
                return None,docs,"保护视图中禁止自动翻页"
            for i in range(1,int(app.Windows.Count)+1):
                w = app.Windows.Item(i)
                if self._document_hwnd(w) != hwnd:
                    continue
                if int(w.ViewType) not in (1,7,9) or int(w.Selection.Type) == 3:
                    return None,docs,"PPT 文字编辑／特殊视图 · 保留鼠标操作"
                key = f"ppt-edit:{hwnd}:{w.Presentation.FullName}"
                self.ppt_windows[key] = w
                return OfficeTarget("ppt-edit",key,hwnd,"PowerPoint 浏览"),docs,"PPT 浏览 · 张掌翻页，指向点击"
        except Exception as error:
            self.apps.pop("PowerPoint.Application",None)
            self.diagnostic_error = f"{type(error).__name__}: {error}"
            return None,docs,"PowerPoint 接口不可用，翻页已暂停"
        return None,docs,reason


class OfficeWorker(threading.Thread):
    """租约、会话标识和短时事件队列；不补发、不自动重试。"""

    def __init__(self, safe_mode=False, adapter_factory=None, automatic=False):
        super().__init__(name="office-context",daemon=True)
        self.automatic = automatic
        self.safe_mode = safe_mode
        self.adapter_factory = adapter_factory or (lambda: WindowsOfficeAdapter(safe_mode))
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.status = OfficeStatus()
        self.owner = ""
        self.lease_ns = 0
        self.epoch = uuid4().hex
        self.word_key = ""
        self.events = queue.Queue(maxsize=1)
        self.faulted = False

    def snapshot(self):
        with self.lock:
            s = self.status
            if not self.faulted and time.monotonic_ns()-s.checked_ns > 500_000_000:
                return replace(s,token="",message="Office 等待响应，控制已暂停")
            return s

    def authorize(self, owner, observed_ns):
        with self.lock:
            if owner != self.owner:
                self.epoch = uuid4().hex
                self.status = replace(self.status,token="")
            self.owner, self.lease_ns = owner, observed_ns

    def revoke(self):
        self.authorize("",0)

    def bind_word(self, key):
        with self.lock:
            self.word_key = key
            self.epoch = uuid4().hex
            self.status = replace(self.status,token="")

    def submit(self, event):
        try:
            self.events.put_nowait(event)
        except queue.Full:
            pass

    def stop(self):
        self.revoke()
        self.stop_event.set()

    def run(self):
        adapter = None
        try:
            adapter = self.adapter_factory()
            while not self.stop_event.is_set():
                with self.lock:
                    epoch, word = self.epoch, self.word_key
                target, docs, reason = adapter.scan_auto() if self.automatic else adapter.scan(word)
                now = time.monotonic_ns()
                with self.lock:
                    if epoch != self.epoch:
                        continue
                    if target != self.status.target:
                        self.epoch = uuid4().hex
                    token = (self.epoch if target and self.owner
                             and 0 <= now-self.lease_ns < 200_000_000 else "")
                    self.status = OfficeStatus(token,target,docs,reason,now,
                                               self.status.sent,self.status.latency_ms)
                try:
                    event = self.events.get(timeout=.04)
                except queue.Empty:
                    continue
                # COM 查询耗时后也必须重新检查租约和事件年龄。
                fresh, _, _ = adapter.scan_auto() if self.automatic else adapter.scan(word)
                with self.lock:
                    now = time.monotonic_ns()
                    valid = (not self.stop_event.is_set() and self.owner and token
                             and event.session_id == self.epoch == token
                             and fresh == target and self.word_key == word
                             and 0 <= now-event.timestamp_ns < 200_000_000
                             and 0 <= now-self.lease_ns < 200_000_000)
                if valid and adapter.execute(target,event.direction):
                    with self.lock:
                        self.status = replace(self.status,sent=self.status.sent+1,
                            latency_ms=(time.monotonic_ns()-event.timestamp_ns)/1e6)
        except Exception:
            self.faulted = True
            with self.lock:
                self.status = replace(self.status,token="",target=None,
                    message="Office 接口异常，自动翻页已暂停；请停止后重新启动控制",
                    checked_ns=time.monotonic_ns())
        finally:
            self.revoke()
            if adapter is not None:
                adapter.close()
