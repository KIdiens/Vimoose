const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  HeadingLevel,
  ImageRun,
  LevelFormat,
  PageBreak,
  PageNumber,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  VerticalAlign,
  WidthType,
} = require("docx");

const ROOT = path.resolve(__dirname, "..");
const OUTPUT = path.join(ROOT, "Vimoose_UI设计AI完整交接包_V0.8.5_2026-08-04.docx");
const IMAGE_DIR = path.join(ROOT, "artifacts", "ui-handoff-v085");
const CONTENT_WIDTH = 9026;

const C = {
  navy: "07111F",
  surface: "0D1929",
  raised: "122238",
  soft: "16283E",
  border: "263B53",
  borderStrong: "34516F",
  text: "F8FAFC",
  subtle: "A5B4C7",
  muted: "71849B",
  teal: "2DD4BF",
  cyan: "38BDF8",
  green: "34D399",
  amber: "FBBF24",
  rose: "FB7185",
  white: "FFFFFF",
  ink: "162033",
  body: "334155",
  line: "D9E2EC",
  pale: "F4F7FA",
  paleTeal: "E9FBF8",
  paleBlue: "EAF6FD",
  paleAmber: "FFF8E5",
  paleRose: "FFF0F3",
};

const border = { style: BorderStyle.SINGLE, size: 1, color: C.line };
const borders = { top: border, bottom: border, left: border, right: border };

function run(text, options = {}) {
  return new TextRun({ text, font: "Microsoft YaHei", color: C.body, size: 20, ...options });
}

function p(text = "", options = {}) {
  const children = Array.isArray(text) ? text : [run(text, options.run || {})];
  return new Paragraph({
    children,
    spacing: { after: 110, line: 320 },
    ...options,
  });
}

function heading(text, level = 1) {
  return new Paragraph({
    heading: level === 1 ? HeadingLevel.HEADING_1 : level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3,
    children: [run(text, { bold: true, color: level === 1 ? C.ink : C.body })],
  });
}

function bullet(text, level = 0, reference = "bullet-main") {
  return new Paragraph({
    numbering: { reference, level },
    children: [run(text)],
    spacing: { after: 70, line: 300 },
  });
}

function callout(title, body, fill = C.paleTeal, accent = C.teal) {
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [220, CONTENT_WIDTH - 220],
    rows: [
      new TableRow({
        children: [
          new TableCell({
            width: { size: 220, type: WidthType.DXA },
            shading: { fill: accent, type: ShadingType.CLEAR },
            borders: { top: border, bottom: border, left: border, right: { style: BorderStyle.NONE, size: 0, color: fill } },
            children: [p("")],
          }),
          new TableCell({
            width: { size: CONTENT_WIDTH - 220, type: WidthType.DXA },
            shading: { fill, type: ShadingType.CLEAR },
            borders: { top: border, bottom: border, right: border, left: { style: BorderStyle.NONE, size: 0, color: fill } },
            margins: { top: 140, bottom: 120, left: 180, right: 180 },
            children: [
              p([run(title, { bold: true, color: C.ink, size: 21 })], { spacing: { after: 50 } }),
              p(body, { spacing: { after: 0, line: 300 } }),
            ],
          }),
        ],
      }),
    ],
  });
}

function table(headers, rows, widths, options = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const headerFill = options.headerFill || C.soft;
  const headerColor = options.headerColor || C.white;
  const allRows = [
    new TableRow({
      tableHeader: true,
      cantSplit: true,
      children: headers.map((text, i) => new TableCell({
        width: { size: widths[i], type: WidthType.DXA },
        shading: { fill: headerFill, type: ShadingType.CLEAR },
        borders,
        margins: { top: 100, bottom: 100, left: 110, right: 110 },
        verticalAlign: VerticalAlign.CENTER,
        children: [p([run(text, { bold: true, color: headerColor, size: 18 })], { spacing: { after: 0 }, alignment: AlignmentType.CENTER })],
      })),
    }),
    ...rows.map((row, rowIndex) => new TableRow({
      cantSplit: true,
      children: row.map((value, i) => new TableCell({
        width: { size: widths[i], type: WidthType.DXA },
        shading: { fill: rowIndex % 2 === 0 ? C.white : C.pale, type: ShadingType.CLEAR },
        borders,
        margins: { top: 90, bottom: 90, left: 110, right: 110 },
        verticalAlign: VerticalAlign.CENTER,
        children: Array.isArray(value)
          ? value
          : [p(String(value), { spacing: { after: 0, line: 280 }, run: { size: 17 } })],
      })),
    })),
  ];
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: allRows,
  });
}

function imageBlock(file, title, description, width = 570) {
  const full = path.join(IMAGE_DIR, file);
  const data = fs.readFileSync(full);
  // PNG 的 IHDR 从第16字节开始保存宽高，按真实比例嵌入，避免窗口截图被压扁。
  const sourceWidth = data.readUInt32BE(16);
  const sourceHeight = data.readUInt32BE(20);
  const height = Math.round(width * sourceHeight / sourceWidth);
  return [
    p([run(title, { bold: true, color: C.ink, size: 22 })], { spacing: { before: 120, after: 80 } }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new ImageRun({
        type: "png",
        data,
        transformation: { width, height },
        altText: { title, description, name: title },
      })],
      spacing: { after: 80 },
    }),
    p(description, { alignment: AlignmentType.CENTER, spacing: { after: 140 }, run: { size: 17, color: C.muted, italics: true } }),
  ];
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

