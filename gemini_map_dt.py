#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""gemini_map_dt.py  --  маппер манифеста к фото по распознанному времени (datetime index).

Поддерживает работу в Unix-пайплайне:
    - Читает манифест из файла или STDIN
    - Выводит обновленный манифест в файл или STDOUT
    - Все логи и отладка выводятся строго в stderr (stdlog)
    - Ключ -c: сжимает найденные фото до 1920px и сохраняет в ./img с расширением .jpg

Примеры:
    gemini_map_dt.py "manifest.txt" --dir "K:\Photos" -c
    gemini_map_dt.py "manifest.txt" --dir "K:\Photos" -c -q 75
    type manifest.json | gemini_map_dt.py --dir "K:\Photos" -c | BuildPhototableT.py -o out.pdf
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

MEDIA_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".mp4")

RU_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5,
    "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12
}


def log(*args, **kwargs):
    """Вывод информационных сообщений строго в stderr, чтобы stdout оставался чистым для JSON."""
    print(*args, file=sys.stderr, flush=True, **kwargs)


def normalize_cli_path(p):
    r"""Исправляет баг Windows cmd.exe: аргумент "C:\path\" парсится с кавычкой на конце (\")."""
    if not p:
        return ""
    p = p.strip()
    while p.endswith('"') or p.endswith("'"):
        p = p[:-1]
    return os.path.abspath(p)


def parse_dt_from_string(s):
    """Извлекает datetime из строки (ISO, EXIF с двоеточиями, русский OCR-штамп или имя файла)."""
    if not s or not isinstance(s, str):
        return None

    # 1. Формат YYYY-MM-DD HH:MM:SS, YYYY.MM.DD HH:MM:SS или EXIF YYYY:MM:DD HH:MM:SS
    m = re.search(r'(\d{4})[-./:](\d{2})[-./:](\d{2})\s+(\d{2}):(\d{2}):(\d{2})', s)
    if m:
        y, mo, d, h, mi, sec = map(int, m.groups())
        return datetime(y, mo, d, h, mi, sec)

    # 2. Формат имени файла YYYYMMDD_HHMMSS
    m = re.search(r'(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})', s)
    if m:
        y, mo, d, h, mi, sec = map(int, m.groups())
        return datetime(y, mo, d, h, mi, sec)

    # 3. Формат русского штампа OCR: '9 окт. 2026 г. 15:54:24' или '17 октября 2026 12:41:14'
    m = re.search(r'(\d{1,2})\s+([а-яА-ЯёЁ]+)[.]?\s+(\d{4})\s*(?:г[.]?)?\s*(\d{2}):(\d{2}):(\d{2})', s)
    if m:
        d = int(m.group(1))
        mon_str = m.group(2).lower()[:3]
        y = int(m.group(3))
        h, mi, sec = int(m.group(4)), int(m.group(5)), int(m.group(6))
        mo = RU_MONTHS.get(mon_str)
        if mo:
            return datetime(y, mo, d, h, mi, sec)

    return None


def detect_native_jpeg_quality(img_path):
    """Оценивает исходное качество JPEG по таблице квантования DQT."""
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


def compress_and_save_image(src_path, dest_dir, max_dim=1920, quality=None):
    """Сжимает фото (до max_dim с качеством quality) и сохраняет в dest_dir с расширением .jpg."""
    os.makedirs(dest_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(src_path))[0]
    # Очищаем дубликаты вида " (1)"
    clean_base = re.sub(r'\s*\(\d+\)$', '', base_name).strip()
    dest_path = os.path.abspath(os.path.join(dest_dir, f"{clean_base}.jpg"))

    try:
        from PIL import Image, ImageOps
        target_q = quality or detect_native_jpeg_quality(src_path)
        with Image.open(src_path) as im:
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            scale = min(max_dim / max(w, h), 1.0)
            if scale < 1.0:
                im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            im.convert("RGB").save(dest_path, "JPEG", quality=target_q, optimize=True)
            return dest_path
    except Exception as e:
        log(f"[WARN] Ошибка сжатия {src_path}: {e}. Копирую оригинал как есть.")
        shutil.copy2(src_path, dest_path)
        return dest_path


