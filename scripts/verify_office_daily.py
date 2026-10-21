"""仅用自己新建的临时文档实测自动 Office；结束时关闭测试文档、恢复原焦点。"""
import json
import time
import traceback
from pathlib import Path
import comtypes.client
from gesture_mouse.office_bridge import WindowsOfficeAdapter
from scripts.verify_office_classroom import focus_test_window


def main():
    a=WindowsOfficeAdapter()
    original=int(a.user32.GetForegroundWindow() or 0)
    report={}
    ppt=word=deck=doc=second=show=None
    ppt_owned=word_owned=False
    try:
        try: ppt=comtypes.client.GetActiveObject("PowerPoint.Application",dynamic=True)
        except Exception:
            ppt=comtypes.client.CreateObject("PowerPoint.Application",dynamic=True)
            ppt_owned=True
        if int(ppt.SlideShowWindows.Count):
            raise RuntimeError("有用户放映正在进行，未打断它，跳过测试")
        ppt.Visible=True
        deck=ppt.Presentations.Add()
        for n in range(1,4):
            slide=deck.Slides.Add(n,12)
            shape=slide.Shapes.AddTextbox(1,60,80,500,100)
            shape.TextFrame.TextRange.Text=f"Vimoose 自动文档测试 {n}（临时未保存）"
            if n==1: slide.TimeLine.MainSequence.AddEffect(shape,1,0,1)
        w=deck.Windows.Item(1)
        w.View.GotoSlide(1)
        edit_hwnd=a._document_hwnd(w)
        focus_test_window(a,edit_hwnd)
        target,_,reason=a.scan_auto()
        report["ppt_edit_detected"]={"kind":target.kind if target else None,"reason":reason,
                                      "diagnostic":a.diagnostic_error}
        if target:
            sent=a.execute(target,1)
            report["ppt_edit_next"]=sent and int(w.View.Slide.SlideIndex)==2
            fresh,_,_=a.scan_auto()
            report["ppt_edit_previous"]=bool(fresh and a.execute(fresh,-1)) and int(w.View.Slide.SlideIndex)==1
        show=deck.SlideShowSettings.Run()
        hwnd=a._show_hwnd(ppt,show)
        focus_test_window(a,hwnd)
        target,_,reason=a.scan_auto()
        report["ppt_show_detected"]=bool(target and target.kind=="ppt")
        if target:
            before=(int(show.View.CurrentShowPosition),int(show.View.GetClickIndex()))
            a.execute(target,1)
            time.sleep(.3)
            after=(int(show.View.CurrentShowPosition),int(show.View.GetClickIndex()))
            report["ppt_animation_step"]={"before":before,"after":after,"passed":before[0]==after[0] and after[1]>before[1]}
            show.View.GotoSlide(2)
            a.execute(target,1)
            time.sleep(.3)
            report["ppt_plain_next"]=int(show.View.CurrentShowPosition)==3
        show.View.Exit()
        show=None
        focus_test_window(a,edit_hwnd)
        fresh,_,_=a.scan_auto()
        report["show_exit_returns_to_edit"]=bool(fresh and fresh.kind=="ppt-edit")
        if target: report["old_show_target_rejected"]=not a.execute(target,1)
    except Exception as error:
        report["ppt_error"]=f"{type(error).__name__}: {error}"
        report["ppt_traceback"]=traceback.format_exc()
    finally:
        if show is not None:
            try: show.View.Exit()
            except Exception: pass
        if deck is not None:
            try: deck.Saved=True; deck.Close()
            except Exception: pass
        if ppt_owned and ppt is not None:
            try:
                if not ppt.Presentations.Count: ppt.Quit()
            except Exception: pass
    try:
        try: word=comtypes.client.GetActiveObject("Word.Application",dynamic=True)
        except Exception:
            word=comtypes.client.CreateObject("Word.Application",dynamic=True)
            word_owned=True
        word.Visible=True
        doc=word.Documents.Add()
        doc.Content.Text="\n".join(f"临时自动翻屏测试 {n}" for n in range(400))
        focus_test_window(a,int(doc.ActiveWindow.Hwnd))
        a._last_documents=0
        target,_,reason=a.scan_auto()
        report["word_auto_detected"]={"detected":bool(target and target.kind=="word"),"reason":reason}
        if target:
            before=int(doc.ActiveWindow.VerticalPercentScrolled)
            sent=a.execute(target,1)
            time.sleep(.2)
            after=int(doc.ActiveWindow.VerticalPercentScrolled)
            report["word_down"]={"before":before,"after":after,"passed":sent and after>before}
            a.execute(target,-1)
            report["word_up"]=int(doc.ActiveWindow.VerticalPercentScrolled)<after
            second=word.Documents.Add()
            second.Content.Text="第二份测试文档，不修改用户文档。"
            focus_test_window(a,int(second.ActiveWindow.Hwnd))
            time.sleep(.6)
            new,_,_=a.scan_auto()
            report["word_auto_follows_new"]=bool(new and new.key!=target.key)
            report["old_word_rejected"]=not a.execute(target,1)
    except Exception as error:
        report["word_error"]=f"{type(error).__name__}: {error}"
    finally:
        for item in (second,doc):
            if item is not None:
                try: item.Close(0)
                except Exception: pass
        if word_owned and word is not None:
            try:
                if not word.Documents.Count: word.Quit()
            except Exception: pass
        if original: focus_test_window(a,original)
        a.close()
    path=Path("artifacts/acceptance-20260907/office-daily.json")
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__": main()
