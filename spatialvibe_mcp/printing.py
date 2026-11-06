"""Build-volume checks and the print bundle (print STL + STEP + script + Japanese guide).

Runs in the server process but only reads JSON and mesh files written by the runner — it never
executes the model script.
"""
import itertools
import json
import math
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from . import _files as files
from ._isolation import MAX_MESH_BYTES

PRESETS = {"a1mini": ("Bambu Lab A1 mini", [180.0, 180.0, 180.0])}
EPS = 1e-6  # mm; float noise only — sizes are compared unrounded
NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*(?:mm)?")
MAX_QTY = 1000


def parse_printer(spec: str) -> dict:
    """'a1mini' / 'Bambu Lab A1 mini' or a build volume 'WxDxH' in mm."""
    s = str(spec).strip()
    key = re.sub(r"[\s_-]", "", s.lower()).removeprefix("bambulab").removeprefix("bambu")
    if key in PRESETS:
        name, vol = PRESETS[key]
        return {"name": name, "build_volume_mm": list(vol), "preset": key}
    m = SIZE.fullmatch(s.lower())
    if m:
        vol = [float(g) for g in m.groups()]
        if all(10 <= v <= 2000 for v in vol):
            return {"name": "custom", "build_volume_mm": vol, "preset": None}
        raise ValueError(f"build volume {s!r} out of range (each side 10–2000 mm)")
    raise ValueError(f"unknown printer {s!r}: use 'a1mini' or the build volume in mm like '256x256x256' "
                     "(ask the user — do not guess)")


def resolve_printer(arg: str = "", recorded: dict | None = None):
    """Explicit argument > printer recorded with the build > $SPATIALVIBE_PRINTER > not set."""
    if arg and arg.strip():
        return dict(parse_printer(arg), source="argument")
    if isinstance(recorded, dict):
        vol = recorded.get("build_volume_mm")
        if isinstance(vol, list) and len(vol) == 3 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and 10 <= v <= 2000 for v in vol):
            return {"name": str(recorded.get("name", "custom"))[:60], "build_volume_mm": [float(v) for v in vol],
                    "preset": recorded.get("preset") if recorded.get("preset") in PRESETS else None,
                    "source": "build"}
    env = os.environ.get("SPATIALVIBE_PRINTER", "").strip()
    if env:
        return dict(parse_printer(env), source="SPATIALVIBE_PRINTER")
    return None


def _size(pp) -> list:
    s = pp.get("size_mm_exact") if isinstance(pp, dict) else None
    if not (isinstance(s, list) and len(s) == 3 and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 for v in s)):
        raise ValueError("print size missing or malformed in result.json")
    return [float(v) for v in s]


def fit(pp: dict, printer) -> dict:
    """Per-part check in the planned print pose. 'exceeds' is about this pose's bounding box only."""
    size = _size(pp)
    rot = pp.get("rotate_xyz_deg")
    d = {"orientation": "specified" if rot is not None else "unconfirmed",
         "rotate_xyz_deg": rot, "size_mm": [round(v, 2) for v in size]}
    if rot is None:
        d["orientation_note"] = "no print_orientation: checked as modelled (assembled pose)"
    if printer is None:
        d.update(fit="printer_not_set",
                 message="build volume not checked: ask which printer and pass printer= (do not assume one)")
        return d
    vol = printer["build_volume_mm"]
    over = [s - v for s, v in zip(size, vol)]
    if all(o <= EPS for o in over):
        d.update(fit="fits", margin_mm=[round(v - s, 2) for s, v in zip(size, vol)])
        return d
    d.update(fit="exceeds", over_mm={a: round(o, 3) for a, o in zip("XYZ", over) if o > EPS})
    turned = next((list(p) for p in itertools.permutations(size)
                   if all(s - v <= EPS for s, v in zip(p, vol))), None)
    if turned:
        d["hint"] = (f"this pose is too big, but its bounding box fits if turned by 90° so that its X/Y/Z "
                     f"sizes are {[round(v, 2) for v in turned]} — change print_orientation")
    else:
        d["hint"] = ("this bounding box does not fit with 90° turns; it may still fit placed diagonally, "
                     "otherwise split the part or use a larger printer")
    return d