def inspect_exif_and_streams(fpath):
    """Считывает EXIF теги и файловые потоки (NTFS ADS, XMP, COM)."""
    res = {
        "exif_dt": None,
        "exif_source": None,
        "exif_meta": {},
        "streams": {}
    }

    # 1. Проверка EXIF через Pillow
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
        with Image.open(fpath) as img:
            raw_exif = img._getexif() or {}
            for tag_id, val in raw_exif.items():
                name = TAGS.get(tag_id, str(tag_id))
                if name in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                    dt = parse_dt_from_string(str(val))
                    if dt and not res["exif_dt"]:
                        res["exif_dt"] = dt
                        res["exif_source"] = f"EXIF:{name}"
                if name in ("Make", "Model", "Software", "DateTimeOriginal", "GPSInfo"):
                    if isinstance(val, (str, int, float)):
                        res["exif_meta"][name] = str(val).strip()
    except Exception:
        pass

    # 2. Проверка NTFS Alternate Data Streams (ADS) в Windows
    if sys.platform == "win32":
        for sname in ("datetime", "exif", "meta", "time", "date"):
            ads_path = f"{fpath}:{sname}"
            try:
                with open(ads_path, "r", encoding="utf-8", errors="ignore") as sf:
                    txt = sf.read().strip()
                    if txt:
                        res["streams"][f"NTFS:{sname}"] = txt
                        if not res["exif_dt"]:
                            dt = parse_dt_from_string(txt)
                            if dt:
                                res["exif_dt"] = dt
                                res["exif_source"] = f"NTFS:{sname}"
            except OSError:
                pass

    # 3. Поиск XMP и бинарных потоков даты в заголовке файла
    try:
        with open(fpath, "rb") as f:
            head = f.read(131072)

            m = re.search(r'(?:xmp:CreateDate|photoshop:DateCreated|CreateDate)>([^<]+)<',
                          head.decode("latin1", errors="ignore"))
            if m:
                xmp_val = m.group(1).strip()
                res["streams"]["XMP:CreateDate"] = xmp_val
                if not res["exif_dt"]:
                    dt = parse_dt_from_string(xmp_val)
                    if dt:
                        res["exif_dt"] = dt
                        res["exif_source"] = "XMP:CreateDate"

            pos = 0
            while pos < len(head) - 4:
                if head[pos:pos + 2] == b"\xff\xfe":
                    length = int.from_bytes(head[pos + 2:pos + 4], "big")
                    com_bytes = head[pos + 4:pos + 2 + length]
                    try:
                        com_txt = com_bytes.decode("utf-8").strip()
                        if com_txt:
                            res["streams"]["JPEG:COM"] = com_txt
                    except UnicodeDecodeError:
                        pass
                    break
                pos += 1
    except Exception:
        pass

    return res


def scan_folder_media(folder):
    """Сканирует папку и индексирует файлы по дате из имени."""
    index = []
    for entry in os.scandir(folder):
        if not entry.is_file():
            continue
        ext = os.path.splitext(entry.name)[1].lower()
        if ext not in MEDIA_EXTS:
            continue

        dt = parse_dt_from_string(entry.name)
        index.append({
            "name": entry.name,
            "path": os.path.abspath(entry.path),
            "dt": dt,
            "size": entry.stat().st_size
        })
    return index


