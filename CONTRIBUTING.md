# 参与 Vimoose 开发

感谢关注 Vimoose。提交问题前，请先确认没有重复的 Issue，并尽量提供以下信息：

- Windows版本、显示缩放比例和摄像头型号；
- Vimoose版本、相关设置和问题发生频率；
- 可公开的复现步骤、日志或已脱敏录像；
- 预期行为与实际行为。

## 本地开发

项目使用 Python 3.11：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\download_model.ps1
.\.venv\Scripts\python.exe -m pytest
```

代码修改应遵循以下原则：

- 鼠标注入相关改动必须包含按键释放和异常退出测试；
- 手势改动应使用时序关键点序列测试，不能只测试单帧姿态；
- 默认不记录摄像头画面、关键点或个人识别信息；
- GUI必须在主线程运行，视觉推理和UI Automation不得阻塞界面线程；
- 提交前运行完整测试，并说明真人摄像头验证环境。