# ---- bundle -----------------------------------------------------------------------------

def _own_file(vfd: int, vname: str, fname: str) -> None:
    """Refuse (with a message for the client) anything that is not a plain, single-linked,
    bounded file of ours in the version folder: no symlink/hardlink/FIFO tricks from a script
    or from a version folder written by an older server. The copy re-checks by descriptor."""
    try:
        files.plain_stat(fname, vfd, MAX_MESH_BYTES)
    except FileNotFoundError:
        raise ValueError(f"{vname}/{fname} is missing; rebuild with build_model") from None
    except files.BoundaryError:
        raise ValueError(f"{vname}/{fname} is not a plain file; refusing to export it") from None


def _copy_into(vfd: int, fname: str, folder: Path, dst_name: str) -> None:
    dfd = files.open_dir(folder)
    try:
        files.copy_file(fname, vfd, dst_name, dfd, MAX_MESH_BYTES, replace=False)
    finally:
        os.close(dfd)


def _text(v, label, limit) -> str:
    v = re.sub(r"[\x00-\x1f\x7f]+", " ", str(v)).strip()
    if len(v) > limit:
        raise ValueError(f"{label} is longer than {limit} characters")
    return v


def _texts(items, label, limit, count=50):
    if items is None:
        return None
    if isinstance(items, str) or not isinstance(items, (list, tuple)):
        raise ValueError(f"{label} must be a list of strings")
    if len(items) > count:
        raise ValueError(f"{label}: at most {count} items")
    return [t for t in (_text(x, label, limit) for x in items) if t]


def _check_part_keys(d, parts, label):
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise ValueError(f"{label} must be a dict {{part_name: value}}")
    bad = [k for k in d if k not in parts]
    if bad:
        raise ValueError(f"{label}: {bad} not in parts {sorted(parts)} (context is never printed)")
    return d


def make_bundle(project: str, vdir: Path, result: dict, printer, quantities=None, material="",
                hardware=None, notes=None, part_notes=None, include_zip: bool = False) -> dict:
    parts = result.get("parts") or {}
    if (not isinstance(parts, dict) or not parts or not all(isinstance(k, str) and NAME.fullmatch(k) for k in parts)
            or len({k.casefold() for k in parts}) != len(parts)):  # macOS folders ignore case
        raise ValueError(f"{project} {vdir.name}: no valid part list in result.json; rebuild with build_model")
    if any("print" not in p for p in parts.values()):
        raise ValueError(f"{project} {vdir.name} was built before print export existed (no print pose data). "
                         f"Rebuild it once: build_model({project!r}, get_code({project!r}, {int(vdir.name[1:])})), "
                         "then export_print the new version")

    quantities = _check_part_keys(quantities, parts, "quantities")
    for k, q in quantities.items():
        if not isinstance(q, int) or isinstance(q, bool) or not 1 <= q <= MAX_QTY:
            raise ValueError(f"quantities[{k!r}] must be an integer 1–{MAX_QTY}, got {q!r}")
    part_notes = {k: _text(v, f"part_notes[{k!r}]", 500)
                  for k, v in _check_part_keys(part_notes, parts, "part_notes").items()}
    material = _text(material or "", "material", 100)
    hardware = _texts(hardware, "hardware", 200)
    notes = _texts(notes, "notes", 500) or []

    rows, broken, oversize = [], [], []
    for name, info in parts.items():
        f = fit(info["print"], printer)
        if not info.get("valid") or not info.get("solids"):
            broken.append(name)
        if f["fit"] == "exceeds":
            oversize.append({"part": name, "size_mm": f["size_mm"], "over_mm": f["over_mm"], "hint": f["hint"]})
        rows.append((name, info, f))
    if broken:
        return {"ok": False, "error": f"not exported: parts {broken} are not valid solids; fix the model and rebuild"}
    if oversize:
        vol = printer["build_volume_mm"]
        return {"ok": False, "oversize": oversize,
                "error": f"not exported: {[o['part'] for o in oversize]} exceed the build volume "
                         f"{vol} mm of {printer['name']} in their print pose"}

    vfd = files.open_dir(vdir)          # the version folder itself; its files are checked below
    try:
        for fname in [*(f"part_{n}.step" for n in parts), *(f"print_{n}.stl" for n in parts), "model.py"]:
            _own_file(vfd, vdir.name, fname)
        return _write_bundle(project, vdir, vfd, result, printer, parts, rows, quantities, material, hardware,
                             notes, part_notes, include_zip)
    finally:
        os.close(vfd)


