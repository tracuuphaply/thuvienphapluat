"""
Sinh sơ đồ quy trình hệ thống theo chuẩn BPMN 2.0 (OMG) ra file .bpmn.

Viết bằng script thay vì gõ tay XML vì phần Diagram Interchange (toạ độ hình và
đường nối) phải khớp tuyệt đối với phần ngữ nghĩa — lệch một id là công cụ mở
lên trắng trang. Ở đây toạ độ được tính, và có bước tự kiểm ở cuối.

Mở được bằng: Camunda Modeler, bpmn.io, Signavio, hoặc bất kỳ công cụ nào đọc
BPMN 2.0 XML.

Chạy:  python -m scripts.generate_bpmn
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path("docs/quy_trinh_he_thong.bpmn")

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
}

# ── Bố cục ───────────────────────────────────────────────────────────────────
POOL_X, POOL_Y = 160, 80
LANE_LABEL_W = 30
LANES: list[tuple[str, str, int]] = [           # (id, tên, chiều cao)
    ("Lane_ThuThap", "Thu thập văn bản", 300),
    ("Lane_XuLy", "Xử lý & lưu trữ", 200),
    ("Lane_TruyXuat", "Truy xuất & sinh báo cáo", 220),
    ("Lane_PhatHanh", "Phát hành & vận hành", 200),
]
POOL_W = 3700
POOL_H = sum(h for _, _, h in LANES)

_lane_top: dict[str, int] = {}
_y = POOL_Y
for _id, _name, _h in LANES:
    _lane_top[_id] = _y
    _y += _h


def cy(lane: str, offset: int = 0) -> int:
    """Tâm dọc của một lane, có thể dịch lên/xuống để tách nhánh song song."""
    idx = [l[0] for l in LANES].index(lane)
    return _lane_top[lane] + LANES[idx][2] // 2 + offset


TASK_W, TASK_H = 150, 80
EV_D, GW_D = 36, 50

# ── Các phần tử ──────────────────────────────────────────────────────────────
# (id, loại, nhãn, lane, x, dịch dọc)
ELEMENTS: list[tuple[str, str, str, str, int, int]] = [
    ("Start_HangNgay", "startEvent", "Đến giờ chạy hằng ngày\n(launchd 06:00)", "Lane_ThuThap", 230, -70),
    ("Task_Khoa", "task", "Lấy khoá chống chạy chồng", "Lane_ThuThap", 320, -70),
    ("GW_Quet_Split", "parallelGateway", "", "Lane_ThuThap", 520, -70),
    ("Task_QuetTVPL", "task", "Quét RSS Thư viện pháp luật", "Lane_ThuThap", 620, -110),
    ("Task_QuetMOJ", "serviceTask", "Gọi API Bộ Tư pháp\n(quét theo cửa sổ ngày)", "Lane_ThuThap", 620, 10),
    ("GW_Quet_Join", "parallelGateway", "", "Lane_ThuThap", 830, -70),
    ("GW_CoVanBan", "exclusiveGateway", "Có văn bản\nnào không?", "Lane_ThuThap", 930, -70),
    ("End_NguonChet", "endEvent", "Ghi FAILED\n+ gửi cảnh báo", "Lane_ThuThap", 1010, 60),

    ("Task_GopTrung", "task", "Gộp & khử trùng\ntheo doc_key", "Lane_XuLy", 1030, 0),
    ("Task_NapChiTiet", "serviceTask", "Nạp chi tiết + quan hệ\ntừ Bộ Tư pháp", "Lane_XuLy", 1220, 0),
    ("Task_LamSach", "task", "Làm sạch, tách Điều/Khoản", "Lane_XuLy", 1410, 0),
    ("Task_LuuDB", "task", "Ghi CSDL, cập nhật\nlịch sử hiệu lực", "Lane_XuLy", 1600, 0),
    ("GW_CoSuKien", "exclusiveGateway", "Có sự kiện\nA / B / C?", "Lane_XuLy", 1810, 0),

    ("Task_DongBo", "task", "Đồng bộ vault Obsidian\n+ chỉ mục RAG", "Lane_TruyXuat", 1900, 0),
    ("Task_Nhung", "serviceTask", "Nhúng vector các đoạn mới", "Lane_TruyXuat", 2090, 0),
    ("Task_TruyXuat", "task", "Truy xuất theo ngành VSIC\n(BM25 + vector)", "Lane_TruyXuat", 2280, 0),
    ("Task_LocHieuLuc", "businessRuleTask", "Loại văn bản hết hiệu lực,\ngắn cảnh báo", "Lane_TruyXuat", 2470, 0),
    ("Task_SinhBaoCao", "serviceTask", "Sinh báo cáo qua API v98", "Lane_TruyXuat", 2660, 0),
    ("Task_DoiChieu", "businessRuleTask", "Đối chiếu số hiệu\nvới cơ sở dữ liệu", "Lane_TruyXuat", 2850, 0),
    ("GW_TrichDan", "exclusiveGateway", "Trích dẫn\nhợp lệ?", "Lane_TruyXuat", 3060, 0),
    ("End_ChanBaoCao", "endEvent", "Chặn xuất bản,\nghi số hiệu lạ", "Lane_TruyXuat", 3150, 70),

    # Toàn sơ đồ chảy một chiều trái→phải: lane sau bắt đầu ở nơi lane trước kết
    # thúc. Xếp lane sau về bên trái tuy gọn hơn nhưng tạo đường nối chạy ngược,
    # người đọc phải lần lại — sai quy ước đọc của BPMN.
    ("Task_XuatPDF", "task", "Xuất PDF theo mẫu\nthương hiệu", "Lane_PhatHanh", 3160, 0),
    ("Task_ThongBao", "sendTask", "Gửi bản tin Telegram", "Lane_PhatHanh", 3350, 0),
    ("Task_SaoLuu", "task", "Sao lưu CSDL & sản phẩm", "Lane_PhatHanh", 3540, 0),
    ("End_HoanTat", "endEvent", "Hoàn tất lượt chạy", "Lane_PhatHanh", 3760, 0),
]

# (id, nguồn, đích, nhãn)
FLOWS: list[tuple[str, str, str, str]] = [
    ("f01", "Start_HangNgay", "Task_Khoa", ""),
    ("f02", "Task_Khoa", "GW_Quet_Split", ""),
    ("f03", "GW_Quet_Split", "Task_QuetTVPL", ""),
    ("f04", "GW_Quet_Split", "Task_QuetMOJ", ""),
    ("f05", "Task_QuetTVPL", "GW_Quet_Join", ""),
    ("f06", "Task_QuetMOJ", "GW_Quet_Join", ""),
    ("f07", "GW_Quet_Join", "GW_CoVanBan", ""),
    ("f08", "GW_CoVanBan", "End_NguonChet", "Không — nghi mất nguồn"),
    ("f09", "GW_CoVanBan", "Task_GopTrung", "Có"),
    ("f10", "Task_GopTrung", "Task_NapChiTiet", ""),
    ("f11", "Task_NapChiTiet", "Task_LamSach", ""),
    ("f12", "Task_LamSach", "Task_LuuDB", ""),
    ("f13", "Task_LuuDB", "GW_CoSuKien", ""),
    ("f14", "GW_CoSuKien", "Task_DongBo", "Có"),
    ("f15", "Task_DongBo", "Task_Nhung", ""),
    ("f16", "Task_Nhung", "Task_TruyXuat", ""),
    ("f17", "Task_TruyXuat", "Task_LocHieuLuc", ""),
    ("f18", "Task_LocHieuLuc", "Task_SinhBaoCao", ""),
    ("f19", "Task_SinhBaoCao", "Task_DoiChieu", ""),
    ("f20", "Task_DoiChieu", "GW_TrichDan", ""),
    ("f21", "GW_TrichDan", "End_ChanBaoCao", "Không"),
    ("f22", "GW_TrichDan", "Task_XuatPDF", "Có"),
    ("f23", "Task_XuatPDF", "Task_ThongBao", ""),
    ("f24", "Task_ThongBao", "Task_SaoLuu", ""),
    ("f25", "Task_SaoLuu", "End_HoanTat", ""),
    ("f26", "GW_CoSuKien", "Task_SaoLuu", "Không có gì mới"),
]

EVENTS = {"startEvent", "endEvent"}
GATEWAYS = {"exclusiveGateway", "parallelGateway"}


def geom(el: tuple) -> tuple[int, int, int, int]:
    """Khung chữ nhật (x, y, w, h) của một phần tử."""
    _id, kind, _name, lane, x, off = el
    if kind in EVENTS:
        w = h = EV_D
    elif kind in GATEWAYS:
        w = h = GW_D
    else:
        w, h = TASK_W, TASK_H
    return x, cy(lane, off) - h // 2, w, h


def build() -> ET.Element:
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)
    B, DI_, DC, DIA = (f"{{{NS['bpmn']}}}", f"{{{NS['bpmndi']}}}",
                       f"{{{NS['dc']}}}", f"{{{NS['di']}}}")

    defs = ET.Element(f"{B}definitions", {
        "id": "Definitions_TheoDoiVanBanPhapLuat",
        "targetNamespace": "https://thongtincty.com/bpmn",
        "exporter": "thuvienphapluat/scripts/generate_bpmn.py",
        "exporterVersion": "1.0",
    })

    collab = ET.SubElement(defs, f"{B}collaboration", {"id": "Collab_1"})
    ET.SubElement(collab, f"{B}participant", {
        "id": "Pool_HeThong", "name": "Hệ thống theo dõi văn bản pháp luật",
        "processRef": "Process_1",
    })

    proc = ET.SubElement(defs, f"{B}process", {
        "id": "Process_1", "isExecutable": "false",
    })

    lane_set = ET.SubElement(proc, f"{B}laneSet", {"id": "LaneSet_1"})
    by_lane: dict[str, list[str]] = {lid: [] for lid, _, _ in LANES}
    for el in ELEMENTS:
        by_lane[el[3]].append(el[0])
    for lid, lname, _ in LANES:
        lane = ET.SubElement(lane_set, f"{B}lane", {"id": lid, "name": lname})
        for ref in by_lane[lid]:
            ET.SubElement(lane, f"{B}flowNodeRef").text = ref

    incoming: dict[str, list[str]] = {}
    outgoing: dict[str, list[str]] = {}
    for fid, src, tgt, _ in FLOWS:
        outgoing.setdefault(src, []).append(fid)
        incoming.setdefault(tgt, []).append(fid)

    for eid, kind, name, _lane, _x, _off in ELEMENTS:
        attrs = {"id": eid}
        if name:
            attrs["name"] = name
        node = ET.SubElement(proc, f"{B}{kind}", attrs)
        for fid in incoming.get(eid, []):
            ET.SubElement(node, f"{B}incoming").text = fid
        for fid in outgoing.get(eid, []):
            ET.SubElement(node, f"{B}outgoing").text = fid

    for fid, src, tgt, label in FLOWS:
        attrs = {"id": fid, "sourceRef": src, "targetRef": tgt}
        if label:
            attrs["name"] = label
        ET.SubElement(proc, f"{B}sequenceFlow", attrs)

    # ── Diagram Interchange ──────────────────────────────────────────────────
    diagram = ET.SubElement(defs, f"{DI_}BPMNDiagram", {"id": "Diagram_1"})
    plane = ET.SubElement(diagram, f"{DI_}BPMNPlane",
                          {"id": "Plane_1", "bpmnElement": "Collab_1"})

    shape = ET.SubElement(plane, f"{DI_}BPMNShape", {
        "id": "Shape_Pool", "bpmnElement": "Pool_HeThong", "isHorizontal": "true"})
    ET.SubElement(shape, f"{DC}Bounds", {
        "x": str(POOL_X), "y": str(POOL_Y), "width": str(POOL_W), "height": str(POOL_H)})

    for lid, _lname, lh in LANES:
        s = ET.SubElement(plane, f"{DI_}BPMNShape", {
            "id": f"Shape_{lid}", "bpmnElement": lid, "isHorizontal": "true"})
        ET.SubElement(s, f"{DC}Bounds", {
            "x": str(POOL_X + LANE_LABEL_W), "y": str(_lane_top[lid]),
            "width": str(POOL_W - LANE_LABEL_W), "height": str(lh)})

    for el in ELEMENTS:
        eid, kind, name, _lane, _x, _off = el
        x, y, w, h = geom(el)
        s = ET.SubElement(plane, f"{DI_}BPMNShape",
                          {"id": f"Shape_{eid}", "bpmnElement": eid})
        ET.SubElement(s, f"{DC}Bounds", {
            "x": str(x), "y": str(y), "width": str(w), "height": str(h)})
        # Nhãn của sự kiện và cổng nằm ngoài hình, cần khung nhãn riêng
        if kind in EVENTS | GATEWAYS and name:
            lbl = ET.SubElement(s, f"{DI_}BPMNLabel")
            ET.SubElement(lbl, f"{DC}Bounds", {
                "x": str(x - 40), "y": str(y + h + 4),
                "width": str(w + 80), "height": "32"})

    box = {el[0]: geom(el) for el in ELEMENTS}
    for fid, src, tgt, label in FLOWS:
        sx, sy, sw, sh = box[src]
        tx, ty, tw, th = box[tgt]
        edge = ET.SubElement(plane, f"{DI_}BPMNEdge",
                             {"id": f"Edge_{fid}", "bpmnElement": fid})
        # Đi ngang khi cùng hàng, còn lại bẻ góc vuông qua điểm giữa
        if abs((sy + sh // 2) - (ty + th // 2)) < 6:
            pts = [(sx + sw, sy + sh // 2), (tx, ty + th // 2)]
        elif tx >= sx:
            midx = sx + sw + max(20, (tx - sx - sw) // 2)
            pts = [(sx + sw, sy + sh // 2), (midx, sy + sh // 2),
                   (midx, ty + th // 2), (tx, ty + th // 2)]
        else:  # đi ngược về trái: vòng xuống dưới
            pts = [(sx + sw // 2, sy + sh), (sx + sw // 2, ty + th // 2),
                   (tx + tw, ty + th // 2)]
        for px, py in pts:
            ET.SubElement(edge, f"{DIA}waypoint", {"x": str(px), "y": str(py)})
        if label:
            lbl = ET.SubElement(edge, f"{DI_}BPMNLabel")
            mx, my = pts[len(pts) // 2]
            ET.SubElement(lbl, f"{DC}Bounds", {
                "x": str(mx - 60), "y": str(my - 26),
                "width": "120", "height": "24"})

    return defs


def validate(defs: ET.Element) -> list[str]:
    """Tự kiểm: mọi luồng phải nối phần tử có thật, mọi phần tử phải có hình."""
    loi: list[str] = []
    ids = {e[0] for e in ELEMENTS}
    for fid, src, tgt, _ in FLOWS:
        if src not in ids:
            loi.append(f"{fid}: nguồn '{src}' không tồn tại")
        if tgt not in ids:
            loi.append(f"{fid}: đích '{tgt}' không tồn tại")

    shapes = {s.get("bpmnElement") for s in defs.iter(f"{{{NS['bpmndi']}}}BPMNShape")}
    for eid in ids:
        if eid not in shapes:
            loi.append(f"{eid}: thiếu BPMNShape")
    edges = {e.get("bpmnElement") for e in defs.iter(f"{{{NS['bpmndi']}}}BPMNEdge")}
    for fid, *_ in FLOWS:
        if fid not in edges:
            loi.append(f"{fid}: thiếu BPMNEdge")

    # Phần tử treo: không có luồng vào lẫn luồng ra
    noi = {s for _, s, _, _ in FLOWS} | {t for _, _, t, _ in FLOWS}
    for eid in ids - noi:
        loi.append(f"{eid}: không nối với luồng nào")

    # Sự kiện đầu không được có luồng vào; sự kiện cuối không được có luồng ra
    for eid, kind, *_ in ELEMENTS:
        if kind == "startEvent" and any(t == eid for _, _, t, _ in FLOWS):
            loi.append(f"{eid}: startEvent không được có luồng vào")
        if kind == "endEvent" and any(s == eid for _, s, _, _ in FLOWS):
            loi.append(f"{eid}: endEvent không được có luồng ra")
    return loi


def main() -> int:
    defs = build()
    loi = validate(defs)
    if loi:
        print("SƠ ĐỒ KHÔNG HỢP LỆ:")
        for x in loi:
            print("  -", x)
        return 1

    tree = ET.ElementTree(defs)
    ET.indent(tree, space="  ")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tree.write(OUT, encoding="utf-8", xml_declaration=True)

    print(f"Đã ghi {OUT}")
    print(f"  {len(ELEMENTS)} phần tử · {len(FLOWS)} luồng · {len(LANES)} lane")
    print("  tự kiểm: hợp lệ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
