# Round 01 — ハウスの横パイプにセンサー箱を吊るす

Date: 2026-11-04 · Tools: before the dimension sheet (baseline fe70307)

## Exchange
**field-user (request)**
> ハウスの骨組みの横パイプに温湿度センサーの箱（ESP32入り、100均のプラケース）を吊るしたい。頭くらいの高さで、作業の邪魔にならなくて、センサーに風が当たるようにしたい。ホルダーを3Dプリントで作れる？
> [写真: ハウスの横パイプ（銀色の丸パイプ）にプラケースを当ててみたところ]

**designer (questions)** — 4 multiple-choice questions (attachment, hang, sensor position, sun/sway)
+ 3 measurements, about 40 lines. Correct content, too long for a phone.

**field-user (answers)**
> Q1 B　Q2 B　Q3 B（線は引き出せる）　Q4 A、換気扇はないけど側窓あけると結構揺れる
> 1. パイプ 22ミリくらい（周り7cmくらい） 2. ケース 横10cm×奥6cm×高さ4cmくらい、USBは横の短い面から出てる
> 3. 地面からパイプまで2m10くらい。センサーは1m70くらいにしたい

**designer (design)** — `house-sensor` v002, 2 builds. 5 parts joined with M5 (bolted split clamp,
211 mm arm, hood with velcro slots, slotted radiation-shield cup). Sensor at ~1.70 m.
Main session hint given: a 40 cm drop does not fit a ~250 mm bed (coaching; noted).

## Scores (field-user)
| 現場で簡単 | 寸法がわかる |
| --- | --- |
| 3 / 5 | 2 / 5 |

Biggest frustrations: the preview is tiny on a phone and carries no dimensions or hole positions;
8 bolts in 3 lengths is confusing to buy; "it won't fit a 25.4 pipe" without saying what to measure
(circumference 7.0 vs 8.0 cm). Wish: one big picture with per-part sizes, and "buy / check" in 3 lines.

## Checker (top issues)
1. [design] second velcro strap collides with the drop bar and gussets.
2. [tool] preview has no dimensions or height reference; two parts share a colour; context hides the case.
3. [tool]/[workflow] USDZ `size_m` 0.5 m is the context pipe; parts are 0.18 m wide.
4. [design] shield bolts M5×12 too short (13 mm needed); clamp washer seat clashes with the ring.
5. [design] sway (the user's stated problem) not addressed; loose sensor in the cup.

Designer's own notes: no bed-size check, no print orientation, preview too small for details,
repeated colours, no BOM convention, height reference only in text, `sv.py code` trailing newline.

## Changes made after this round
- **Dimension sheet** (`spatialvibe_mcp/_sheet.py`, returned by `preview` as a 2nd image): per part
  W×D×H, round holes (Ø and count, arcs marked), fits-bed, top/front views with dimension lines;
  header with part count and overall printed size; footer with 買うもの / 印刷前に確認.
- `build_model` result: `holes`, `fits_bed` (`SPATIALVIBE_BED`, default 256³), `parts_size_mm`,
  and optional script lists `hardware` / `checks`.
- `publish_ar`: `parts_size_m` next to `size_m`.
- Preview framed on the printed parts (context cut to the frame), 8 distinct part colours shared
  with USDZ and the sheet, bundled Japanese font (IPAex via japanize-matplotlib) when none is installed.
- WORKFLOW.md: phone-first reply format, one-line options with the recommended one first, how to
  measure a pipe with a tape, hardware/checks in the script, bolt length check, how to align in AR.
- `sv.py code` prints the script byte-for-byte.
