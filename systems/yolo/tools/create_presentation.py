from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


OUT = Path("construction_safety_system_presentation.pptx")
FONT = "Microsoft JhengHei"

COLORS = {
    "bg": RGBColor(244, 246, 245),
    "ink": RGBColor(23, 33, 28),
    "muted": RGBColor(100, 115, 109),
    "steel": RGBColor(45, 74, 93),
    "line": RGBColor(220, 228, 223),
    "safe": RGBColor(19, 138, 91),
    "warn": RGBColor(181, 107, 0),
    "danger": RGBColor(189, 43, 43),
    "yellow": RGBColor(243, 182, 31),
    "white": RGBColor(255, 255, 255),
    "dark": RGBColor(17, 24, 22),
}


def set_bg(slide, color=COLORS["bg"]):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_title(slide, title, subtitle=None):
    box = slide.shapes.add_textbox(Inches(0.55), Inches(0.35), Inches(12.2), Inches(0.75))
    frame = box.text_frame
    frame.clear()
    p = frame.paragraphs[0]
    p.text = title
    p.font.name = FONT
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = COLORS["ink"]
    if subtitle:
        sub = slide.shapes.add_textbox(Inches(0.58), Inches(1.05), Inches(11.8), Inches(0.35))
        sp = sub.text_frame.paragraphs[0]
        sp.text = subtitle
        sp.font.name = FONT
        sp.font.size = Pt(13)
        sp.font.color.rgb = COLORS["muted"]


def add_footer(slide, page):
    box = slide.shapes.add_textbox(Inches(11.6), Inches(7.05), Inches(1.1), Inches(0.25))
    p = box.text_frame.paragraphs[0]
    p.text = f"{page:02d}"
    p.font.name = FONT
    p.font.size = Pt(10)
    p.font.color.rgb = COLORS["muted"]
    p.alignment = PP_ALIGN.RIGHT


def bullet_box(slide, x, y, w, h, title, bullets, accent=COLORS["steel"]):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = COLORS["white"]
    shape.line.color.rgb = COLORS["line"]
    shape.line.width = Pt(1)
    frame = shape.text_frame
    frame.clear()
    frame.margin_left = Inches(0.18)
    frame.margin_right = Inches(0.18)
    frame.margin_top = Inches(0.14)
    p = frame.paragraphs[0]
    p.text = title
    p.font.name = FONT
    p.font.size = Pt(15)
    p.font.bold = True
    p.font.color.rgb = accent
    for item in bullets:
        bp = frame.add_paragraph()
        bp.text = item
        bp.font.name = FONT
        bp.font.size = Pt(11.5)
        bp.font.color.rgb = COLORS["ink"]
        bp.space_after = Pt(2)
    return shape


def label(slide, x, y, w, h, text, fill, font_size=12, color=COLORS["white"]):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = fill
    frame = shape.text_frame
    frame.clear()
    frame.margin_left = Inches(0.08)
    frame.margin_right = Inches(0.08)
    p = frame.paragraphs[0]
    p.text = text
    p.font.name = FONT
    p.font.size = Pt(font_size)
    p.font.bold = True
    p.font.color.rgb = color
    p.alignment = PP_ALIGN.CENTER
    return shape


def connector(slide, x1, y1, x2, y2, color=COLORS["steel"]):
    line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    line.line.color.rgb = color
    line.line.width = Pt(1.5)
    return line


def add_code_box(slide, x, y, w, h, text):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = COLORS["dark"]
    shape.line.color.rgb = COLORS["dark"]
    frame = shape.text_frame
    frame.clear()
    frame.margin_left = Inches(0.22)
    frame.margin_top = Inches(0.18)
    p = frame.paragraphs[0]
    p.text = text
    p.font.name = "Consolas"
    p.font.size = Pt(12)
    p.font.color.rgb = COLORS["white"]


prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide)
add_title(slide, "撌亙摰??蝟餌絞", "YOLO + MediaPipe + Flask + Next.js ??蝡臬??質?鞈??脣?隤芣?")
label(slide, 0.75, 2.05, 3.2, 1.0, "?垢???恍", COLORS["steel"], 17)
label(slide, 5.05, 2.05, 3.2, 1.0, "敺垢颲刻?璅∠?", COLORS["safe"], 17)
label(slide, 9.35, 2.05, 3.2, 1.0, "?單??????, COLORS["warn"], 17)
connector(slide, 3.95, 2.55, 5.05, 2.55)
connector(slide, 8.25, 2.55, 9.35, 2.55)
bullet_box(slide, 1.0, 4.0, 11.3, 1.55, "蝟餌絞?格?", [
    "?單?霈?極?啣蔣???菜葫鈭箏???典蜇???刻?敹?,
    "餈質馱??雿犖?∩蒂閮?摨扳?嚗???UWB ???賢?",
    "?游?鈭箏??◢?芾?霅血鈭辣嚗?靘?批??唬蝙??,
])
add_footer(slide, 1)

slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide)
add_title(slide, "?湧??嗆?", "?垢鞎痊???雿?敺垢鞎痊敶勗????儘霅蕭頩方?????)
items = [
    ("敶勗?靘?\n?祆?敶梁? / RTSP", 0.65, COLORS["steel"]),
    ("Flask API\napp.py", 3.0, COLORS["safe"]),
    ("?詨?璅∠?\ncamera / yolo / pose / tracker / manager", 5.35, COLORS["warn"]),
    ("?單?鞈?\nworkers / events / tracks", 8.0, COLORS["danger"]),
    ("?垢?恍\nNext.js / Flask 皜祈岫??, 10.6, COLORS["steel"]),
]
for text, x, color in items:
    label(slide, x, 2.1, 2.0, 0.9, text, color, 11)
for i in range(len(items) - 1):
    connector(slide, items[i][1] + 2.0, 2.55, items[i + 1][1], 2.55)
bullet_box(slide, 0.85, 4.15, 3.75, 1.55, "鞈?瘚?, ["敶勗?撟?脣敺垢", "璅∪?頛詨 detection", "tracker 蝬剜? track_id"])
bullet_box(slide, 4.8, 4.15, 3.75, 1.55, "???", ["WorkerManager ?游? PPE / 憪踵? / 摨扳?", "?Ｙ? worker ???鈭辣"], COLORS["safe"])
bullet_box(slide, 8.75, 4.15, 3.75, 1.55, "?瘚?, ["API ? JSON", "銝脫??恍??獢??漣璅?蝭?"], COLORS["warn"])
add_footer(slide, 2)

slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide)
add_title(slide, "?垢?", "?桀???Next.js ?垢?耦??Flask 敺垢?????詨?鈭?撌脣??曉 Flask ?撽?")
bullet_box(slide, 0.7, 1.65, 3.85, 4.6, "銝餌??, [
    "銝憿舐內?單?敶勗?銝脫?",
    "?喃?閫＊蝷?camera_id",
    "銝靘蕭頩文?犖?⊥???閮??,
    "瘥憿舐內 worker_id?rack_id?PE?◢?芥漣璅?,
])
bullet_box(slide, 4.75, 1.65, 3.85, 4.6, "蝭?蝜芾ˊ", [
    "?臬?恍銝?梢???UWB ?文?蝭?",
    "?喳?銝?敶Ｘ?憭?敶?,
    "?脣?敺?蝡臭誑甇???漣璅?摮?,
    "銝脫? overlay ???UWB RANGE",
], COLORS["safe"])
bullet_box(slide, 8.8, 1.65, 3.85, 4.6, "敹恍炎??, [
    "?亙熒瑼Ｘ /api/health",
    "?蔣璈???/api/cameras",
    "鈭箏???/api/workers",
    "霅血鈭辣 /api/alerts",
], COLORS["warn"])
add_footer(slide, 3)

slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide)
add_title(slide, "敺垢?詨?璅∠?", "?桀?敺垢靘??賣????蜓閬芋蝯?鈭?靽?璅∪??游?嚗???撌脣撥???恣??)
modules = [
    ("camera.py", "敶勗?頛詨????\n敶梁? / RTSP?圾?漲?PS?漁摨艾?瘥????),
    ("yolo_detector.py", "YOLO ?菜葫\nkaggle.pt ?菜葫鈭箏嚗est_v3.pt ?菜葫摰撣質???"),
    ("pose_detector.py", "MediaPipe 憪踵?\n??憪踵???嚗撩璅∪???蝝?銝剜瘚?"),
    ("tracker.py", "鈭箏餈質馱\nIoU + 銝剖?頝 + 撠箏站?訾撮摨衣雁??track_id"),
    ("worker_manager.py", "??恣?n?游?鈭箏?PE?尿?漣璅◢?芾?鈭辣"),
]
for idx, (name, desc) in enumerate(modules):
    y = 1.45 + idx * 0.95
    color = [COLORS["steel"], COLORS["safe"], COLORS["warn"], COLORS["danger"], COLORS["steel"]][idx]
    label(slide, 0.8, y, 2.2, 0.62, name, color, 12)
    box = slide.shapes.add_textbox(Inches(3.25), Inches(y), Inches(9.1), Inches(0.62))
    p = box.text_frame.paragraphs[0]
    p.text = desc
    p.font.name = FONT
    p.font.size = Pt(12.5)
    p.font.color.rgb = COLORS["ink"]
add_footer(slide, 4)

slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide)
add_title(slide, "敶勗??啁?????瘚?", "瘥?撟??摨??????皜研?撠蕭頩扎漣璅?憸券?游?")
steps = [
    ("1 霈?蔣??, "VideoInput 霈?璈蔣?? RTSP"),
    ("2 ????, "蝯曹?閫??摨艾撘? FPS"),
    ("3 YOLO ?菜葫", "?曉鈭箏???刻???),
    ("4 鋆???", "靘征??蝵格? helmet / vest ?策鈭?),
    ("5 餈質馱摨扳?", "蝬剜? track_id 銝西?蝞漣璅?),
    ("6 ??撓??, "頛詨 workers JSON ??events"),
]
for i, (title, desc) in enumerate(steps):
    x = 0.65 + (i % 3) * 4.2
    y = 1.55 + (i // 3) * 2.15
    color = [COLORS["steel"], COLORS["safe"], COLORS["warn"], COLORS["danger"], COLORS["steel"], COLORS["safe"]][i]
    bullet_box(slide, x, y, 3.65, 1.35, title, [desc], color)
connector(slide, 4.3, 2.2, 4.85, 2.2)
connector(slide, 8.5, 2.2, 9.05, 2.2)
connector(slide, 4.3, 4.35, 4.85, 4.35)
connector(slide, 8.5, 4.35, 9.05, 4.35)
add_footer(slide, 5)

slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide)
add_title(slide, "鈭箏餈質馱?漣璅?蝞?, "璅∠????鞎祉雁??track_id嚗蒂頛詨?拙惜摨扳?蝯?UWB ??雿輻")
bullet_box(slide, 0.75, 1.55, 3.7, 4.7, "餈質馱?摩", [
    "YOLO person box ?脣 IouTracker",
    "??IoU?葉敹?頝??憭批??訾撮摨行?撠?敺?",
    "?剜瞍皜祆?靽? track嚗?雿?ID 霈?",
    "??鈭箸?蝬剜?????track_id",
])
bullet_box(slide, 4.85, 1.55, 3.7, 4.7, "?渡?Ｗ漣璅?, [
    "瘞賊?閮? coordinate.frame",
    "雿輻鈭箏獢??其葉敹?",
    "??靽? pixel ??normalized",
    "?拙? debug ??恍摰?",
], COLORS["safe"])
bullet_box(slide, 8.95, 1.55, 3.7, 4.7, "蝜芾ˊ蝭?摨扳?", [
    "雿輻雿輻??箇? polygon",
    "鈭箏暺蝭??扳?閮? coordinate.range",
    "銝蝭??批? range = null嚗?蝡舫＊蝷箝??,
    "?? UWB ??蝭??文?",
], COLORS["warn"])
add_footer(slide, 6)

slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide)
add_title(slide, "鞈??脣??孵?", "?桀??臬????鞈?摮敺垢閮擃??? Flask 敺?皜征")
bullet_box(slide, 0.8, 1.45, 3.75, 4.8, "SafetyRuntime", [
    "摮 app.config[\"SAFETY_RUNTIME\"]",
    "靽? camera_config",
    "靽? VideoInput",
    "靽? PairingRange",
    "靽? WorkerManager",
])
bullet_box(slide, 4.8, 1.45, 3.75, 4.8, "WorkerManager", [
    "workers: dict[int, WorkerState]",
    "events: deque[dict]嚗?憭?200 蝑?,
    "last_errors 靽?璅∪??尿?隤?,
    "last_frame_summary 靽??餈?撟??",
], COLORS["safe"])
bullet_box(slide, 8.8, 1.45, 3.75, 4.8, "Tracker", [
    "tracks: dict[int, Track]",
    "key ??track_id",
    "靽? box?onfidence?its?issed",
    "?冽銝?撟鈭箏瘥?",
], COLORS["warn"])
add_footer(slide, 7)

slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide)
add_title(slide, "銝餉?鞈?蝯?", "?垢霈??/api/workers ???詨?鞈?靘 WorkerState.to_dict()")
add_code_box(slide, 0.85, 1.45, 5.55, 4.95, """{
  \"worker_id\": \"worker-001\",
  \"track_id\": 1,
  \"camera_id\": \"CAM-01\",
  \"zone\": \"?身???\",
  \"ppe\": { \"helmet\": true, \"vest\": true },
  \"coordinate\": {
    \"frame\": { \"pixel\": { \"x\": 94, \"y\": 718 } },
    \"range\": null
  },
  \"risk_level\": \"normal\",
  \"alerts\": []
}""")
bullet_box(slide, 6.75, 1.45, 5.65, 4.95, "甈?隤芣?", [
    "worker_id嚗???track_id ?Ｙ?嚗?敺??UWB ?祕頨思遢",
    "track_id嚗蔣?蕭頩斤楊???其?蝬剜???鈭?,
    "ppe嚗??典蜇??敹????撟?文?蝯?",
    "coordinate.frame嚗?恍摨扳?嚗偶????,
    "coordinate.range嚗蝜芾ˊ蝭??扳?摮嚗? null",
    "alerts嚗蝛踵??????鈭辣??",
])
add_footer(slide, 8)

slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide)
add_title(slide, "API ???撓??, "Flask ?桀??????葡瘚? JSON API嚗??垢?臬??鞈?")
bullet_box(slide, 0.75, 1.45, 3.75, 4.85, "?恍?葡瘚?, [
    "/嚗?蝡舐?扳葫閰阡?",
    "/api/cameras/stream嚗JPEG ?單?銝脫?",
    "銝脫??恍??箔犖?⊥??漣璅???UWB RANGE",
])
bullet_box(slide, 4.8, 1.45, 3.75, 4.85, "???API", [
    "/api/health嚗摨瑟炎??,
    "/api/cameras嚗?敶望??芋?? pairing_range ???,
    "/api/workers嚗?犖?∠???,
    "/api/alerts嚗郎?曹?隞?,
], COLORS["safe"])
bullet_box(slide, 8.85, 1.45, 3.75, 4.85, "蝭? API", [
    "GET /api/cameras/pairing-range",
    "POST /api/cameras/pairing-range",
    "隞?normalized polygon points ?脣?",
    "?桀?摮閮擃???敺??圈?閮剖?,
], COLORS["warn"])
add_footer(slide, 9)

slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide)
add_title(slide, "?桀????蝥????, "蝟餌絞撌脣撅內?詨?瘚?嚗?甇?????閬?銋??帘摰蕭頩方?憭?敶望?蝞∠?")
bullet_box(slide, 0.75, 1.45, 3.75, 4.85, "鞈?靽?", [
    "?桀?鞈??刻??園?嚗???皜征",
    "撱箄降鈭辣?身摰神??SQLite / MySQL",
    "鈭箏頨思遢鞈?蝑?UWB ??敺遣蝡??”",
])
bullet_box(slide, 4.8, 1.45, 3.75, 4.85, "颲刻??蕭頩?, [
    "餈質馱?典?? ByteTrack / DeepSORT",
    "PPE ???臬?鈭粹??????,
    "鋆? MediaPipe pose_landmarker 璅∪?隞亙??典尿??隞?,
], COLORS["safe"])
bullet_box(slide, 8.85, 1.45, 3.75, 4.85, "?垢?游?", [
    "Next.js 甇????Flask API",
    "?啣? workers / alerts / cameras ?",
    "??蝭?閮剖??TSP 閮剖????蔣璈???,
], COLORS["warn"])
add_footer(slide, 10)

prs.save(OUT)
print(OUT.resolve())


