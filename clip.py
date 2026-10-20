#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
clip.py — консольная утилита для работы с буфером обмена.

Режимы:
  1. Без параметров (по умолчанию, one-shot):
     Выводит текущее содержимое буфера в stdout и выходит.
     Идеально для пайпов: python clip.py | python BuildPhototableT.py

  2. Режим фонового демона (-w / --watch):
     Мониторит изменения буфера и отдает каждый новый текст в stdout.

  3. Режим архиватора (-f / --save / -o ПАПКА):
     Сохраняет каждое изменение буфера в отдельный файл {timestamp}.txt.
"""

import argparse
import os
import sys
import time
import pyperclip

# Принудительный UTF-8 для Windows консоли и пайпов
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def log(*args, **kwargs):
    """Вывод сервисных сообщений строго в stderr (stdlog)."""
    print(*args, file=sys.stderr, flush=True, **kwargs)


def emit_stdout(text):
    """Безопасная отдача текста в stdout с автопереносом строки."""
    if text:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()


def run_daemon(to_file=False, target_dir="", single_file=None, interval=1.0):
    """Логика фонового демона мониторинга буфера обмена."""
    if to_file:
        dest_desc = f"файлы в '{target_dir or '.'}'" if not single_file else f"файл '{single_file}'"
        log(f"[*] Демон UCTP запущен. Режим: запись в {dest_desc}. Логи: stderr.")
    else:
        log("[*] Демон UCTP запущен. Режим: непрерывный стрим -> stdout. Логи: stderr.")

    last_content = None

    while True:
        time.sleep(interval)
        try:
            current = pyperclip.paste()
            if not current:
                continue

            if not last_content or current != last_content:
                last_content = current
                log(f"\n[*] Буфер обновлен ({len(current)} симв.)")
            else:
                continue

            if to_file:
                out_name = single_file or f"{int(time.time())}.txt"
                if target_dir and not single_file:
                    out_name = os.path.join(target_dir, out_name)

                with open(out_name, "w", encoding="utf-8") as f:
                    f.write(last_content)
                log(f"-> Сохранено в: {out_name}")
            else:
                emit_stdout(last_content)
                log("-> Передано в stdout")

        except KeyboardInterrupt:
            log("\n[*] Демон остановлен.")
            break
        except Exception as e:
            log(f"\n[!] Ошибка: {e}")
            time.sleep(3)


def main():
    ap = argparse.ArgumentParser(
        description="Чтение буфера обмена в stdout или запуск фонового демона."
    )
    ap.add_argument(
        "output_dir",
        nargs="?",
        help="папка для сохранения файлов {timestamp}.txt (включает режим демона-архиватора)"
    )
    ap.add_argument(
        "-w", "--watch", "--daemon",
        dest="watch",
        action="store_true",
        help="запустить фонового демона мониторинга (по умолчанию скрипт отдает буфер один раз и выходит)"
    )
    ap.add_argument(
        "-f", "--file", "--save",
        dest="save_file",
        action="store_true",
        help="сохранять изменения в файлы {timestamp}.txt (режим демона)"
    )
    ap.add_argument(
        "-o", "--out",
        dest="out_target",
        metavar="PATH",
        help="файл или папка для сохранения (включает режим демона)"
    )
    ap.add_argument(
        "-t", "--interval",
        type=float,
        default=1.0,
        help="интервал опроса в режиме демона (по умолчанию 1.0 сек)"
    )

    args = ap.parse_args()

    # Проверяем, запрошен ли режим непрерывного демона
    to_file = bool(args.save_file or args.out_target or args.output_dir)
    is_daemon = args.watch or to_file

    if is_daemon:
        target_dir = args.output_dir or (args.out_target if args.out_target and os.path.isdir(args.out_target) else "")
        single_file = args.out_target if args.out_target and not os.path.isdir(args.out_target) else None
        run_daemon(to_file=to_file, target_dir=target_dir, single_file=single_file, interval=args.interval)
    else:
        # ОСНОВНОЙ РЕЖИМ (по умолчанию): отдать текущий буфер в stdout и сразу выйти
        try:
            content = pyperclip.paste()
            if content:
                emit_stdout(content)
            else:
                log("[!] Буфер обмена пуст.")
        except Exception as e:
            log(f"[!] Ошибка чтения буфера обмена: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()