const functions = [
  ["光标移动", "完整手部可用时，以8号食指指尖为锚点；自然微弯、侧手和中指半伸仍允许移动。", "持续"],
  ["左键单击", "拇指与食指捏合，松开后触发；靠近阶段先锁定点击位置；一次点击后必须重新张开才允许下一次。", "已实现"],
  ["双击", "连续两次短捏合；双击窗口交由Windows系统判断。", "已实现"],
  ["拖拽", "食指捏合持续达到默认2000ms后发送左键按下；松开、越界、失联、异常或退出均释放。", "已实现"],
  ["右键单击", "拇指与中指先张开、再主动靠近并捏合，松开后触发；0.8.5允许中指在120ms内完成前伸，不支持右键拖拽。", "已实现"],
  ["滚轮", "张开手掌上下平移，或张掌后前后翻腕；滚动期间不移动光标。", "已实现"],
  ["翻页", "张掌水平挥动：向左发送PageDown，向右发送PageUp；一次动作只触发一页。", "已实现"],
  ["暂停/恢复", "握拳保持500ms切换，也可用按钮、托盘或Ctrl+Alt+G。", "已实现"],
  ["紧急停止", "Ctrl+Alt+Esc或红色按钮：停止注入并强制释放鼠标按键。", "安全关键"],
  ["控件磁吸", "利用Windows UI Automation吸附到按钮、复选框、菜单、链接及浏览器标签关闭点；只吸附，不自动点击。", "可关闭"],
  ["局部单指续跟踪", "完整手部部分出框后，继承食指或中指身份；只有食指可继续移动。", "可关闭"],
  ["三步校准", "采集自然张开、轻捏合、静止指向，计算捏合滞回和光标手感参数；确认后才保存。", "已实现"],
];

const gestureRows = [
  ["食指指向/一般完整手部", "光标移动", "实时连续", "8号食指；安全活动区映射全屏"],
  ["拇指靠近食指或中指", "点击位置锁定", "进入接近阈值", "立即停止未完成的光标插值"],
  ["拇指+食指短捏合", "左键单击", "松开时", "默认不在按下瞬间点击"],
  ["连续两次短捏合", "双击", "由Windows双击时间判断", "软件不另设固定窗口"],
  ["拇指+食指持续捏合", "拖拽", "默认2000ms", "先LEFT_DOWN，移动，松开LEFT_UP"],
  ["拇指+中指主动捏合", "右键", "松开时", "需“先张开、再靠近”；允许120ms前伸宽限"],
  ["张掌上下平移", "滚轮", "超过0.12掌宽", "每次最多约3格；速度默认100%"],
  ["张掌前后翻腕", "滚轮", "相对深度变化0.18", "可在设置中关闭"],
  ["张掌水平挥动", "翻页", "超过0.70掌宽", "向左下一页，向右上一页"],
  ["握拳", "暂停/恢复", "保持500ms", "捏合冲突区优先处理点击/拖拽"],
  ["手部丢失/数据超时", "停止控制并释放", "超过200ms", "离散手势需完整手部稳定1000ms后重启"],
];

const visibleParams = [
  ["摄像头编号", "0", "0–9", "选择摄像头设备"],
  ["操作手", "任意手（推荐）", "任意/右/左", "过滤允许控制的手"],
  ["检测门槛", "40%", "25%–75%", "降低可提高召回；复杂背景可适度提高"],
  ["识别增强", "115%", "100%–135%", "中央温和放大，改善远手/小手检出"],
  ["稳定性", "58%", "0%–100%", "越高静止越稳，但可能增加跟随感"],
  ["响应速度", "82%", "0%–100%", "越高快速移动越跟手"],
  ["丝滑过渡", "42ms", "12–60ms", "在相邻视觉帧之间补充轨迹"],
  ["捏合灵敏度", "42%", "28%–68%", "越高越容易在不紧贴时触发"],
  ["滚轮速度", "100%", "20%–300%", "缩放滚轮增量"],
  ["全屏覆盖", "20%", "8%–28%", "越高，越小手部行程覆盖全屏"],
  ["拖拽长按", "2000ms", "1000–8000ms", "持续捏合达到时长后进入拖拽"],
  ["控件磁吸", "开启", "开/关", "吸附到可点击位置，不自动点击"],
  ["吸附半径", "30px", "12–60px", "控件磁吸的触发范围"],
  ["张掌翻页", "开启", "开/关", "左右挥动发送PageDown/PageUp"],
  ["翻腕辅助", "开启", "开/关", "指向时保持移动，张掌时滚轮"],
  ["局部单指续跟踪", "开启", "开/关", "部分出框后继续继承食指/中指"],
  ["实时摄像头预览", "开启", "开/关", "关闭预览不停止本地识别"],
  ["登录Windows后启动", "关闭", "开/关", "当前用户级开机自启"],
  ["启动后自动控制", "关闭", "开/关", "默认要求用户主动启动"],
];

