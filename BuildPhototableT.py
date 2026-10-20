#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
BuildPhototableT.py — процессуальный сборщик фототаблицы по JSON-манифесту.

Особенности:
    - Сортировка кадров строго по SlideNum (1, 2, 3...)
    - По умолчанию JPEG вшивается напрямую как есть (без пережатия и потерь)
    - Ключ -c (--compress): оптимизация до 1920px с автоопределением родного сжатия
    - Поддержка STDIN: при отсутствии аргументов читает манифест из пайпа
"""

import argparse
import glob
import io
import json
import os
import re
import sys
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# --- РЕГИСТРАЦИЯ ШРИФТОВ ---
def find_font(bundled_name, candidates):
    bundled = os.path.join(SCRIPT_DIR, "fonts", bundled_name)
    if os.path.exists(bundled):
        return bundled
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(f"Не найден шрифт '{bundled_name}'.")

try:
    REGULAR_FONT = find_font("DejaVuSans.ttf", [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        r"C:\Windows\Fonts\arial.ttf"
    ])
    BOLD_FONT = find_font("DejaVuSans-Bold.ttf", [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        r"C:\Windows\Fonts\arialbd.ttf"
    ])
    pdfmetrics.registerFont(TTFont("PT_Sans", REGULAR_FONT))
    pdfmetrics.registerFont(TTFont("PT_SansBold", BOLD_FONT))
except Exception as e:
    sys.stderr.write(f"[WARN] Ошибка шрифтов: {e}.\n")


# --- ОБРАБОТКА МЕТАДАННЫХ ШАПКИ И ДАТ ---
def load_title_file(file_path):
    if not file_path or not os.path.exists(file_path):
        return {}
    if file_path.lower().endswith(".json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                return d.get("title_page", d) if isinstance(d, dict) else {}
        except Exception:
            return {}
    info = {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        if lines:
            info["title"] = lines[0]
            if len(lines) > 1: info["subtitle"] = lines[1]

        extra_lines = []
        for line in lines[2:]:
            if ":" in line:
                k, v = line.split(":", 1)
                kl, vr = k.strip().lower(), v.strip()
                if "место" in kl: info["location"] = vr
                elif "дат" in kl: info["datetime"] = vr
                elif "услови" in kl: info["road_conditions"] = vr
                elif "норм" in kl or "гост" in kl: info["methodology"] = vr
                else: extra_lines.append(f"<b>{k.strip()}:</b> {vr}")
            else:
                extra_lines.append(line)
        if extra_lines:
            info["extra_description"] = "<br/>".join(extra_lines)
    except Exception:
        pass
    return info

def parse_time_from_filename(fname):
    m = re.search(r'(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})', fname)
    if m:
        y, mo, d, hh, mm, ss = map(int, m.groups())
        return datetime(y, mo, d, hh, mm, ss)
    return None


# --- ОПТИМИЗАЦИЯ И СЖАТИЕ ИЗОБРАЖЕНИЙ ---
def detect_native_jpeg_quality(img_path):
    """Оценивает исходное качество JPEG по матрице квантования DQT."""
    try:
        from PIL import Image as PILImage
        with PILImage.open(img_path) as im:
            if hasattr(im, "quantization") and im.quantization:
                q_table = im.quantization.get(0)
                if q_table:
                    avg = sum(q_table) / len(q_table)
                    return max(65, min(95, int(100 - avg * 0.75)))
    except Exception:
        pass
    return 80

def prepare_image_source(img_path, compress=False, quality=None, max_dim=1920):
    """
    Если compress=False -> передаёт файл в ReportLab напрямую (pass-through).
    Если compress=True  -> пропорционально уменьшает и жмет в буфере памяти.
    """
    if not compress:
        return img_path

    try:
        from PIL import Image as PILImage, ImageOps
        target_q = quality or detect_native_jpeg_quality(img_path)

        with PILImage.open(img_path) as im:
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            scale = min(max_dim / max(w, h), 1.0)

            if scale < 1.0:
                new_w, new_h = int(w * scale), int(h * scale)
                im = im.resize((new_w, new_h), PILImage.Resampling.LANCZOS)

            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=target_q, optimize=True)
            buf.seek(0)
            return buf
    except Exception as e:
        sys.stderr.write(f"[WARN] Ошибка сжатия {img_path}: {e}. Исходник оставлен как есть.\n")
        return img_path

def scale_image(img_source, max_w, max_h):
    try:
        reader = ImageReader(img_source)
        iw, ih = reader.getSize()
        scale = min(max_w / iw, max_h / ih, 1.0)
        return Image(img_source, width=iw * scale, height=ih * scale, hAlign="CENTER")
    except Exception:
        return None


# --- ЗАГРУЗКА, РАЗРЕШЕНИЕ ПУТЕЙ И СОРТИРОВКА МАНИФЕСТА ---
def load_manifest(raw_sources):
    """Загружает кадры и сортирует строго по SlideNum (1, 2, 3...)."""
    raw_frames = []
    json_meta = {}

    for src in raw_sources:
        if isinstance(src, str):
            j_dir = os.path.dirname(os.path.abspath(src))
            with open(src, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            j_dir = os.getcwd()
            data = src

        if isinstance(data, list):
            raw_frames.extend(data)
        elif isinstance(data, dict):
            for k in ["title", "subtitle", "norm", "methodology", "date", "datetime",
                      "disclaimer", "location", "road_conditions", "extra_description"]:
                if k in data and k not in json_meta:
                    json_meta[k] = data[k]
            if "title_page" in data and isinstance(data["title_page"], dict):
                json_meta.update(data["title_page"])

            frames = data.get("frames")
            if frames is None:
                frames = data.get("items", [])
            for fr in frames:
                fr["_base_dir"] = j_dir
                raw_frames.append(fr)

    valid_frames = []

    for idx, item in enumerate(raw_frames, start=1):
        file_path = item.get("path") or item.get("filename")
        if not file_path:
            continue

        resolved_path = None
        if os.path.isabs(file_path) and os.path.exists(file_path):
            resolved_path = file_path
        else:
            base_dir = item.get("_base_dir", "")
            for cand in [os.path.join(base_dir, file_path), os.path.abspath(file_path), os.path.abspath(os.path.basename(file_path))]:
                if os.path.exists(cand):
                    resolved_path = cand
                    break

        if not resolved_path:
            print(f"  [WARN] Файл не найден на диске: {file_path}")
            continue

        file_name = os.path.basename(resolved_path)
        dt_from_file = parse_time_from_filename(file_name)
        display_time = item.get("parsed_datetime") or (dt_from_file.strftime("%Y-%m-%d %H:%M:%S") if dt_from_file else "")

        slide_num = str(item.get("SlideNum") or idx)

        valid_frames.append({
            "slide_num": slide_num,
            "title": item.get("title", f"Объект контроля № {slide_num}"),
            "theme": item.get("theme", ""),
            "description": item.get("description", ""),
            "display_time": display_time,
            "img_path": resolved_path
        })

    # СОРТИРОВКА СТРОГО ПО SlideNum: 1, 2, 3, 4...
    def get_sort_key(fr):
        m = re.search(r'\d+', str(fr.get("slide_num", "")))
        return (0, int(m.group(0))) if m else (1, str(fr.get("slide_num", "")))

    valid_frames.sort(key=get_sort_key)

    print(f"[*] Загружено кадров : {len(valid_frames)} (отсортированы по SlideNum 1, 2, 3...)")
    return valid_frames, json_meta


def parse_markdown_to_flowables(md_path):
    if not md_path or not os.path.exists(md_path):
        return []

    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    flowables = []
    h1_st = ParagraphStyle("MD_H1", fontName="PT_SansBold", fontSize=13, leading=16, spaceBefore=10, spaceAfter=4, textColor="#111111")
    h2_st = ParagraphStyle("MD_H2", fontName="PT_SansBold", fontSize=11, leading=14, spaceBefore=8, spaceAfter=3, textColor="#222222")
    h3_st = ParagraphStyle("MD_H3", fontName="PT_SansBold", fontSize=10, leading=12.5, spaceBefore=6, spaceAfter=2, textColor="#333333")
    body_st = ParagraphStyle("MD_Body", fontName="PT_Sans", fontSize=9, leading=12.5, spaceAfter=4, textColor="#111111")
    bullet_st = ParagraphStyle("MD_Bul", fontName="PT_Sans", fontSize=9, leading=12.5, leftIndent=14, firstLineIndent=-10, spaceAfter=2.5, textColor="#111111")
    quote_st = ParagraphStyle("MD_Q", fontName="PT_Sans", fontSize=8.5, leading=11.5, leftIndent=15, rightIndent=15, textColor="#444444", spaceAfter=4)
    tbl_hdr_st = ParagraphStyle("MD_TH", fontName="PT_SansBold", fontSize=8.5, leading=11, textColor="#111111")
    tbl_cell_st = ParagraphStyle("MD_TD", fontName="PT_Sans", fontSize=8, leading=10.5, textColor="#222222")
    avail_w = A4[0] - 2 * (1.3 * cm)

    def format_inline_text(text):
        t = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        t = re.sub(r'`(.*?)`', r'<font face="Courier">\1</font>', t)
        t = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', t)
        t = re.sub(r'__(.*?)__', r'<b>\1</b>', t)
        t = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<i>\1</i>', t)
        t = re.sub(r'(?<!_)_(?!_)(.*?)(?<!_)_(?!_)', r'<i>\1</i>', t)
        return t

    i, num_lines = 0, len(lines)
    while i < num_lines:
        raw = lines[i].rstrip("\r\n")
        s = raw.strip()

        if not s:
            flowables.append(Spacer(1, 3))
            i += 1
            continue

        if s in ("\\newpage", "---", "***"):
            flowables.append(PageBreak())
            i += 1
            continue

        if s.startswith("|") and s.endswith("|"):
            tbl_raw_rows = []
            while i < num_lines and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                row_str = lines[i].strip()
                cells = [c.strip() for c in row_str.split("|")[1:-1]]
                if not all(re.match(r'^[:\- ]+$', c) for c in cells if c):
                    tbl_raw_rows.append(cells)
                i += 1

            if tbl_raw_rows:
                max_cols = max(len(r) for r in tbl_raw_rows)
                for r in tbl_raw_rows:
                    while len(r) < max_cols: r.append("")

                col_lens = [max(len(r[c]) for r in tbl_raw_rows) for c in range(max_cols)]
                weights = [max(8, l) for l in col_lens]
                tot_w = sum(weights)
                col_widths = [(w / tot_w) * avail_w for w in weights]

                tbl_data = []
                for r_idx, row in enumerate(tbl_raw_rows):
                    row_cells = []
                    cur_st = tbl_hdr_st if (r_idx == 0) else tbl_cell_st
                    for cell in row:
                        html_cell = format_inline_text(cell)
                        try:
                            row_cells.append(Paragraph(html_cell, cur_st))
                        except Exception:
                            row_cells.append(Paragraph(re.sub(r'<[^>]+>', '', html_cell), cur_st))
                    tbl_data.append(row_cells)

                t_elem = Table(tbl_data, colWidths=col_widths, repeatRows=1)
                t_elem.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), '#EBEBEB'),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('GRID', (0, 0), (-1, -1), 0.5, '#AAAAAA'),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                    ('LEFTPADDING', (0, 0), (-1, -1), 4),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ]))
                flowables.append(Spacer(1, 4))
                flowables.append(t_elem)
                flowables.append(Spacer(1, 6))
            continue

        prefix, style = "", body_st
        if s.startswith("### "): style, content = h3_st, s[4:].strip()
        elif s.startswith("## "): style, content = h2_st, s[3:].strip()
        elif s.startswith("# "): style, content = h1_st, s[2:].strip()
        elif s.startswith("> "): style, content = quote_st, s[2:].strip()
        elif s.startswith("- ") or s.startswith("* "): style, prefix, content = bullet_st, "&bull; &nbsp;", s[2:].strip()
        elif re.match(r'^\d+\.\s', s):
            m = re.match(r'^(\d+\.)\s+(.*)', s)
            style, prefix, content = bullet_st, f"<b>{m.group(1)}</b> &nbsp;", m.group(2).strip()
        else: style, content = body_st, raw.strip()

        final_html = prefix + format_inline_text(content)
        try:
            flowables.append(Paragraph(final_html, style))
        except Exception:
            flowables.append(Paragraph(re.sub(r'<[^>]+>', '', final_html), style))
        i += 1

    return flowables


# --- СБОРКА ИТОГОВОГО PDF ---
def build_pdf(raw_sources, output_pdf, args):
    valid_frames, json_meta = load_manifest(raw_sources)
    if not valid_frames:
        sys.exit("[ERROR] Нет валидных кадров для верстки. PDF не создан.")

    auto_date = ""
    for fr in valid_frames:
        if fr.get("display_time"):
            auto_date = fr["display_time"].split()[0]
            break

    doc_title = getattr(args, 'title', None) or json_meta.get("title") or "ФОТОТАБЛИЦА ОБЪЕКТИВНОГО КОНТРОЛЯ"
    doc_subtitle = getattr(args, 'subtitle', None) or json_meta.get("subtitle") or "к материалам фиксации нарушений требований стандартов"
    doc_methodology = getattr(args, 'methodology', None) or json_meta.get("norm") or json_meta.get("methodology") or "ГОСТ Р 50597-2017, ст. 12.34 КоАП РФ"
    doc_datetime = getattr(args, 'date', None) or json_meta.get("date") or json_meta.get("datetime") or auto_date or datetime.now().strftime("%Y-%m-%d")

    title_info = {
        "title": doc_title,
        "subtitle": doc_subtitle,
        "datetime": doc_datetime,
        "methodology": doc_methodology,
        "location": json_meta.get("location"),
        "road_conditions": json_meta.get("road_conditions"),
        "extra_description": json_meta.get("extra_description"),
        "disclaimer": json_meta.get("disclaimer")
    }

    if args.title_file:
        title_info.update(load_title_file(args.title_file))

    styles = getSampleStyleSheet()
    doc_title_style = ParagraphStyle("DocTitle", fontName="PT_SansBold", fontSize=15, leading=19, alignment=1, spaceAfter=5)
    doc_sub_style = ParagraphStyle("DocSub", fontName="PT_Sans", fontSize=10, leading=14, alignment=1, spaceAfter=10)
    meta_val = ParagraphStyle("MetaV", fontName="PT_Sans", fontSize=9, leading=13, spaceAfter=5, textColor="#222222")
    disclaimer_style = ParagraphStyle("Disc", fontName="PT_Sans", fontSize=8, leading=11, textColor="#555555", spaceBefore=10, spaceAfter=5)

    photo_num_style = ParagraphStyle("PhotoNum", fontName="PT_SansBold", fontSize=14, leading=16, alignment=1, spaceAfter=8, textColor="#111111")
    frame_title_style = ParagraphStyle("FrameTitle", fontName="PT_SansBold", fontSize=11, leading=14, alignment=1, spaceAfter=8, textColor="#111111")
    frame_theme_style = ParagraphStyle("FrameTheme", fontName="PT_SansBold", fontSize=10, leading=12, textColor="#990000")
    frame_time_style = ParagraphStyle("FrameTime", fontName="PT_Sans", fontSize=9, leading=12, alignment=2, textColor="#555555")
    frame_bottom_style = ParagraphStyle("FrameBottom", fontName="PT_Sans", fontSize=10, leading=14, spaceBefore=8, textColor="#111111")

    page_w, page_h = A4
    margin = 1.3 * cm
    doc = SimpleDocTemplate(output_pdf, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin)
    story = []

    if args.md_file:
        md_items = parse_markdown_to_flowables(args.md_file)
        if md_items:
            story.extend(md_items)
            story.append(PageBreak())

    # Титульный лист
    story.append(Paragraph(title_info["title"], doc_title_style))
    story.append(Paragraph(title_info["subtitle"], doc_sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color="#888888", spaceBefore=0, spaceAfter=10))

    def add_meta_row(label, val):
        if val: story.append(Paragraph(f"<b>{label}:</b> {val}", meta_val))

    add_meta_row("Место фиксации", title_info.get("location"))
    add_meta_row("Дата фиксации", title_info.get("datetime"))
    add_meta_row("Дорожные условия", title_info.get("road_conditions"))
    add_meta_row("Нормативная база", title_info.get("methodology"))
    add_meta_row("Всего зафиксировано объектов", f"{len(valid_frames)} единиц")

    if title_info.get("extra_description"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(title_info["extra_description"], meta_val))

    show_disclaimer = not args.no_disclaimer
    if "disclaimer" in json_meta and json_meta["disclaimer"] is False:
        show_disclaimer = False

    if show_disclaimer:
        disc_text = title_info.get("disclaimer") or (
            "<b>ПРИМЕЧАНИЕ / ДИСКЛЕЙМЕР:</b> Материалы фототаблицы получены и структурированы "
            "программным комплексом объективной фиксации нарушений."
        )
        story.append(Spacer(1, 12))
        story.append(HRFlowable(width="100%", thickness=0.5, color="#CCCCCC", spaceBefore=4, spaceAfter=6))
        story.append(Paragraph(disc_text, disclaimer_style))

    story.append(PageBreak())

    # Карточки объектов (строго по SlideNum: 1, 2, 3...)
    max_img_h = 16.5 * cm
    content_w = page_w - 2 * margin

    compress_mode = args.compress or (args.quality is not None)
    if compress_mode:
        print(f"[*] Режим сжатия : ВКЛ (max_dim={args.max_dim}px, quality={args.quality or 'auto-native'})")
    else:
        print("[*] Режим сжатия : ВЫКЛ (оригинальные JPEG без потерь)")

    for idx, fr in enumerate(valid_frames, start=1):
        clean_title = re.sub(r'^(?:(?:Фото|Кадр)\s*№?\s*\d+|[0-9]+|[./:\s-])+\s*', '', fr['title'], flags=re.IGNORECASE).strip()
        final_title = clean_title or fr['title']

        num_text = f"Фото № {fr['slide_num']}"
        story.append(Paragraph(num_text, photo_num_style))
        story.append(Paragraph(final_title, frame_title_style))

        # Подготовка изображения: прямой pass-through или сжатие
        img_source = prepare_image_source(
            fr["img_path"],
            compress=compress_mode,
            quality=args.quality,
            max_dim=args.max_dim
        )

        img_flow = scale_image(img_source, content_w, max_img_h)
        if img_flow:
            story.append(img_flow)

        theme_p = Paragraph(f"Тематика: {fr['theme']}", frame_theme_style) if fr["theme"] else Paragraph("", frame_theme_style)
        time_p = Paragraph(f"Фиксация: {fr['display_time']}", frame_time_style) if fr["display_time"] else Paragraph("", frame_time_style)

        meta_table = Table([[theme_p, time_p]], colWidths=[content_w * 0.7, content_w * 0.3])
        meta_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (0,0), 'LEFT'),
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ]))
        story.append(meta_table)

        if fr["description"]:
            desc_html = fr["description"].replace("\n", "<br/>")
            story.append(Paragraph(desc_html, frame_bottom_style))

        if idx < len(valid_frames):
            story.append(PageBreak())

    doc.build(story)
    file_size_mb = os.path.getsize(output_pdf) / (1024 * 1024)
    print(f"\n[+] ГОТОВО! Фототаблица сохранена: {output_pdf} ({file_size_mb:.2f} MB)")
    print(f"    Сверстано страниц с дефектами: {len(valid_frames)}")


def main():
    parser = argparse.ArgumentParser(
        description="BuildPhototableT.py — процессуальный сборщик фототаблицы с сортировкой по SlideNum."
    )
    parser.add_argument("inputs", nargs="*", help="Файлы манифеста (.json / .txt) или '-' для stdin")
    parser.add_argument("-o", "--out", default=None, help="Имя выходного PDF файла")
    parser.add_argument("-t", "--title", default=None, help="Свой заголовок документа")
    parser.add_argument("-tfn", "--title-file", dest="title_file", default=None, help="Файл с шапкой титульного листа (.txt)")
    parser.add_argument("-md", "--markdown", dest="md_file", default=None, help="Markdown-файл (.md) для вставки перед фототаблицей")
    parser.add_argument("-c", "--compress", action="store_true", help="Сжать фото перед вставкой (уменьшает PDF с 50MB до 2MB)")
    parser.add_argument("-q", "--quality", type=int, default=None, help="Качество JPEG (1-100, по умолчанию auto-native)")
    parser.add_argument("--max-dim", type=int, default=1920, help="Макс. размер стороны фото при сжатии в px (по умолчанию 1920)")
    parser.add_argument("--no-disclaimer", action="store_true", help="Отключить дисклеймер")

    args = parser.parse_args()

    raw_sources = []

    # 1. Считываем аргументы или STDIN
    if args.inputs:
        for item in args.inputs:
            if item == "-":
                try:
                    raw_sources.append(json.load(sys.stdin))
                except Exception as e:
                    sys.exit(f"[ERROR] Ошибка чтения JSON из stdin: {e}")
            else:
                matched = glob.glob(item)
                if matched:
                    raw_sources.extend([os.path.abspath(f) for f in matched])
                elif os.path.exists(item):
                    raw_sources.append(os.path.abspath(item))
    else:
        # При отсутствии аргументов берем из stdin (если передан пайп)
        if not sys.stdin.isatty():
            try:
                raw_sources.append(json.load(sys.stdin))
            except Exception as e:
                sys.exit(f"[ERROR] Ошибка чтения JSON из stdin: {e}")
        else:
            parser.print_help()
            sys.exit(0)

    if not raw_sources:
        sys.exit("[ERROR] Манифест не найден.")

    out_pdf = args.out
    if not out_pdf:
        if isinstance(raw_sources[0], str):
            base = os.path.splitext(os.path.basename(raw_sources[0]))[0]
            out_pdf = f"{base}_report.pdf"
        else:
            out_pdf = "phototable_report.pdf"

    build_pdf(raw_sources, out_pdf, args)


if __name__ == "__main__":
    main()