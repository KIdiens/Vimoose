"""顺序解码验收录像，保存带时间码的概览和指定片段帧供人工复核。"""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("video",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--step",type=float,default=10)
    p.add_argument("--start",type=float,default=0)
    p.add_argument("--end",type=float)
    p.add_argument("--width",type=int,default=640)
    a = p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    c = cv2.VideoCapture(str(a.video))
    fps,n = c.get(5),int(c.get(7))
    if not c.isOpened() or fps <= 0: raise RuntimeError("无法解码验收视频")
    report = {"fps":fps,"frames":n,"width":c.get(3),"height":c.get(4),"duration":n/fps}
    tiles = []
    page = 0
    def save():
        nonlocal page
        while len(tiles)<6: tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,6,2)])
        cv2.imencode('.jpg',sheet)[1].tofile(str(a.output/f"overview-{page:03}.jpg"))
        tiles.clear()
        page += 1
    frame_idx,next_time = 0,a.start
    while c.grab():
        t = frame_idx/fps
        frame_idx += 1
        if a.end is not None and t>a.end: break
        if t<next_time: continue
        ok,frame = c.retrieve()
        if not ok: continue
        next_time += a.step
        if a.step < 2:
            cv2.imencode('.jpg',frame)[1].tofile(str(a.output/f"frame-{t:08.3f}.jpg"))
        frame=cv2.resize(frame,(a.width,round(frame.shape[0]*a.width/frame.shape[1])))
        cv2.rectangle(frame,(0,0),(190,35),(0,0,0),-1)
        cv2.putText(frame,f"{t:.3f}s",(8,26),cv2.FONT_HERSHEY_SIMPLEX,.8,(255,255,255),2)
        tiles.append(frame)
        if len(tiles)==6: save()
    if tiles: save()
    c.release()
    report["decoded_frames"] = frame_idx
    (a.output/"metadata.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__": main()