const advancedParams = [
  ["camera_width × camera_height", "640 × 480", "最低320 × 240", "摄像头采集分辨率"],
  ["camera_fps", "30", "5–60", "摄像头请求帧率"],
  ["mirror", "true", "布尔", "镜像预览与控制"],
  ["ema_alpha / fast_alpha", "0.30 / 0.72", "0.05–0.95 / ≥EMA且≤0.98", "兼容与动态平滑底层参数"],
  ["pointer_margin_x / y", "0.20 / 0.16", "0–0.40", "蓝色光标活动区边界"],
  ["pointer_edge_override", "true", "布尔", "安全区边缘直接映射屏幕边缘"],
  ["pinch_engage", "0.42", "0.10–1.00", "进入捏合阈值，按掌宽与掌长组合的稳健手部尺度归一化"],
  ["pinch_release", "0.55", "≥engage+0.02，≤1.20", "退出捏合阈值，形成滞回"],
  ["pinch_arm", "0.72", "≥release+0.05，≤1.40", "点击位置锁定/右键预备阈值"],
  ["right_pinch_approach_delta", "0.22", "0.10–0.60", "右键“主动靠近”最小变化"],
  ["fist_hold_ms", "500ms", "300–1500ms", "握拳切换暂停"],
  ["hand_lost_ms", "200ms", "100–1000ms", "手部失联保护"],
  ["scroll_threshold", "0.12", "0.03–0.60", "张掌垂直移动阈值"],
  ["palm_rotation_threshold", "0.18", "0.08–0.60", "翻腕辅助阈值"],
  ["page_swipe_threshold", "0.70", "0.35–1.50", "水平翻页阈值"],
  ["partial_tracking_frames", "0", "0–600", "0代表按光流质量决定寿命"],
  ["presence / tracking", "0.35 / 0.40", "0.25–0.90", "MediaPipe存在/跟踪置信度"],
  ["preview_fps", "15fps", "5–30fps", "GUI预览刷新上限"],
  ["配置版本", "9", "内部版本", "旧配置按版本迁移"],
];

const gestureSafetyParams = [
  ["离散手势重新武装", "1000ms", "越界或失联后需完整手部持续稳定，期间仍允许移动光标"],
  ["左键接触确认", "45ms", "浅接触需持续确认；深接触可更快成立"],
  ["左键深接触系数", "0.80 × pinch_engage", "明显捏合时缩短低帧率下的确认等待"],
  ["左键接触最大光标跳变", "0.18（归一化）", "身份可疑且跳变过大时拒绝点击"],
  ["左键最小食指身份跨度", "0.52（稳健手尺度）", "降低折叠/遮挡造成的错误指尖身份"],
  ["右键中指前伸阈值", "0.75；宽限0.55", "中指必须保持主动前伸，宽限只接受接近有效姿态"],
  ["右键中指关节角", "80°；宽限68°", "折叠中指不进入右键；接近有效姿态可短暂等待"],
  ["右键食指伸展跨度", "1.20（稳健手尺度）", "避免张掌收成指向时误锁右键"],
  ["右键前伸宽限", "120ms", "等待期间进入点击位置锁定，不输出光标移动"],
  ["右键释放确认", "25ms", "抑制单帧尺度波动造成的重复右键"],
  ["控制数据最大年龄", "100ms", "过期异步结果不得继续驱动鼠标"],
  ["翻腕接续窗口", "350ms", "指向/张掌旋转证据的短时连续性保护"],
];

const stateRows = [
  ["已停止", "程序未控制鼠标", "灰蓝", "启动控制"],
  ["控制中", "识别与注入正常", "绿色", "暂停/停止/紧急停止"],
  ["已暂停", "停止鼠标注入，可继续低频识别", "黄色", "恢复"],
  ["无画面", "摄像头打开但无有效视频", "红色", "启动视频源或切换摄像头"],
  ["摄像头异常", "设备断开或打开失败", "红色", "重新连接摄像头"],
  ["未检测到手", "超过200ms无有效手部", "状态文本", "立即释放左键；重新入镜"],
  ["点击位置锁定", "手指接近捏合、等待接触", "手势主卡片", "保持位置或松开"],
  ["正在拖拽", "左键已按下", "手势主卡片", "松开/越界/失联均释放"],
];

const colorRows = [
  ["页面背景", "#07111F", "深海军蓝"],
  ["卡片表面", "#0D1929 / #122238 / #16283E", "三层深色表面"],
  ["边框", "#263B53 / #34516F", "普通/强调边界"],
  ["主文字", "#F8FAFC", "高对比白"],
  ["次要文字", "#A5B4C7 / #71849B", "说明/弱化"],
  ["主强调", "#2DD4BF", "青绿色，按钮/进度/焦点"],
  ["辅助蓝", "#38BDF8", "识别框/信息"],
  ["成功/警告/危险", "#34D399 / #FBBF24 / #FB7185", "运行、提醒、紧急停止"],
];

const children = [];

