"""对完整视频的特征缓存作确定性回放；诊断文件不参与线上识别。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from gesture_mouse.classroom import ClassroomCalibration,ClassroomGestureEngine,HandFeatures


def evaluate(report, calibration, labels):
    engine = ClassroomGestureEngine(calibration)
    events = []
    for row in report["frames"]:
        f = HandFeatures(**row["features"]) if row["features"] else None
        e = engine.process(f,"离线回放")
        row["state"] = engine.state
        if e: events.append({"seconds":row["seconds"],"direction":e.direction})
    expected = labels["actions"]
    counts = [sum(a["start"] <= e["seconds"] <= a["end"] and e["direction"] == a["direction"]
                  for e in events) for a in expected]
    unexpected = [e for e in events if not any(a["start"] <= e["seconds"] <= a["end"]
                   and e["direction"] == a["direction"] for a in expected)]
    report.update(events=events,calibrated=calibration is not None,
                  acceptance={"expected":len(expected),"counts":counts,
                              "matched_once":sum(n == 1 for n in counts),
                              "unexpected":unexpected,
                              "passed":bool(expected) and calibration is not None
                              and all(n == 1 for n in counts) and not unexpected})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("features",type=Path)
    p.add_argument("--calibration",type=Path,required=True)
    p.add_argument("--labels",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a = p.parse_args()
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    calibration = ClassroomCalibration.from_mapping(load(a.calibration))
    if calibration is None: raise ValueError("校准文件不完整或无效")
    report = evaluate(load(a.features),calibration,load(a.labels))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "frames"},ensure_ascii=False))
    return 0 if report["acceptance"]["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
