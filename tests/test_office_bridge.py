"""使用假 Office 验证授权时效，绝不发送真实按键。"""
import threading
import time
from gesture_mouse.office_bridge import OfficeWorker,OfficeTarget
from gesture_mouse.classroom import PresentationEvent


class FakeOffice:
    def __init__(self):
        self.target = OfficeTarget("ppt","show-a",12,"演示")
        self.calls = []
        self.closed = False
    def scan(self,word): return self.target,(),"测试"
    def execute(self,target,direction):
        self.calls.append((target,direction))
        return True
    def close(self): self.closed = True


def wait_for(predicate,timeout=1):
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        if predicate(): return
        time.sleep(.005)
    assert predicate()


def worker():
    adapter = FakeOffice()
    w = OfficeWorker(adapter_factory=lambda:adapter)
    w.authorize("teacher",time.monotonic_ns())
    w.start()
    wait_for(lambda:bool(w.snapshot().token))
    return w,adapter


def shutdown(w):
    w.stop(); w.join(1)
    assert not w.is_alive()


def test_valid_event_once():
    w,a = worker()
    try:
        w.submit(PresentationEvent(w.snapshot().token,time.monotonic_ns(),1))
        wait_for(lambda:bool(a.calls))
        assert len(a.calls) == 1
    finally: shutdown(w)
    assert a.closed


def test_expired_event_and_old_teacher_never_sent():
    w,a = worker()
    try:
        token = w.snapshot().token
        w.submit(PresentationEvent(token,time.monotonic_ns()-210_000_000,1))
        time.sleep(.06)
        w.authorize("other-teacher",time.monotonic_ns())
        w.submit(PresentationEvent(token,time.monotonic_ns(),1))
        time.sleep(.06)
        assert not a.calls
    finally: shutdown(w)


def test_pause_and_foreground_change_never_sent():
    w,a = worker()
    try:
        token = w.snapshot().token
        w.revoke()
        w.submit(PresentationEvent(token,time.monotonic_ns(),1))
        time.sleep(.06)
        assert not a.calls
        w.authorize("teacher",time.monotonic_ns())
        wait_for(lambda:bool(w.snapshot().token))
        token = w.snapshot().token
        a.target = None
        w.submit(PresentationEvent(token,time.monotonic_ns(),1))
        time.sleep(.06)
        assert not a.calls
    finally: shutdown(w)


def test_hung_scan_does_not_block_revoke():
    w,a = worker()
    gate = threading.Event()
    original = a.scan
    try:
        token = w.snapshot().token
        a.scan = lambda word: (gate.wait(1),original(word))[1]
        w.submit(PresentationEvent(token,time.monotonic_ns(),1))
        start = time.monotonic()
        w.revoke()
        assert time.monotonic()-start < .1
        time.sleep(.22); gate.set(); time.sleep(.08)
        assert not a.calls
    finally:
        gate.set(); shutdown(w)


def test_partial_keyboard_submission_attempts_release():
    import pytest
    import os
    from types import SimpleNamespace
    from gesture_mouse.office_bridge import WindowsOfficeAdapter
    if os.name != "nt": pytest.skip("Windows 输入结构")
    calls = []
    def submit(count,values,size):
        calls.append([values[i].ki.dwFlags for i in range(count)])
        return 1
    adapter = WindowsOfficeAdapter.__new__(WindowsOfficeAdapter)
    adapter.safe_mode = False
    adapter.user32 = SimpleNamespace(GetForegroundWindow=lambda:12,SendInput=submit)
    adapter._unobstructed = lambda hwnd:True
    with pytest.raises(OSError):
        adapter.execute(OfficeTarget("ppt","test",12,"测试"),1)
    assert calls == [[0,2],[2]]