children.push(
  new Paragraph({ spacing: { before: 1200, after: 220 }, children: [run("VIMOOSE", { bold: true, color: C.teal, size: 30, characterSpacing: 120 })] }),
  new Paragraph({ spacing: { after: 160 }, children: [run("UI 重新设计交接说明", { bold: true, color: C.ink, size: 50 })] }),
  new Paragraph({ spacing: { after: 420 }, children: [run("当前界面原貌 · 产品功能 · 手势状态 · 参数规格 · 设计约束", { color: C.muted, size: 23 })] }),
  callout("交给设计 AI 的唯一事实源", "请先完整阅读本文件，再进行界面重设计。截图表示当前0.8.5源码的真实布局；功能、参数和限制来自当前代码及发布说明。用户可见参数与高级参数合计覆盖AppConfig全部40个持久化配置字段，并单列0.8.5内部防误触阈值。不得删除紧急停止、状态反馈、隐私提示和错误恢复入口。", C.paleTeal, C.teal),
  new Paragraph({ spacing: { before: 1300, after: 120 }, children: [run("产品版本：0.8.5", { bold: true, color: C.body, size: 22 })] }),
  p("文档版本：1.3　｜　整理日期：2026-08-04　｜　目标平台：Windows 10/11 x64", { run: { size: 19, color: C.muted } }),
  p("交付格式：可解析、可编辑的 Word 文档；内含当前界面截图。", { run: { size: 19, color: C.muted } }),
  pageBreak(),
);

children.push(
  heading("0. 给设计 AI 的任务指令", 1),
  callout("建议直接复制给设计 AI", "请基于本文件为Vimoose设计一套更清晰、专业、易实现的Windows桌面UI。先输出信息架构、关键流程和设计系统，再输出控制台、设置、校准、暂停/失联/摄像头异常等状态稿。设计必须适配PySide6，不依赖网页特效，并保留所有安全入口与参数语义。", C.paleBlue, C.cyan),
  heading("设计目标", 2),
  bullet("让用户在3秒内看清：是否正在控制、当前识别到什么、是否安全、下一步该做什么。"),
  bullet("把高频控制与低频高级参数分层，降低当前设置页的滚动和认知负担。"),
  bullet("让手势学习、实时反馈和错误恢复形成完整闭环，而不是只展示技术指标。"),
  bullet("保留Vimoose“深色、精密、实时视觉”的品牌性格，但避免控制台信息堆叠。"),
  heading("期望设计 AI 输出", 2),
  bullet("信息架构与用户流程图：首次启动、正常控制、暂停、失联、异常、校准。"),
  bullet("至少5个高保真视图：主控制台、识别设置、手势设置、校准向导、异常/安全状态。"),
  bullet("完整组件状态：默认、悬停、聚焦、按下、禁用、加载、成功、警告、错误。"),
  bullet("设计令牌：颜色、字体、字号、间距、圆角、描边、阴影、动效时长。"),
  bullet("PySide6可实现的布局尺寸与交互标注；说明哪些组件折叠、分组或进入高级设置。"),
  bullet("无障碍说明：键盘顺序、可见焦点、文本对比度、不能仅靠颜色表达状态。"),
  pageBreak(),
);

children.push(
  heading("1. 产品概览", 1),
  p("Vimoose由Vision与Mouse组合而来，是一款使用普通摄像头、完全本地运行的视觉手势鼠标。它通过MediaPipe Hand Landmarker识别单手21个关键点，再调用Windows SendInput完成系统鼠标操作。本文档描述的是当前0.8.5源码与现有桌面界面，不是概念稿。"),
  table(["项目", "当前事实"], [
    ["定位", "无接触式Windows鼠标控制工具，强调稳定性、防误触和安全退出"],
    ["核心用户", "智慧展厅/PPT演示/无菌环境用户、肢体辅助操作用户、计算机视觉学习者"],
    ["技术栈", "Python 3.10–3.12（开发固定3.11）、OpenCV、MediaPipe 0.10.21、PySide6 6.11.1、Windows SendInput"],
    ["运行方式", "Windows 10/11 x64，普通用户权限，当前用户级安装"],
    ["数据策略", "默认离线；不上传、不保存视频、截图或关键点历史"],
    ["首版边界", "单摄像头、单手、主显示器；不含多显示器、双手、自定义手势、语音和跨平台"],
    ["权限边界", "普通权限程序不能控制更高完整性级别的管理员窗口"],
  ], [2100, 6926]),
  heading("产品价值", 2),
  bullet("普通摄像头即可使用，不需要深度相机或专用传感器。"),
  bullet("不是单帧手势Demo：有时序状态机、滞回、防误触、点击重新武装、失联释放和完整手部稳定重启。"),
  bullet("捏合、滚动和握拳使用掌宽与掌长组合的稳健尺度，降低侧手时掌宽投影变窄造成的漏识别与误滚动。"),
  bullet("光标采用动态平滑和最高约125Hz的帧间轨迹输出，兼顾静止稳定与快速响应。"),
  bullet("Windows控件磁吸改善小按钮、标签关闭叉号和菜单项的可点击性。"),
  pageBreak(),
);

