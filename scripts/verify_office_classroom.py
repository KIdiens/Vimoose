"""使用临时未保存文档验证本机 Office；不打开或修改用户文档。"""
from __future__ import annotations
import ctypes
import json
import time
from pathlib import Path
import comtypes.client
from gesture_mouse.office_bridge import WindowsOfficeAdapter


def focus_test_window(adapter, hwnd):
    """仅验收脚本激活自己新建的测试窗口；产品代码不调用此函数。"""
    user = adapter.user32
    user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    from ctypes import wintypes
    message = wintypes.MSG()
    user.PeekMessageW(ctypes.byref(message),None,0,0,0)
    current = ctypes.windll.kernel32.GetCurrentThreadId()
    foreground = user.GetWindowThreadProcessId(user.GetForegroundWindow(),None)
    attached = bool(user.AttachThreadInput(current,foreground,True)) if current != foreground else False
    try:
        user.BringWindowToTop.argtypes = [ctypes.c_void_p]
        user.BringWindowToTop(hwnd)
        user.SetForegroundWindow(hwnd)
    finally:
        if attached: user.AttachThreadInput(current,foreground,False)
    time.sleep(.3)
    return int(user.GetForegroundWindow() or 0) == hwnd


def main():
    result = {}
    adapter = WindowsOfficeAdapter()
    ppt = word = presentation = document = extra_document = show = None
    ppt_owned = word_owned = False
    try:
        try:
            ppt = comtypes.client.GetActiveObject("PowerPoint.Application",dynamic=True)
        except Exception:
            ppt = comtypes.client.CreateObject("PowerPoint.Application",dynamic=True)
            ppt_owned = True
        ppt.Visible = True
        presentation = ppt.Presentations.Add()
        for n in range(1,4):
            slide = presentation.Slides.Add(n,12)
            shape = slide.Shapes.AddTextbox(1,60,80,500,100)
            shape.TextFrame.TextRange.Text = f"课堂集成测试：第 {n} 页（临时未保存）"
            if n == 1:
                slide.TimeLine.MainSequence.AddEffect(shape,1,0,1)
        show = presentation.SlideShowSettings.Run()
        result["ppt_properties"] = {}
        for key in ("HWND","IsFullScreen","View","Presentation"):
            try: result["ppt_properties"][key] = str(getattr(show,key))
            except Exception as error: result["ppt_properties"][key] = str(error)
        result["ppt_properties"]["version"] = str(ppt.Version)
        adapter.user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        try:
            hwnd = adapter._show_hwnd(ppt,show)
            result["ppt_properties"]["focus_result"] = focus_test_window(adapter,hwnd)
        except Exception: pass
        time.sleep(1)
        target,_,reason = adapter.scan("")
        result["ppt_context"] = {"detected":target is not None,"reason":reason,
                                 "show_hwnd":hwnd,
                                 "diagnostic":adapter.diagnostic_error,
                                 "foreground_class":adapter._class(adapter.user32.GetForegroundWindow())}
        if target:
            before = (int(show.View.CurrentShowPosition),int(show.View.GetClickIndex()))
            sent = adapter.execute(target,1)
            time.sleep(.4)
            after = (int(show.View.CurrentShowPosition),int(show.View.GetClickIndex()))
            result["ppt_animation"] = {"before":before,"after":after,"sent":sent,
                                       "passed":sent and before[0] == after[0] and after[1] > before[1]}
            sent2 = adapter.execute(target,-1)
            time.sleep(.4)
            result["ppt_previous"] = {"sent":sent2,"click":int(show.View.GetClickIndex()),
                                      "passed":sent2 and int(show.View.GetClickIndex()) < after[1]}
            show.View.GotoSlide(2)
            time.sleep(.2)
            fresh,_,_ = adapter.scan("")
            sent3 = adapter.execute(fresh,1) if fresh else False
            time.sleep(.3)
            result["ppt_plain_slide"] = {"sent":sent3,"position":int(show.View.CurrentShowPosition),
                                         "passed":sent3 and int(show.View.CurrentShowPosition) == 3}
            # 安全模式确实不推进真实演示。
            adapter.safe_mode = True
            before_safe = int(show.View.CurrentShowPosition)
            if fresh: adapter.execute(fresh,-1)
            time.sleep(.2)
            result["safe_mode_no_input"] = int(show.View.CurrentShowPosition) == before_safe
            adapter.safe_mode = False
        show.View.Exit(); show = None
        time.sleep(.2)
        target,_,_ = adapter.scan("")
        result["ppt_after_exit_rejected"] = target is None
    except Exception as e:
        result["ppt_error"] = type(e).__name__+": "+str(e)
    finally:
        if show is not None:
            try: show.View.Exit()
            except Exception: pass
        if presentation is not None:
            try: presentation.Saved = True; presentation.Close()
            except Exception: pass
        if ppt_owned and ppt is not None:
            try:
                if ppt.Presentations.Count == 0: ppt.Quit()
            except Exception: pass
    try:
        try: word = comtypes.client.GetActiveObject("Word.Application",dynamic=True)
        except Exception:
            word = comtypes.client.CreateObject("Word.Application",dynamic=True)
            word_owned = True
        word.Visible = True
        document = word.Documents.Add()
        document.Content.Text = "\n".join(f"课堂文档测试，第 {i} 行。仅用于验证翻一屏。" for i in range(1,401))
        document.Activate()
        focus_test_window(adapter,int(document.ActiveWindow.Hwnd))
        time.sleep(1)
        adapter._last_documents = 0
        docs = adapter.documents()
        target = next((d for d in docs if d.hwnd == int(document.ActiveWindow.Hwnd)),None)
        if target:
            active,_,reason = adapter.scan(target.key)
            before = int(document.ActiveWindow.VerticalPercentScrolled)
            sent = adapter.execute(active,1) if active else False
            time.sleep(.3)
            after = int(document.ActiveWindow.VerticalPercentScrolled)
            result["word_scroll"] = {"before":before,"after":after,"sent":sent,
                                    "passed":sent and after > before,"reason":reason}
            if active:
                adapter.execute(active,-1)
                time.sleep(.3)
                result["word_scroll_up"] = int(document.ActiveWindow.VerticalPercentScrolled) < after
                result["word_zoom"] = []
                for zoom in (70,100,150):
                    document.ActiveWindow.View.Zoom.Percentage = zoom
                    document.ActiveWindow.VerticalPercentScrolled = 10
                    time.sleep(.2)
                    fresh,_,_ = adapter.scan(target.key)
                    before_zoom = int(document.ActiveWindow.VerticalPercentScrolled)
                    submitted = adapter.execute(fresh,1) if fresh else False
                    time.sleep(.2)
                    after_zoom = int(document.ActiveWindow.VerticalPercentScrolled)
                    result["word_zoom"].append({"zoom":zoom,"before":before_zoom,"after":after_zoom,
                                                 "passed":submitted and after_zoom > before_zoom})
                extra_document = word.Documents.Add()
                extra_document.Content.Text = "第二个临时文档：不允许串控"
                focus_test_window(adapter,int(extra_document.ActiveWindow.Hwnd))
                fresh,_,_ = adapter.scan(target.key)
                result["word_other_document_rejected"] = fresh is None
                document.Close(0)
                document = None
                time.sleep(.6)
                fresh,docs,_ = adapter.scan(target.key)
                result["word_closed_unbound"] = fresh is None and target.key not in [d.key for d in docs]
        else: result["word_error"] = "未枚举到测试文档"
    except Exception as e:
        result["word_error"] = type(e).__name__+": "+str(e)
    finally:
        if extra_document is not None:
            try: extra_document.Close(0)
            except Exception: pass
        if document is not None:
            try: document.Close(0)
            except Exception: pass
        if word_owned and word is not None:
            try:
                if word.Documents.Count == 0: word.Quit()
            except Exception: pass
        adapter.close()
    path = Path("artifacts/classroom-0.9.0/office-integration.json")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__": main()