def main():
    ap = argparse.ArgumentParser(
        description="Маппер манифеста к фото по времени (поддерживает STDIN/STDOUT и локальное сжатие)."
    )
    ap.add_argument("manifest", nargs="?", help="путь к JSON-манифесту (при отсутствии читается из STDIN)")
    ap.add_argument("--dir", "--folder", dest="folder", help="папка с фотографиями (по умолчанию: папка манифеста или текущая)")
    ap.add_argument("-c", "--compress", dest="compress", action="store_true",
                    help="сжать фото до 1920px и сохранить в локальную папку (по умолчанию: ./img)")
    ap.add_argument("--dest", "--copy-dir", dest="dest_dir", default="img", metavar="DIR",
                    help="папка для сохранения сжатых фото при ключе -c (по умолчанию: ./img)")
    ap.add_argument("-q", "--quality", type=int, default=None, help="качество JPEG (1-100, по умолчанию auto-native)")
    ap.add_argument("--max-dim", type=int, default=1920, help="макс. размер стороны фото при сжатии в px (по умолчанию 1920)")
    ap.add_argument("-v", "--verify", action="store_true", help="проверять EXIF и стрим даты внутри файла")
    ap.add_argument("-d", "--detail", "--debug", dest="detail", action="store_true", help="выводить подробные данные проверки")
    ap.add_argument("--tolerance", type=int, default=2, help="допуск времени в секундах (по умолчанию 2)")
    ap.add_argument("--stdout", action="store_true", help="принудительно вывести итоговый JSON в stdout даже при наличии файла")
    ap.add_argument("--dry-run", action="store_true", help="показать маппинг без изменения файлов")
    ap.add_argument("--backup", action="store_true", help="создать .bak копию манифеста перед записью")

    # Если вызов без аргументов и в stdin ничего не передано
    if len(sys.argv) == 1 and sys.stdin.isatty():
        ap.print_help(sys.stderr)
        sys.exit(0)

    a = ap.parse_args()

    # 1. Читаем манифест: из файла или из STDIN
    manifest_path = None
    from_stdin = False

    if a.manifest:
        manifest_path = normalize_cli_path(a.manifest)
        if not os.path.exists(manifest_path):
            log(f"[!] Файл манифеста не найден: {manifest_path}")
            sys.exit(1)
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        if not sys.stdin.isatty():
            try:
                data = json.load(sys.stdin)
                from_stdin = True
            except Exception as e:
                log(f"[!] Ошибка чтения JSON из STDIN: {e}")
                sys.exit(1)
        else:
            ap.print_help(sys.stderr)
            sys.exit(0)

    # 2. Определяем папку поиска фотографий
    if a.folder:
        search_dir = normalize_cli_path(a.folder)
    elif manifest_path:
        search_dir = os.path.dirname(manifest_path)
    else:
        search_dir = os.getcwd()

    if not os.path.isdir(search_dir):
        log(f"[!] Папка поиска не найдена: {search_dir}")
        sys.exit(1)

    log(f"[*] Источник манифеста : {'STDIN' if from_stdin else manifest_path}")
    log(f"[*] Папка поиска фото  : {search_dir}")
    
    do_compress = a.compress or (a.quality is not None)
    if do_compress:
        q_str = f"q={a.quality}" if a.quality else "q=auto-native"
        log(f"[*] Сжатие фото (-c)     : ВКЛ -> ./{a.dest_dir} ({a.max_dim}px, {q_str})")
    else:
        log("[*] Сжатие фото (-c)     : ВЫКЛ (ссылаемся на оригиналы без копирования)")
        
    log(f"[*] Допуск времени     : ±{a.tolerance} сек")

    if isinstance(data, list):
        frames = data
    elif isinstance(data, dict):
        frames = data.get("frames") or data.get("items") or []
    else:
        log("[!] Неизвестная структура манифеста")
        sys.exit(1)

    if not frames:
        log("[!] В манифесте не найдено записей (frames/items).")
        sys.exit(1)

    # 3. Индексируем медиафайлы в папке
    media_pool = scan_folder_media(search_dir)
    log(f"[*] Найдено медиафайлов: {sum(1 for x in media_pool if x['dt'])} из {len(media_pool)}")

    matched_count = 0
    used_paths = set()

    # 4. Сопоставляем каждый кадр по времени
    for i, fr in enumerate(frames):
        slide = fr.get("SlideNum") or str(i + 1)
        target_dt = parse_dt_from_string(fr.get("parsed_datetime")) or parse_dt_from_string(fr.get("ocr_raw"))

        if not target_dt:
            log(f"  [{slide:>2}] [MISS-TIME] В кадре нет распознанной даты")
            continue

        best_match = None
        min_diff = float("inf")

        for item in media_pool:
            if not item["dt"] or item["path"] in used_paths:
                continue
            diff = abs((item["dt"] - target_dt).total_seconds())
            if diff <= a.tolerance and diff < min_diff:
                min_diff = diff
                best_match = item

        if best_match:
            used_paths.add(best_match["path"])
            matched_count += 1
            fpath = best_match["path"]
            fname = best_match["name"]

            info_line = ""
            details_block = []

            if a.verify:
                res = inspect_exif_and_streams(fpath)
                if res["exif_dt"]:
                    e_diff = abs((res["exif_dt"] - target_dt).total_seconds())
                    v_stat = "OK" if e_diff <= a.tolerance else f"DRIFT {e_diff:.0f}s"
                    info_line = f" | {res['exif_source']}: {res['exif_dt'].strftime('%H:%M:%S')} [{v_stat}]"
                else:
                    info_line = " | [NO EXIF/STREAM]"

                if a.detail:
                    details_block.append(f"       Файл     : {fpath} ({best_match['size']:,} B)")
                    details_block.append(f"       Имя-время: {best_match['dt']} (Δ={min_diff:.0f}с)")
                    if res["exif_meta"]:
                        meta_s = ", ".join(f"{k}={v}" for k, v in res["exif_meta"].items())
                        details_block.append(f"       EXIF Meta: {meta_s}")
                    if res["streams"]:
                        str_s = ", ".join(f"{k}='{v}'" for k, v in res["streams"].items())
                        details_block.append(f"       Стримы   : {str_s}")
            elif a.detail:
                details_block.append(f"       Файл     : {fpath} ({best_match['size']:,} B)")
                details_block.append(f"       Имя-время: {best_match['dt']} (Δ={min_diff:.0f}с)")

            # Сжатие и сохранение в локальную папку при флаге -c
            final_path = fpath
            if do_compress and not a.dry_run:
                final_path = compress_and_save_image(
                    fpath, a.dest_dir, max_dim=a.max_dim, quality=a.quality
                )
                info_line += f" -> [Сжат: {os.path.basename(final_path)}]"

            log(f"  [{slide:>2}] {target_dt.strftime('%d.%m %H:%M:%S')} -> {fname} (Δ={min_diff:.0f}с{info_line})")
            for d_line in details_block:
                log(d_line)

            fr["path"] = final_path
            fr["filename"] = final_path
            if "SlideNum" in fr and not fr["SlideNum"]:
                fr["SlideNum"] = str(slide)
        else:
            log(f"  [{slide:>2}] {target_dt.strftime('%d.%m %H:%M:%S')} -> <НЕ НАЙДЕН В ОКНЕ ±{a.tolerance}с>")

    log(f"\n[+] Успешно сопоставлено: {matched_count} из {len(frames)} кадров.")

    # 5. Вывод результата: в файл или в STDOUT
    out_json = json.dumps(data, indent=2, ensure_ascii=False)

    if from_stdin or a.stdout:
        sys.stdout.write(out_json)
        sys.stdout.write("\n")
        sys.stdout.flush()
    else:
        if a.dry_run:
            log("[*] --dry-run: манифест не перезаписывался.")
            return

        if a.backup:
            bak = manifest_path + ".bak"
            shutil.copy2(manifest_path, bak)
            log(f"[+] Бэкап: {bak}")

        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(out_json)
        log(f"[+] Манифест успешно обновлен: {manifest_path}")


if __name__ == "__main__":
    main()