children.push(
  heading("2. 当前软件原本长什么样", 1),
  p("当前界面是1280×820的深色双栏桌面控制台，窗口最小尺寸1060×700。左侧始终显示摄像头预览和入镜引导，右侧通过“控制台 / 识别与设置”页签切换。顶部固定放置运行状态、暂停、启动/停止和紧急停止。"),
  ...imageBlock("ui-main.png", "2.1 当前主控制台", "当前0.8.5界面离屏渲染。未启动控制，因此预览与性能指标为占位/空闲状态。"),
  ...imageBlock("ui-settings.png", "2.2 设置页顶部", "摄像头、操作手、检测门槛、识别增强、三步校准与光标手感。"),
  ...imageBlock("ui-settings-middle.png", "2.3 设置页中段", "当前默认拖拽长按已是2000ms；包括控件磁吸与扩展手势入口。"),
  ...imageBlock("ui-settings-extensions.png", "2.4 设置页底部", "扩展手势、预览、自启、自动控制、恢复默认和保存应用。"),
  pageBreak(),
);

children.push(
  heading("3. 当前界面结构与视觉语言", 1),
  heading("3.1 信息架构", 2),
  table(["区域", "包含内容", "使用频率"], [
    ["全局顶部栏", "品牌、运行状态、暂停、启动/停止、紧急停止", "高频/安全关键"],
    ["左侧实时视觉", "摄像头画面、关键点、识别增强框、光标活动区、光照状态、入镜步骤、快捷键", "持续查看"],
    ["控制台页", "当前手势、识别质量、采集/推理FPS、延迟、CPU/内存、丢帧、快捷手势、重新连接", "高频诊断"],
    ["识别与设置页", "摄像头、操作手、检测、识别增强、校准、手感、磁吸、扩展手势、启动与显示", "低频设置"],
    ["系统托盘", "显示窗口、暂停/恢复、安全退出", "后台运行"],
    ["校准对话框", "三步采样、进度、结果预览、应用/取消", "按需"],
  ], [1700, 5526, 1800]),
  heading("3.2 当前配色令牌", 2),
  table(["语义", "色值", "现有用途"], colorRows, [2300, 3100, 3626]),
  heading("3.3 当前风格特征", 2),
  bullet("深色科技控制台；青绿色为主操作和焦点，蓝色为识别信息。"),
  bullet("卡片、细描边、12–20px圆角、较少阴影；状态以文字、颜色和边框共同表达。"),
  bullet("中英文微标签混用，如LIVE VISION、CURRENT GESTURE、PERSONAL CALIBRATION。"),
  bullet("主界面信息密度高，适合研发诊断，但对首次用户的引导层级仍可加强。"),
  bullet("当前最小宽度附近右侧滚动区可能出现横向滚动条，重设计需在1060×700与125%/150%缩放下消除横向滚动。"),
  pageBreak(),
);

children.push(
  heading("4. 功能清单", 1),
  table(["功能", "具体行为", "状态"], functions, [1700, 5826, 1500]),
  heading("4.1 全局快捷键", 2),
  table(["快捷键", "动作", "安全语义"], [
    ["Ctrl + Alt + G", "暂停/恢复手势控制", "保留程序和识别流程"],
    ["Ctrl + Alt + Esc", "紧急停止", "立即停止控制并释放按键"],
    ["Ctrl + Alt + Q", "安全退出", "停止流水线、释放按键、退出程序"],
  ], [2400, 2600, 4026]),
  pageBreak(),
);

children.push(
  heading("5. 手势与状态机规则", 1),
  callout("设计时不可简化掉的逻辑", "点击不是“检测到捏合就立即触发”，而是“靠近时锁定位置、接触后进入待定、松开时点击、持续达到阈值转为拖拽”。界面反馈必须让用户看得懂这个过程。", C.paleAmber, C.amber),
  table(["用户动作", "系统操作", "触发时机/阈值", "备注"], gestureRows, [1850, 1650, 2200, 3326]),
  heading("5.1 固定优先级", 2),
  p([run("紧急停止", { bold: true, color: C.rose }), run(" ＞ 手部失联/越界保护 ＞ 暂停 ＞ 已建立拖拽/捏合 ＞ 点击/右键 ＞ 滚轮/翻页 ＞ 光标移动", { bold: true, color: C.ink })]),
  heading("5.2 用户可见手势状态文案", 2),
  p("等待手势、光标移动、点击位置锁定、左键捏合、右键捏合、正在拖拽、滚轮控制、下一页、上一页、食指续跟踪、中指续跟踪、握拳确认、控制已暂停、未检测到手。"),
  heading("5.3 失联与越界保护", 2),
  bullet("拇指、掌心或相关手指越界时，不用模型预测坐标触发点击、右键、滚轮、翻页或暂停。"),
  bullet("待定点击在越界时静默取消，不把越界当作松开；拖拽则立即释放。"),
  bullet("越界或失联后，完整手部连续稳定约1000ms才重新允许离散手势；食指仍可移动光标。"),
  pageBreak(),
);

