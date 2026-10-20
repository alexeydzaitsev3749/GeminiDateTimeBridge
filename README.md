# Forensic Phototable Toolchain & Multimodal Pipeline

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Standards: GOST R 50597-2017](https://img.shields.io/badge/Standards-GOST%20R%2050597--2017-green.svg)](#)

A Unix-philosophy engineering toolchain for **forensic civil infrastructure auditing**, **lossless photo stamping**, and **automated multimodal LLM report compilation**.

This suite bridges raw high-resolution smartphone sensor captures, AI-assisted multimodal inspection (Gemini AI Studio / Gemini API), and deterministic, court-admissible PDF phototable generation.

---

## ⚡ The One-Line Forensic Pipeline

Once Gemini finishes analyzing an inspection batch in the browser, copy the generated JSON manifest to the clipboard and run:

```bash
python clip.py | python gemini_map_dt.py --dir "K:\My Drive\Google AI Studio\.LLM\1" -c | python BuildPhototableT.py -o final_audit_report.pdf
```

1. **`clip.py`** pipes the clipboard JSON to `stdout` in milliseconds.
2. **`gemini_map_dt.py`** indexes frames by recognized datetime stamps, verifies hardware EXIF, downsamples 60 MB of 48MP photos into lightweight ~300 KB JPEGs in `./img`, and streams the updated manifest downstream.
3. **`BuildPhototableT.py`** ingests the stream, sorts frames strictly by `SlideNum` (`1, 2, 3...`), and compiles an executive 9-page legal phototable (~2.3 MB) ready for court or municipal enforcement.

---

## 🏗️ Architectural Overview

```
                      FIELD CAPTURE (Smartphone / Camera)
                                      │
                                      ▼
                             [PhotoStamper.py]
         (Lossless 16x16 MCU block replacement via 1992 DCT rules)
         (98.5% bit-exact sensor preservation; zero ELA artifacting)
                                      │
                                      ▼
                      MULTIMODAL AUDIT (Gemini LLM)
              (Visual defect detection, OCR timestamp extraction)
                                      │
                                      ▼
                                  [clip.py]
               (Clean stdout data streaming / stderr logging)
                                      │
                                      ▼
                            [gemini_map_dt.py]
         (Datetime-as-Primary-Key mapping, EXIF/Stream verification,
          and localized compression to ./img/*.jpg)
                                      │
                                      ▼
                           [BuildPhototableT.py]
           (Strict SlideNum sorting, ReportLab native /DCTDecode,
            formal legal headers & defect classification)
                                      │
                                      ▼
                      AUDIT-READY PROCEDURAL PDF (2 MB)
```

---

## 📦 Tool Breakdown

### 1. `PhotoStamper.py` — Lossless MCU Stamping Engine
* **Core Principle:** JPEG is fundamentally a Minimum Coded Unit (MCU) block-based architecture. Decompressing and re-saving a 48MP photo through Pillow/OpenCV triggers Full Forward DCT (FDCT) and global lossy re-quantization, destroying micro-textures of concrete cracks, asphalt erosion, and wire fraying.
* **1992 Assembly Paradigm:** Uses `jpegtran -drop` (`libjpeg-turbo`) to splice localized 112×96 px telemetry badges directly into the entropy-coded bitstream.
* **Forensic Integrity:** Coordinates and patch dimensions are strictly aligned to 16×16 MCU boundaries (4:2:0 subsampling). **98.5% of the photograph remains 100% bit-exact to raw camera sensor output**, passing forensic Error Level Analysis (ELA).
* **Anti-Spoofing Architecture:** Overrides corrupted GPS telemetry caused by EW/GNSS spoofing via explicit coordinate pinning (`-c "56.0510N 37.4936E"`) and localized reverse-geocoding caching.

---

### 2. `clip.py` — Unix-Compliant Clipboard Streamer
* **Purpose:** Bridges browser-based AI environments (Google AI Studio) and local command-line automation.
* **Clean Stream Separation:** Emits clipboard payload strictly to `stdout` while routing operational logs to `stderr` (`stdlog`). Prevents pipeline corruption when chaining via pipes.
* **Execution Modes:**
  * **Default (One-Shot):** Immediately prints the current clipboard to `stdout` and exits (`EOF`), unlocking downstream pipe ingestion.
  * **Daemon Mode (`-w` / `--watch`):** Continuously monitors the clipboard, streaming changes to `stdout`.
  * **Archival Mode (`-f` / `-o DIR`):** Persists all clipboard mutations to discrete `{timestamp}.txt` files on disk.

```bash
# One-shot pipe to file or processor
python clip.py | python gemini_map_dt.py ...

# Run as background clipboard auditor
python clip.py -w -f ./clipboard_history
```

---

### 3. `gemini_map_dt.py` — Datetime-Indexed Forensic Mapper
* **Timestamp as Primary Key:** Instead of relying on brittle sequence counters or cloud-sync naming quirks (` (1).jpg`), this utility indexes files by physical capture time extracted by Gemini from on-screen timestamp badges (`parsed_datetime` or `ocr_raw`).
* **Fault Isolation:** Automatically isolates dropped/failed uploads without shifting downstream array indices (immune to cascade off-by-one errors).
* **Verification Engine (`-v`, `-d`):**
  * Parses hardware EXIF metadata (`DateTimeOriginal`, `Make`, `Model`, `Software`).
  * Inspects binary stream tags (Windows NTFS Alternate Data Streams, XMP packets, JPEG `COM` markers).
  * Tolerates shutter/rendering delay windows (`--tolerance 2`).
* **Localized Transcoding (`-c` / `--compress`):**
  * Copies matched files from cloud/virtual drives (`K:`) to `./img` with normalized `.jpg` extensions.
  * Automatically calculates native DQT quantization matrices or accepts target constraints (`-q`, `--max-dim 1920`).
  * Shrinks 55 MB batches of raw camera JPEGs down to ~2.4 MB of print-ready A4 assets.

```bash
# Check timestamps & verify EXIF with full debug dump
python gemini_map_dt.py manifest.json --dir "K:\Photos" -v -d

# Compress matched assets to ./img at 80% quality
python gemini_map_dt.py manifest.json --dir "K:\Photos" -c -q 80
```

---

### 4. `BuildPhototableT.py` — Procedural Legal Phototable Compiler
* **Compliance:** Formats technical evidence under **GOST R 50597-2017** (*Automobile roads and streets. Requirements for operational status permissible under road safety terms*), suitable for submission to court, road authorities, or civic portals (e.g., Dobrodel).
* **Strict Ordinal Sorting:** Enforces monotonic `SlideNum` ordering (`1, 2, 3...`), regardless of the order items were emitted by the LLM.
* **Native `/DCTDecode` Pass-Through:** Embeds JPEGs directly into PDF streams without decompression, eliminating PDF bloat.
* **Markdown Front-Matter Integration (`-md`):** Automatically compiles upstream legal briefs, tables, and notices into page 1 before attaching the photo evidence cards.
* **Zero-Dependency Core:** Decoupled from external glyph tables and complex registry indices. Operates directly on manifest JSON.

```bash
# Compile report from file
python BuildPhototableT.py manifest.json -o road_inspection.pdf

# Prepend a legal complaint letter
python BuildPhototableT.py manifest.json -md complaint.md -o formal_submission.pdf
```

---

## 🛠️ Installation & Dependencies

```bash
git clone https://github.com/your-username/gemini-forensic-phototable.git
cd gemini-forensic-phototable
pip install reportlab pillow pyperclip
```

### Optional External Tools
* **`libjpeg-turbo` (`jpegtran`):** Required only if running raw MCU bitstream insertions via `PhotoStamper.py`.
* **TrueType Fonts:** Ships with auto-fallback to system `arial.ttf` (Windows) or `DejaVuSans.ttf` (Linux).

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