def _write_bundle(project, vdir, vfd, result, printer, parts, rows, quantities, material, hardware, notes,
                  part_notes, include_zip) -> dict:
    bname = f"{project}_{vdir.name}_print"
    manifest_parts, warnings = [], []
    for name, info, f in rows:
        manifest_parts.append({
            "name": name, "stl": f"stl/{name}.stl", "step": f"step/{name}.step",
            "quantity": quantities.get(name, 1), "quantity_confirmed": name in quantities,
            "print_size_mm": f["size_mm"], "assembled_size_mm": info["bbox_mm"]["size"],
            "volume_cm3": info.get("volume_cm3"), "solids": info.get("solids"),
            "orientation": f["orientation"], "rotate_xyz_deg": f["rotate_xyz_deg"],
            "fit": f["fit"], "margin_mm": f.get("margin_mm"), "note": part_notes.get(name, ""),
        })
        if info.get("solids", 1) > 1:
            warnings.append(f"{name} は {info['solids']} 個の別々の塊でできています（意図どおりか確認）")
    for it in result.get("interference") or []:
        warnings.append(f"{it.get('a')} と {it.get('b')} が重なっています（{it.get('overlap_cm3')} cm³）")

    unconfirmed = []
    if printer is None:
        unconfirmed.append("printer")
    unconfirmed += [f"orientation:{p['name']}" for p in manifest_parts if p["orientation"] != "specified"]
    unconfirmed += [f"quantity:{p['name']}" for p in manifest_parts if not p["quantity_confirmed"]]
    if not material:
        unconfirmed.append("material")
    if hardware is None:
        unconfirmed.append("hardware")
    checked = printer is not None and all(p["orientation"] == "specified" for p in manifest_parts)

    manifest = {
        "format": "spatialvibe-print-bundle/1", "project": project, "version": int(vdir.name[1:]),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "units": "mm",
        "printer": ({k: printer[k] for k in ("name", "build_volume_mm", "preset", "source") if k in printer}
                    if printer else None),
        "size_check": "all parts fit in their print pose" if checked else "unconfirmed",
        "material": material or None, "hardware": hardware, "notes": notes, "parts": manifest_parts,
        "warnings": warnings, "unconfirmed": unconfirmed, "context_included": False,
        "source": "source/model.py", "guide": "PRINT_GUIDE_ja.txt", "handoff": "AI_HANDOFF.txt",
        # this tool stops here; nothing below has been computed — never fill it in from guesses
        "not_done": ["slicing", "supports", "print time estimate", "filament estimate", "printing"],
    }

    folder, zdest = vdir / bname, vdir / f"{bname}.zip"
    tmp = Path(tempfile.mkdtemp(prefix=".export-", dir=vdir))
    try:
        root = tmp / bname
        for sub in ("stl", "step", "source"):
            (root / sub).mkdir(parents=True)
        for p in manifest_parts:
            _copy_into(vfd, f"print_{p['name']}.stl", root / "stl", f"{p['name']}.stl")
            _copy_into(vfd, f"part_{p['name']}.step", root / "step", f"{p['name']}.step")
        _copy_into(vfd, "model.py", root / "source", "model.py")
        (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        (root / "PRINT_GUIDE_ja.txt").write_text(guide(manifest), encoding="utf-8")
        handoff_text = handoff(manifest, folder)
        (root / "AI_HANDOFF.txt").write_text(handoff_text, encoding="utf-8")
        if include_zip:
            zpath = tmp / f"{bname}.zip"
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
                for f in sorted(root.rglob("*")):
                    if f.is_file():
                        z.write(f, f"{bname}/{f.relative_to(root).as_posix()}")
        if folder.is_symlink() or folder.is_file():
            folder.unlink()
        elif folder.exists() and not files.wipe(folder):   # an earlier export, or whatever was planted there
            raise ValueError(f"could not replace the old export folder {folder}")
        os.replace(root, folder)
        # a ZIP from an earlier export would no longer match the folder: replace it or remove it
        if include_zip:
            os.replace(zpath, zdest)  # replaces a planted symlink itself, never its target
        elif zdest.is_symlink() or zdest.is_file():
            zdest.unlink()
    finally:
        files.wipe(tmp)

    return {"ok": True, "folder": str(folder), "zip": str(zdest) if include_zip else None,
            "manifest_path": str(folder / "manifest.json"), "guide_path": str(folder / "PRINT_GUIDE_ja.txt"),
            "handoff_path": str(folder / "AI_HANDOFF.txt"), "handoff": handoff_text,
            "files": {"parts": {p["name"]: {"stl": str(folder / p["stl"]), "step": str(folder / p["step"])}
                                for p in manifest_parts},
                      "source": str(folder / "source" / "model.py")},
            "manifest": manifest, "size_check": manifest["size_check"],
            "unconfirmed": unconfirmed, "warnings": warnings,
            "parts": [{k: p[k] for k in ("name", "stl", "quantity", "quantity_confirmed", "print_size_mm",
                                         "orientation", "fit")} for p in manifest_parts],
            "next_steps": NEXT_STEPS}


NEXT_STEPS = [
    "Show the user the conditions (printer, material, each part's quantity / pose / size, hardware, "
    "notes). Reuse information already given; resolve `unconfirmed` and any missing slicer/printer "
    "profile details, asking the user only for information you still need. Re-export updated conditions.",
    "This MCP does not slice or print. If you have a slicer or printer integration, continue preparing "
    "with the STL files and these conditions; otherwise tell the user it stops here.",
    "When you do slice, show the user what was actually chosen and computed (printer/material profile, "
    "orientation and copies, supports, time and filament estimates). Do not state estimates you did not get.",
    "To hand over to another AI, give it `handoff` (also in AI_HANDOFF.txt).",
]


def _mm(v):
    return " × ".join(f"{x:.2f}" for x in v)


FIT_JA = {"fits": "入る", "printer_not_set": "未確認（プリンター未設定）"}


def guide(m: dict) -> str:
    pr = m["printer"]
    L = [f"印刷案内 — {m['project']} v{m['version']:03d}", f"作成: {m['created_at']}",
         "単位: mm（STL は mm）", ""]
    if m["size_check"] == "unconfirmed":
        L += ["※ まだ確認できていない項目があります（下の「未確認」）。印刷できるかは確定していません。", ""]
    L += ["■ プリンター",
          f"  {'指定サイズ' if pr['name'] == 'custom' else pr['name']}（造形範囲 {_mm(pr['build_volume_mm'])} mm）" if pr
          else "  未設定 — 造形範囲に入るかは確認していません", ""]
    L += ["■ 材料", f"  {m['material']}" if m["material"] else "  未指定（決めてから印刷してください）", ""]
    L += ["■ 印刷する部品"]
    for i, p in enumerate(m["parts"], 1):
        qty = f"{p['quantity']} 個" + ("" if p["quantity_confirmed"] else "（個数は未確認）")
        pose = (f"指定あり（組付け姿勢から X{p['rotate_xyz_deg'][0]:g}° Y{p['rotate_xyz_deg'][1]:g}° "
                f"Z{p['rotate_xyz_deg'][2]:g}° 回して床に置いた向き）" if p["orientation"] == "specified"
                else "未確認（組付けたときの向きのまま床に置いただけ。印刷前に向きを決める必要があります）")
        fit_ja = FIT_JA[p["fit"]]
        if p["fit"] == "fits":
            fit_ja += f"（余裕 {_mm(p['margin_mm'])} mm）"
            if p["orientation"] != "specified":
                fit_ja = "この向きのままなら" + fit_ja + "。向きを変えたら確認し直してください"
        L += [f"  {i}. {p['name']} — {qty}", f"     ファイル: {p['stl']}",
              f"     印刷時の外形: {_mm(p['print_size_mm'])} mm（X × Y × Z）",
              f"     印刷姿勢: {pose}", f"     造形範囲: {fit_ja}"]
        if p["note"]:
            L.append(f"     メモ: {p['note']}")
    L += ["", "■ 金具・その他の部品"]
    if m["hardware"] is None:
        L.append("  未記入（必要なボルト・ナット等を確認してください）")
    else:
        L += [f"  - {h}" for h in m["hardware"]] or ["  なし"]
    if m["notes"] or m["warnings"]:
        L += ["", "■ 注意点"] + [f"  - {n}" for n in m["notes"] + m["warnings"]]
    if m["unconfirmed"]:
        L += ["", "■ 未確認", *[f"  - {x}" for x in unconfirmed_ja(m)]]
    L += ["", "■ ファイル",
          "  stl/              印刷用（印刷姿勢に回し、床 z=0 に置いたもの）",
          "  step/             編集用（組付けたときの向きのまま）",
          "  source/model.py   この版の build123d スクリプト",
          "  manifest.json     この案内と同じ条件の、AI・機械向けの一覧",
          "  AI_HANDOFF.txt    別の AI に続きを頼むときに渡す短い文",
          "  周囲の物（パイプ・箱など）は印刷しないので入れていません。", "",
          "■ このあと",
          "  ここまでで印刷用ファイルと条件を用意しました。造形範囲・印刷姿勢の確認状況は上記をご覧ください。",
          "  スライス（サポート・充填など）、印刷時間や材料量の見積り、印刷はまだしていません。",
          "  AI がスライサーやプリンターと連携できる場合は、この条件で準備を続け、",
          "  選んだ設定や見積りが出た時点でお知らせします。連携がなければここまでです。", "",
          "■ 限界",
          "  外形サイズと向きの確認だけで、強度や取り付けの保証ではありません。", ""]
    return "\n".join(L)


def unconfirmed_ja(m: dict) -> list:
    ja = {"printer": "プリンター（造形範囲）", "material": "材料", "hardware": "金具"}
    return [ja.get(u) or (f"{u.split(':', 1)[1]} の印刷姿勢" if u.startswith("orientation:")
                          else f"{u.split(':', 1)[1]} の個数") for u in m["unconfirmed"]]


def handoff(m: dict, folder: Path) -> str:
    """Short text another AI can act on; the conditions themselves live only in manifest.json."""
    pr = m["printer"]
    parts = ", ".join(f"{p['name']} ×{p['quantity']}{'' if p['quantity_confirmed'] else '(個数未確認)'}"
                      f" {_mm(p['print_size_mm'])} mm 姿勢{'指定済' if p['orientation'] == 'specified' else '未確認'}"
                      for p in m["parts"])
    L = [f"3D プリント準備の引き継ぎ: {m['project']} v{m['version']:03d}",
         f"元の保存場所: {folder}",
         "条件は同梱の manifest.json が正です（単位 mm）。移動した場合は、この文と同じフォルダを基準に参照してください。人向けの説明は PRINT_GUIDE_ja.txt。",
         f"プリンター: {(pr['name'] + ' ' + _mm(pr['build_volume_mm']) + ' mm') if pr else '未設定'}",
         f"材料: {m['material'] or '未指定'}",
         f"部品: {parts}（stl/<部品名>.stl は印刷姿勢で z=0 に接地済み）",
         f"未確認: {'、'.join(unconfirmed_ja(m)) if m['unconfirmed'] else 'なし'}",
         "済んでいること: STL/STEP と条件データの作成。造形範囲・印刷姿勢の確認状況は manifest.json と未確認項目を参照してください。",
         "まだのこと: スライス、サポート、印刷時間・材料量の見積り、印刷。",
         "お願い: 既に得ている情報を再利用し、未確認項目と不足する機種・スライサー設定のうち、なお必要な情報だけ人に確認してください。造形サイズだけでは機種やプロファイルは特定できません。スライサーや印刷の連携が使えるなら、この条件で準備を続け、"
         "選んだ機種・材料プロファイル、向きと個数、サポート、見積り時間と材料量を、実際に得られた値だけ人に示してください。"
         "得ていない見積りは書かないでください。"]
    return "\n".join(L) + "\n"