children.push(
  heading("6. 运行状态与反馈要求", 1),
  table(["状态", "含义", "当前视觉", "应提供的恢复操作"], stateRows, [1700, 2850, 1600, 2876]),
  heading("6.1 实时诊断信息", 2),
  bullet("当前手势与上下文消息：是主要反馈，不应被技术指标淹没。"),
  bullet("近3秒识别稳定度、手掌大小、识别增强倍率、光照状态。"),
  bullet("采集/推理FPS、当前/P95延迟、CPU/内存、覆盖/丢帧数。"),
  bullet("分情形提示：无画面、光线偏暗、手太远、手太近、指尖遮挡、识别波动、追踪稳定。"),
  heading("6.2 安全与隐私反馈", 2),
  bullet("摄像头启用必须有明确可见指示。"),
  bullet("暂停后停止鼠标注入；可继续低频识别以便恢复。"),
  bullet("关闭窗口默认最小化到托盘，必须提供明确的“安全退出”。"),
  bullet("任何异常、断线或退出都必须先释放鼠标按键。"),
  pageBreak(),
);

children.push(
  heading("7. 用户可见参数", 1),
  p("以下数值是当前0.8.5默认值和设置页实际范围。重新设计可以改变控件形式、分组和文案，但不能悄悄改变语义或默认值。"),
  table(["参数", "默认值", "界面范围", "含义"], visibleParams, [1900, 1600, 1800, 3726]),
  pageBreak(),
  heading("8. 高级/内部参数", 1),
  p("这些参数不一定全部暴露给普通用户，但设计高级模式、诊断抽屉、配置导入导出或技术说明时需要了解。第7节与本节合计覆盖当前AppConfig全部40个持久化字段；同一字段可能以用户文案和内部字段名各出现一次。"),
  table(["字段", "默认值", "校验范围", "含义"], advancedParams, [2600, 1600, 2200, 2626]),
  heading("8.1 0.8.5内部防误触与时序阈值", 2),
  p("以下常量当前不面向普通用户开放，设计AI不应直接把它们全部做成滑块。它们用于解释诊断状态、右键预备、点击确认、越界恢复和过期结果丢弃。"),
  table(["内部规则", "当前值", "作用"], gestureSafetyParams, [2600, 1900, 4526]),
  pageBreak(),
);

children.push(
  heading("9. 个性化校准流程", 1),
  ...imageBlock("ui-calibration.png", "当前三步校准对话框", "对话框最小560×430，默认620×470；校准期间暂停鼠标控制，视频只在本机处理且不保存。", 520),
  table(["步骤", "用户动作", "采集内容", "结果用途"], [
    ["1 / 3", "拇指与食指自然张开", "张开距离样本", "估算用户自然开合区间"],
    ["2 / 3", "按平时力度轻轻捏合", "闭合距离样本", "计算进入/退出阈值与滞回"],
    ["3 / 3", "食指自然指向并尽量静止", "指尖抖动样本", "计算稳定性、响应和插值时间"],
  ], [1200, 2600, 2400, 2826]),
  heading("结果规则", 2),
  bullet("每步约2秒；有效样本不足或张开/捏合区分不明显时给出原因与重试入口。"),
  bullet("只有点击“应用校准”才保存；取消不得修改当前配置。"),
  bullet("校准结果包括捏合进入阈值、释放阈值、稳定性、响应速度和过渡时间。"),
  pageBreak(),
);

children.push(
  heading("10. 平台、工程与实现约束", 1),
  table(["约束", "具体要求", "对UI设计的影响"], [
    ["桌面技术", "PySide6，GUI必须在主线程", "使用Qt可实现组件和动效，不以网页/CSS专属效果为前提"],
    ["窗口尺寸", "默认1280×820；最小1060×700；Per-Monitor V2 DPI", "在100%、125%、150%缩放下不截断；避免过度固定像素"],
    ["预览性能", "预览默认15fps；推理与采集独立", "不要让大面积装饰动画与预览争抢CPU"],
    ["系统权限", "asInvoker，不能控制管理员窗口", "权限失败应解释原因，不伪装成识别故障"],
    ["主显示器", "首版只映射主显示器", "设置中不应出现未实现的多显示器编排"],
    ["离线隐私", "不上传、不保存画面和关键点", "显著展示本地处理，但不要制造虚假联网入口"],
    ["系统托盘", "关闭窗口后可继续后台运行", "区分隐藏、暂停、停止控制和完全退出"],
    ["配置", "%LOCALAPPDATA%\\Vimoose\\config.json，版本化迁移", "保存/应用/恢复默认必须给出明确结果"],
    ["日志", "%LOCALAPPDATA%\\Vimoose\\logs\\vimoose.log", "诊断入口可导向日志位置，但默认不记录图像/关键点"],
  ], [1800, 3600, 3626]),
  heading("10.1 无障碍底线", 2),
  bullet("所有主要操作可用键盘到达；焦点边框清晰可见。"),
  bullet("正文与背景对比度至少4.5:1；状态不可仅凭颜色区分。"),
  bullet("图标按钮必须有文字标签或无障碍名称；危险操作用文字说明后果。"),
  bullet("控件点击区域建议不小于44×44px，紧邻操作至少留8px间距。"),
  pageBreak(),
);

