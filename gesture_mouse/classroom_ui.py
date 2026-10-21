"""嵌入原控制台的课堂面板、预览选择和无焦点提示。"""

from __future__ import annotations

import copy
from PySide6.QtCore import QObject, QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QScrollArea,QMessageBox,
)


def preview_position(label, position):
    """将含黑边的 QLabel 位置映射为真实画面归一化坐标。"""
    pix = label.pixmap()
    if pix is None or pix.isNull():
        return None
    size = pix.deviceIndependentSize()
    left = (label.width()-size.width())/2
    top = (label.height()-size.height())/2
    x,y = (position.x()-left)/size.width(), (position.y()-top)/size.height()
    return (x,y) if 0 <= x <= 1 and 0 <= y <= 1 else None


class ClassroomPanel(QScrollArea):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pipeline = window.pipeline
        self.drag_start = None
        self.region_mode = False
        self._doc_keys = ()
        self.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        title = QLabel("课堂演示")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        layout.addWidget(title)
        intro = QLabel("讲台摄像头 1～3 米 · 只控制选定老师的一只手\n左摆下一步，右摆上一步；回正不翻页。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.mode = QPushButton("启用课堂模式")
        self.mode.setCheckable(True)
        self.mode.setChecked(window.config.classroom_enabled)
        self.mode.setAccessibleName("切换课堂演示与普通鼠标模式")
        self.mode.clicked.connect(self.change_mode)
        layout.addWidget(self.mode)
        self.hand = QComboBox()
        self.hand.addItem("右手控制","Right")
        self.hand.addItem("左手控制","Left")
        self.hand.setCurrentIndex(0 if window.config.classroom_hand == "Right" else 1)
        self.hand.setAccessibleName("教师唯一控制手")
        self.hand.currentIndexChanged.connect(self.change_hand)
        layout.addWidget(QLabel("1. 选择控制手与讲台有效区"))
        layout.addWidget(self.hand)
        region_row = QHBoxLayout()
        self.region = QPushButton("在预览中拖动框选讲台")
        self.region.setCheckable(True)
        self.region.toggled.connect(self.set_region_mode)
        reset = QPushButton("全画面")
        reset.clicked.connect(lambda: self.save_region([0.,0.,1.,1.]))
        region_row.addWidget(self.region)
        region_row.addWidget(reset)
        layout.addLayout(region_row)
        instruction = QLabel("2. 启动控制，在左侧预览中点击老师胸肩区域。\n多人重叠时不能接管；重新点选将取消上一身份。")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.calibrate = QPushButton("3. 校准正掌与左右各三次动作")
        self.calibrate.clicked.connect(lambda: self.pipeline.classroom.calibrate())
        layout.addWidget(self.calibrate)
        cancel = QPushButton("取消校准／暂停课堂")
        cancel.clicked.connect(lambda: self.pipeline.set_paused(True))
        layout.addWidget(cancel)
        rule = QLabel("4. PPT 全屏自动待命；Word 请在下方绑定文档。\n切回演示窗口后正掌准备，校准期间不会翻页。")
        rule.setWordWrap(True)
        layout.addWidget(rule)
        self.documents = QComboBox()
        self.documents.addItem("不绑定 Word 文档","")
        self.documents.setAccessibleName("课堂演示目标 Word 文档")
        self.documents.currentIndexChanged.connect(self.bind_word)
        layout.addWidget(self.documents)
        self.status = QLabel("待启动")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(78)
        self.status.setStyleSheet("background:#122238;border:1px solid #34516F;padding:12px;color:#F8FAFC;")
        self.status.setAccessibleName("课堂状态及暂停原因")
        layout.addWidget(self.status)
        self.sent = QLabel("已提交 0 次操作")
        layout.addWidget(self.sent)
        help_label = QLabel("Ctrl+Alt+G 暂停／恢复\nCtrl+Alt+Esc 紧急停止\n人体跟踪丢失后必须重新点选老师。")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        layout.addStretch()
        self.setWidget(content)
        window.preview_label.installEventFilter(self)
        self.overlay = QLabel("课堂待命",window,Qt.WindowType.Tool |
                              Qt.WindowType.FramelessWindowHint |
                              Qt.WindowType.WindowStaysOnTopHint |
                              Qt.WindowType.WindowDoesNotAcceptFocus)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.setWindowFlag(Qt.WindowType.WindowTransparentForInput,True)
        self.overlay.setWordWrap(True)
        self.overlay.setFixedWidth(340)
        self.overlay.setStyleSheet("background:#122238;color:#F8FAFC;border:1px solid #2DD4BF;padding:10px;")
        self.overlay.move(24,24)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(100)

    def save(self, config):
        self.window.config = config
        self.window.config_store.save(config)
        self.pipeline.update_config(config)

    def change_mode(self, checked):
        config = copy.deepcopy(self.window.config)
        config.classroom_enabled = checked
        if checked:
            config.preview_enabled = True
        self.save(config)
        if checked:
            self.window.tabs.setCurrentWidget(self)

    def change_hand(self):
        config = copy.deepcopy(self.window.config)
        config.classroom_hand = self.hand.currentData()
        config.classroom_calibration = {}
        config.classroom_camera_signature = ""
        self.save(config)

    def set_region_mode(self, checked):
        self.region_mode = checked
        self.drag_start = None
        if checked:
            self.pipeline.set_paused(True)

    def save_region(self, region):
        config = copy.deepcopy(self.window.config)
        config.classroom_region = region
        self.region.setChecked(False)
        self.save(config)

    def eventFilter(self, obj, event):
        if obj is self.window.preview_label and self.window.config.classroom_enabled:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                p = preview_position(obj,event.position())
                if p:
                    if self.region_mode:
                        self.drag_start = p
                    else:
                        self.pipeline.classroom.select(*p)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self.region_mode:
                p = preview_position(obj,event.position())
                if p and self.drag_start:
                    x,y = self.drag_start
                    r = [min(x,p[0]),min(y,p[1]),max(x,p[0]),max(y,p[1])]
                    if r[2]-r[0] >= .1 and r[3]-r[1] >= .1:
                        self.save_region(r)
                self.drag_start = None
                return True
        return super().eventFilter(obj,event)

    def bind_word(self):
        self.pipeline.classroom.office.bind_word(self.documents.currentData() or "")

    def refresh(self):
        enabled = self.window.config.classroom_enabled
        runtime = self.pipeline.classroom
        state, office = runtime.snapshot(),runtime.office.snapshot()
        self.mode.blockSignals(True)
        self.mode.setChecked(enabled)
        self.mode.setText("课堂模式已启用（点击返回普通模式）" if enabled else "启用课堂模式")
        self.mode.blockSignals(False)
        self.region.setEnabled(enabled)
        self.calibrate.setEnabled(enabled and self.pipeline.running and bool(state["teacher_id"]))
        self.status.setText(state["message"] if enabled and self.pipeline.running else "课堂未运行；启用后点击顶部“启动控制”")
        self.sent.setText(f"已提交 {office.sent} 次操作 · 最近提交延迟 {office.latency_ms:.0f} ms")
        keys = tuple(d.key for d in office.documents)
        if keys != self._doc_keys:
            previous = self.documents.currentData()
            self.documents.blockSignals(True)
            self.documents.clear()
            self.documents.addItem("不绑定 Word 文档","")
            for d in office.documents:
                self.documents.addItem(d.label,d.key)
            self.documents.setCurrentIndex(max(0,self.documents.findData(previous)))
            self.documents.blockSignals(False)
            self._doc_keys = keys
        completed = runtime.consume_calibration()
        if completed:
            # 保存校准不重启摄像头，不丢掉已经确认的教师身份。
            config = self.window.config
            config.classroom_calibration = completed
            config.classroom_camera_signature = config.classroom_signature()
            self.window.config_store.save(config)
        self.overlay.setText("课堂 · "+self.status.text())
        self.overlay.adjustSize()
        self.overlay.setVisible(enabled and self.pipeline.running and not self.window.isActiveWindow())

    def draw_overlay(self, frame):
        import cv2
        state = self.pipeline.classroom.snapshot()
        h,w = frame.shape[:2]
        l,t,r,b = self.window.config.classroom_region
        cv2.rectangle(frame,(round(l*w),round(t*h)),(round(r*w),round(b*h)),(210,203,45),2)
        for person in state["bodies"]:
            l,t,r,b = person.box
            locked = person == state["locked"]
            color = (80,220,100) if locked else (190,180,140)
            cv2.rectangle(frame,(round(l*w),round(t*h)),(round(r*w),round(b*h)),color,2)
            for a,b in ((11,12),(11,13),(13,15),(12,14),(14,16)):
                if min(person.visibility[a],person.visibility[b]) >= .5:
                    p,q = person.points[a],person.points[b]
                    cv2.line(frame,(round(p.x*w),round(p.y*h)),(round(q.x*w),round(q.y*h)),color,2)