children.push(
  heading("11. 性能与质量事实", 1),
  callout("不要把目标值画成已达成", "界面可以展示目标或健康阈值，但必须区分“实时测量”“目标”和“尚未验收”。最近一次安装版性能数据来自0.8.4：约21.8fps、延迟P95约16ms、CPU约3.8%、内存约288.4MB；0.8.5尚未完成真人手势和正式性能验收。", C.paleRose, C.rose),
  table(["指标", "计划目标", "当前证据/状态"], [
    ["有效控制帧率", "≥25fps", "当前Iriun虚拟摄像头约21.8fps，未达目标"],
    ["端到端延迟P95", "≤100ms", "0.8.4安装版短时诊断约16ms，通过短时目标"],
    ["CPU占用", "≤15%目标", "0.8.4安装版短时约3.8%"],
    ["内存", "≤200MB目标", "0.8.4安装版约288.4MB，未达目标"],
    ["点击成功率", "左右键≥95%", "尚未完成正式多用户验收"],
    ["拖拽/滚动", "≥90%", "尚未完成正式多用户验收"],
    ["误触", "≤1次/分钟", "0.8.0录像问题片段回放无离散误触，但不等同正式统计"],
    ["稳定性", "连续1小时无崩溃/卡键", "尚未完成正式1小时验收"],
    ["自动化测试", "回归通过", "0.8.5当前工作树共130项通过，其中手势状态机81项"],
    ["原始录像回放", "已知问题片段无误触", "96.55秒录像按10Hz回放：966采样、806检出；核心指向与翻腕片段无错误点击"],
  ], [2200, 2500, 4326]),
  callout("当前仍需真人验证的手感", "0.8.5已加入右键120ms前伸宽限、中指姿态联合门控和翻腕投影保护，但自动化与录像回放不能替代真实用户手势。UI应明确显示右键预备、接触与确认阶段，并保留易发现的反馈入口。", C.paleAmber, C.amber),
  p("参考环境：Windows 11专业版64位、Intel Core i5-14600KF、31.8GB内存、Iriun虚拟摄像头、2048×1152主屏、125%缩放。"),
  pageBreak(),
);

children.push(
  heading("12. 当前UI问题与重设计机会", 1),
  table(["现象", "风险", "建议方向"], [
    ["主控制台同时展示预览、质量、4项性能指标、手势清单和工具", "首次用户难判断主任务，当前手势与安全状态容易被稀释", "强化“当前状态—下一步动作”主层级；技术指标折叠为诊断区"],
    ["设置全部集中在单一长滚动页", "高频手感参数与低频高级功能混杂", "拆为设备/控制手感/手势/高级与启动，或用渐进披露"],
    ["左侧预览长期占据较大面积", "后台控制时浪费空间，窗口较难缩小", "提供专注模式、紧凑模式或可折叠预览，但默认仍需明显摄像头状态"],
    ["手势学习主要是文字矩阵", "新用户难理解时序，如“松开才点击”“长按转拖拽”", "使用分步动态图/骨架示意和即时确认，不依赖静态文字"],
    ["错误提示与正常状态共用同一信息区域", "恢复路径不够突出", "为无画面、弱光、失联、权限失败设计明确的原因+操作"],
    ["部分英文微标签与中文界面混用", "品牌有科技感，但一致性一般", "确定双语规则；英文只作品牌化辅助，不承载关键语义"],
    ["主窗口安全按钮很多且并列", "暂停、停止、紧急停止的差异可能不直观", "保留三者，但通过层级、说明、确认策略和状态上下文区分"],
  ], [2200, 3100, 3726]),
  heading("不可牺牲的体验", 2),
  bullet("紧急停止始终可见或一键可达，不能藏入多级菜单。"),
  bullet("任何时刻清楚显示是否正在注入鼠标事件。"),
  bullet("点击位置锁定、等待重新张开、拖拽已按下、手部失联等关键中间态必须可感知。"),
  bullet("错误提示必须给出恢复动作，不能只显示错误码。"),
  pageBreak(),
);

children.push(
  heading("13. 建议的新信息架构", 1),
  table(["一级页面/模式", "主要内容", "设计重点"], [
    ["控制", "当前状态、实时预览、当前手势、开始/暂停/停止、快速诊断", "一眼可用；默认页面"],
    ["手势", "全部手势、启停、演示、实时试做、冲突说明", "从“说明书”变为“学习与验证”"],
    ["设备与识别", "摄像头、操作手、检测门槛、识别增强、光照/画面诊断", "错误恢复优先"],
    ["光标体验", "稳定性、响应、过渡、覆盖、磁吸、校准", "即时预览参数变化，可恢复默认"],
    ["高级与系统", "扩展手势、局部跟踪、预览、自启、日志、隐私、版本", "渐进披露，避免干扰普通用户"],
    ["紧凑模式", "状态、当前手势、暂停/恢复、紧急停止", "后台常驻，小尺寸但安全完整"],
  ], [1900, 3900, 3226]),
  callout("这不是强制布局", "设计AI可以提出不同结构，但必须说明如何减少认知负担、如何保证安全操作可达、如何适配1060×700最小窗口和125%/150%缩放。", C.paleBlue, C.cyan),
  heading("关键页面必须覆盖的状态", 2),
  bullet("首次打开且未启动；已启动且识别稳定；点击位置锁定；正在拖拽。"),
  bullet("暂停；手部丢失后的1000ms重启等待；光线偏暗；无画面；摄像头断开。"),
  bullet("普通窗口可控；管理员窗口不可控；控件磁吸可用/目标不提供UI Automation。"),
  bullet("设置已修改未保存、保存成功、恢复默认确认、校准失败与重试。"),
  pageBreak(),
);

children.push(
  heading("14. 设计验收清单", 1),
  bullet("在正常、暂停、停止、无画面和异常状态下，用户都能明确知道鼠标是否会被控制。", 0, "checklist"),
  bullet("紧急停止在所有关键页面一键可达，且与普通停止有明确视觉差异。", 0, "checklist"),
  bullet("点击、拖拽、右键、滚轮和翻页的动作、触发时机与反馈文案准确。", 0, "checklist"),
  bullet("默认参数与本文件一致；高级参数被隐藏时仍有可发现入口。", 0, "checklist"),
  bullet("最小1060×700窗口下无内容截断；125%和150%缩放下可读。", 0, "checklist"),
  bullet("所有交互有悬停、聚焦、按下、禁用和错误状态；支持键盘操作。", 0, "checklist"),
  bullet("正文对比度达到WCAG AA；状态不只依赖颜色。", 0, "checklist"),
  bullet("预览、性能数据和动画不会让主线程持续高负载。", 0, "checklist"),
  bullet("离线处理、不保存画面、普通权限限制等信息表述准确。", 0, "checklist"),
  bullet("设计稿包含PySide6实现尺寸、间距、字体、颜色和组件状态标注。", 0, "checklist"),
  heading("建议交付文件", 2),
  p("Figma或同类可编辑设计文件、关键页面PNG、组件与令牌说明、交互状态说明，以及一份面向PySide6开发者的实现标注。若直接生成代码，应先提交可运行的静态原型，再接入摄像头与鼠标逻辑。"),
  pageBreak(),
);

children.push(
  heading("附录A：设计依据与版本说明", 1),
  table(["依据", "用途"], [
    ["README.md", "当前功能、产品边界、使用说明"],
    ["gesture_mouse/ui.py", "现有布局、文案、颜色、控件与范围"],
    ["gesture_mouse/config.py", "默认参数、校验范围、配置迁移"],
    ["gesture_mouse/gestures.py", "状态机、优先级、手势时序与安全释放"],
    ["gesture_mouse/calibration.py", "三步校准算法与结果"],
    ["PRIVACY.md", "本地处理和数据边界"],
    ["PERFORMANCE_BASELINE.md", "参考环境、实测与未完成验收"],
    ["RELEASE_NOTES_0.8.5.md", "最新右键灵敏度、翻腕准确性与完整录像回放验证"],
  ], [3200, 5826]),
  heading("附录B：需要设计 AI 主动回答的问题", 1),
  bullet("如何让“系统正在注入鼠标”成为最清楚的一级状态？"),
  bullet("如何区分暂停、停止、紧急停止，而不让顶部栏显得拥挤？"),
  bullet("如何用可实现的视觉反馈表达“点击位置已锁定”和“拖拽左键已按下”？"),
  bullet("如何在紧凑窗口中兼顾预览、安全控制和错误恢复？"),
  bullet("哪些设置应默认展示，哪些应进入高级模式？依据是什么？"),
  bullet("如何设计首次使用流程，让用户在30秒内完成入镜、移动、点击和紧急停止学习？"),
  callout("最终提醒", "不要把本软件设计成纯展示型“AI仪表盘”。它首先是一件实时输入设备：安全、状态可知、低误触和恢复路径应优先于装饰效果。", C.paleTeal, C.teal),
);

const doc = new Document({
  creator: "Codex",
  title: "Vimoose UI设计交接说明",
  subject: "Vimoose当前界面、功能、参数与UI重设计约束",
  description: "供外部AI或UI设计师使用的单文件产品设计交接资料",
  styles: {
    default: {
      document: { run: { font: "Microsoft YaHei", size: 20, color: C.body } },
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Microsoft YaHei", size: 34, bold: true, color: C.ink },
        paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 0, border: { bottom: { style: BorderStyle.SINGLE, size: 10, color: C.teal, space: 8 } } },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Microsoft YaHei", size: 27, bold: true, color: C.ink },
        paragraph: { spacing: { before: 200, after: 110 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Microsoft YaHei", size: 23, bold: true, color: C.body },
        paragraph: { spacing: { before: 160, after: 90 }, outlineLevel: 2 },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: "bullet-main",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 260 } } } }],
      },
      {
        reference: "checklist",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "□", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 260 } } } }],
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 820, right: 1440, bottom: 900, left: 1440 },
      },
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          tabStops: [{ type: "right", position: 8800 }],
          children: [
            run("Vimoose UI设计交接说明", { size: 16, color: C.muted }),
            run("\t第 ", { size: 16, color: C.muted }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Microsoft YaHei", size: 16, color: C.muted }),
            run(" 页", { size: 16, color: C.muted }),
          ],
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: C.line, space: 6 } },
        })],
      }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(OUTPUT, buffer);
  process.stdout.write(`${OUTPUT}\n`);
});
