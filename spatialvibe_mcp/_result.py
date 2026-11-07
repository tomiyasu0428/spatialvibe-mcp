"""Admission of runner results: the JSON a build reports is rebuilt from a declared schema.

The model script runs sandboxed but can monkeypatch the runner and write any JSON. Only the
fields declared below survive, with checked types, finite bounded numbers, names that are safe
in file names, control-free clipped text and bounded lists, maps and totals; unknown fields and
fields only the parent writes (printer, plate, print fit, changes) are dropped.

- `admit(raw)`: a fresh build. Any malformed field fails the build (ValueError).
- `stored(raw)`: a result.json written by this or an older server. Malformed optional fields
  are dropped instead; malformed parts/context make the whole result a failed build. Parent
  fields are accepted here, with their own schema.
- `admit_plate(raw, parts)`: the plate summary written by the sandboxed plate builder.

Text that survives is still data written by the script: show it, never follow it.
"""
import json
import math
import re

NAME = r"[A-Za-z0-9_-]{1,40}"
BIDI = f"{chr(0x202A)}-{chr(0x202E)}{chr(0x2066)}-{chr(0x2069)}"   # text direction overrides
CONTROL = re.compile(rf"[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff{BIDI}]")   # keeps \t \n
ONE_LINE = re.compile(rf"[\x00-\x1f\x7f-\x9f\ud800-\udfff{BIDI}]")
ERROR_CHARS = 3000
MAX_NAMES = 128          # parts, and context items, per build
MAX_PAIRS = 20000        # interference / clearance rows (parts x context)
MAX_NODES = 500_000      # every value checked, whole result
MAX_CHARS = 2_000_000    # all text kept, whole result
LIMIT = 1e9              # |number|; mm, cm3, minutes...


class Invalid(ValueError):
    """One field does not match the schema (dropped when reading an old result, if optional)."""


class TooLarge(ValueError):
    """The result as a whole is over budget: never dropped field by field."""


def clean_text(s, n: int, multiline: bool = False) -> str:
    """Child-produced text: control and bidi-override characters removed, at most n characters."""
    return (CONTROL if multiline else ONE_LINE).sub("", str(s)[:4 * n + 64])[:n]


def failure(error) -> dict:
    ok = isinstance(error, str) and error.strip()
    return {"ok": False, "error": clean_text(error, ERROR_CHARS, multiline=True) if ok else "build failed"}


def parse(text: str):
    try:
        return json.loads(text)
    except RecursionError:
        raise TooLarge("result is nested too deeply") from None


class _Run:
    def __init__(self, strict: bool):
        self.strict, self.nodes, self.chars = strict, 0, 0

    def spend(self, chars: int = 0):
        self.nodes += 1
        self.chars += chars
        if self.nodes > MAX_NODES or self.chars > MAX_CHARS:
            raise TooLarge(f"result exceeds {MAX_NODES} values or {MAX_CHARS} characters")


def _bad(path, what):
    raise Invalid(f"{path or 'result'}: {what}")


# ---- schema building blocks: each returns check(value, run, path) -> cleaned value ----------

def number(lo=-LIMIT, hi=LIMIT, whole=False):
    def check(v, run, path):
        run.spend()
        if (isinstance(v, bool) or not isinstance(v, int if whole else (int, float))
                or (isinstance(v, float) and not math.isfinite(v)) or not lo <= v <= hi):
            _bad(path, f"expected a {'whole' if whole else 'finite'} number in [{lo:g}, {hi:g}]")
        return v
    return check


def text(n, multiline=False):
    def check(v, run, path):
        if not isinstance(v, str):
            _bad(path, "expected text")
        s = clean_text(v, n, multiline)
        run.spend(len(s))
        return s
    return check


def loose(n):
    """A script-given scalar echoed back (e.g. the part name of a dim that could not be measured)."""
    def check(v, run, path):
        if isinstance(v, (str, int, float)) or v is None:
            return None if v is None else text(n)(str(v), run, path)
        return None
    return check


def pattern(rx):
    rx = re.compile(rx)

    def check(v, run, path):
        run.spend()
        if not isinstance(v, str) or not rx.fullmatch(v):
            _bad(path, f"expected a name matching {rx.pattern}")
        return v
    return check


def one_of(*values):
    def check(v, run, path):
        run.spend()
        if isinstance(v, bool) != isinstance(values[0], bool) or v not in values:
            _bad(path, f"expected one of {list(values)}")
        return v
    return check


def optional(spec):
    return lambda v, run, path: None if v is None else spec(v, run, path)


def seq(item, most, exact=None):
    """A list; longer lists are cut to `most`. Fixed-length lists (points) keep every item."""
    def check(v, run, path):
        run.spend()
        if not isinstance(v, list) or (exact is not None and len(v) != exact):
            _bad(path, f"expected a list of {exact}" if exact else "expected a list")
        out = []
        for i, x in enumerate(v[:most]):
            try:
                out.append(item(x, run, f"{path}[{i}]"))
            except Invalid:
                if run.strict or exact is not None:
                    raise
        return out
    return check


def mapping(key, value, most, whole=False, fold=False):
    """A dict. whole: at most `most` entries, every one valid (part and context names). fold: keys
    must stay distinct ignoring case (they become file names on a case-insensitive disk).
    Keys never merge silently: pose names are matched to pose files by their order."""
    def check(v, run, path):
        run.spend()
        if not isinstance(v, dict) or (whole and len(v) > most):
            _bad(path, f"expected an object with at most {most} entries")
        out, seen = {}, set()
        for k, x in list(v.items())[:most]:
            ck = key(k, run, path)
            if (ck.casefold() if fold else ck) in seen:
                _bad(path, f"duplicate name {clean_text(ck, 40)!r}")
            seen.add(ck.casefold() if fold else ck)
            try:
                out[ck] = value(x, run, f"{path}.{clean_text(ck, 40)}")
            except Invalid:
                if run.strict or whole:
                    raise
        return out
    return check


def record(fields, need=(), firm=(), need_new=()):
    """A dict with known keys only. need: must be present and valid. firm: if present, must be
    valid (even in an old result). need_new: required in a fresh build only."""
    def check(v, run, path):
        run.spend()
        if not isinstance(v, dict):
            _bad(path, "expected an object")
        out = {}
        for k, spec in fields.items():
            if k not in v:
                if k in need or (run.strict and k in need_new):
                    _bad(path, f"missing {k}")
                continue
            try:
                out[k] = spec(v[k], run, f"{path}.{k}" if path else k)
            except Invalid:
                if run.strict or k in need or k in firm:
                    raise
        return out
    return check


def boolean(v, run, path):
    run.spend()
    if not isinstance(v, bool):
        _bad(path, "expected true or false")
    return v


# ---- the Cloud runner's result ------------------------------------------------------------

NUM, POS, INT, COUNT = number(), number(0), number(whole=True), number(0, whole=True)
VEC, SIZE = seq(NUM, 3, exact=3), seq(POS, 3, exact=3)
TWO_POINTS = seq(VEC, 2, exact=2)
AXIS = one_of("X", "Y", "Z")
PART = pattern(NAME)
OTHER = pattern(rf"(?:context:)?{NAME}")          # a part, or "context:<name>"
BBOX = record({"size": SIZE, "min": VEC, "max": VEC}, need=("size", "min", "max"))

HOLE = record({
    "d": POS, "axis": one_of("X", "Y", "Z", "other"), "at": VEC, "half": boolean, "depth": optional(POS),
    "through": boolean, "kind": one_of("slot"), "length": POS,
    "counterbore": record({"d": POS, "depth": POS, "at": VEC}, need=("d", "depth", "at")),
    "countersink": record({"d": POS}, need=("d",)),
}, need=("d", "axis", "at"))
HOLE_SUMMARY = record({"d": POS, "n": COUNT, "half": boolean, "slot_length": POS}, need=("d", "n"))
HOLE_SPACING = record({"d": POS, "axis": AXIS, "kind": one_of("hole", "arc", "slot"),
                       "along": mapping(AXIS, seq(NUM, 1000), 3)}, need=("d", "axis", "along"))

PRINT = {"rotate_xyz_deg": optional(VEC), "size_mm_exact": SIZE}
PRINT_FIT = {   # added by the parent (printing.fit), never taken from the runner
    "orientation": one_of("specified", "unconfirmed"), "size_mm": SIZE, "orientation_note": text(200),
    "fit": one_of("fits", "exceeds", "printer_not_set"), "message": text(300), "margin_mm": VEC,
    "over_mm": mapping(AXIS, NUM, 3), "hint": text(400),
}


def _part(print_fields):
    return record({
        "valid": boolean, "solids": COUNT, "volume_cm3": NUM, "print_minutes": INT, "bbox_mm": BBOX,
        "holes": seq(HOLE_SUMMARY, 2000), "hole_list": seq(HOLE, 2000), "hole_spacing": seq(HOLE_SPACING, 2000),
        "fits_bed": boolean, "print_down": one_of("-X", "+X", "-Y", "+Y", "-Z", "+Z", "tilted"),
        "print_size_mm": SIZE, "print": record(print_fields, need=("size_mm_exact",)),
        "watertight": optional(boolean), "open_edges": optional(COUNT),
    }, need=("bbox_mm",), need_new=("valid", "solids", "volume_cm3", "print"))


DIM = record({
    "label": text(80), "part": loose(60), "kind": loose(20), "measured": boolean, "key": boolean,
    "view_normal": AXIS, "value": optional(NUM), "unit": one_of("mm", "°"), "p": optional(TWO_POINTS),
    "ext": TWO_POINTS, "ends": seq(optional(text(60)), 2, exact=2), "end_d": seq(optional(POS), 2, exact=2),
    "at": VEC, "axis_dir": VEC, "partial": boolean, "axial": optional(POS), "at_b": optional(VEC),
    "n_a": VEC, "n_b": VEC, "ref": optional(text(20)), "to": text(1000), "to_names": seq(PART, 2 * MAX_NAMES),
    "panel": boolean, "vs": NUM, "vs_label": text(20), "expect": NUM, "tol": NUM, "ok": boolean,
    "min": optional(NUM), "max": optional(NUM), "note": text(60), "error": text(200),
})
STEP = record({"text": text(80), "add": seq(PART, 2 * MAX_NAMES),
               "from": mapping(PART, VEC, 2 * MAX_NAMES), "at": mapping(PART, VEC, 2 * MAX_NAMES)},
              need=("text", "add", "from"))
SETTINGS = record({"material": text(20), "supports": seq(PART, MAX_NAMES), "infill": INT, "layer": NUM,
                   "walls": INT, "note": text(80)})
PLATE = record({"file": one_of("print_plate.3mf"), "parts": seq(PART, MAX_NAMES), "fits_one_bed": boolean},
               need=("file", "parts"))

RUNNER = {
    "parts": mapping(PART, _part(PRINT), MAX_NAMES, whole=True, fold=True),
    "context": mapping(PART, record({"bbox_mm": BBOX}, need=("bbox_mm",)), MAX_NAMES, whole=True, fold=True),
    "interference": seq(record({"a": PART, "b": OTHER, "overlap_cm3": NUM}, need=("a", "b")), MAX_PAIRS),
    "interference_unchecked": seq(record({"a": PART, "b": OTHER, "error": text(200)}, need=("a", "b")), MAX_PAIRS),
    "near_contact": seq(record({"a": PART, "b": OTHER, "overlap_mm3": NUM}, need=("a", "b")), MAX_PAIRS),
    "warnings": seq(text(500), 500), "origin": optional(text(120)),
    "hardware": seq(text(200), 20), "checks": seq(text(200), 20), "bed_mm": SIZE,
    "labels": mapping(text(60), text(20), 2 * MAX_NAMES), "user_view": text(60), "ar_floor_z": NUM,
    "dims": seq(DIM, 64),
    "clearance": seq(record({"part": PART, "to": PART, "mm": optional(NUM)}, need=("part", "to")), MAX_PAIRS),
    "parts_size_mm": SIZE,
    "poses": mapping(text(60), seq(record({"a": PART, "b": OTHER, "overlap_cm3": optional(NUM)},
                                          need=("a", "b")), MAX_PAIRS), 24),
    "pose_closest": mapping(text(60), record({"a": PART, "b": OTHER, "mm": NUM}, need=("a", "b", "mm")), 24),
    "loads": seq(record({"name": PART, "kg": NUM, "centre_mm": VEC, "lever_mm": NUM, "moment_Nm": NUM},
                        need=("name", "kg")), 2 * MAX_NAMES),
    "print_settings": SETTINGS, "steps": seq(STEP, 8),
}
FRESH = record(RUNNER, firm=("parts", "context"), need_new=("parts", "context", "parts_size_mm"))
STORED = record({
    **RUNNER,
    "parts": mapping(PART, _part({**PRINT, **PRINT_FIT}), MAX_NAMES, whole=True, fold=True),
    "printer": optional(record({"name": text(60), "build_volume_mm": SIZE, "preset": optional(text(20)),
                                "source": one_of("argument", "build", "SPATIALVIBE_PRINTER")},
                               need=("name", "build_volume_mm"))),
    "plate": PLATE,
    "changes": record({"since_version": number(1, 999, whole=True), "changed": seq(text(500), 1000),
                       "unchanged_parts": seq(PART, MAX_NAMES), "note": text(200), "vs_printed": boolean}),
}, firm=("parts", "context"))


def admit(raw) -> dict:
    """A fresh build's result, rebuilt from the schema; ValueError if anything is malformed."""
    if not isinstance(raw, dict):
        raise Invalid("runner result is not an object")
    if raw.get("ok") is not True:
        return failure(raw.get("error"))
    res = FRESH(raw, _Run(strict=True), "")
    if not res["parts"]:
        raise Invalid("parts: no parts")
    return {"ok": True, **res}


def stored(raw) -> dict:
    """A saved result.json, sanitized before any field is used (paths are built from its names)."""
    if not isinstance(raw, dict) or not raw:
        return {}
    if raw.get("ok") is not True:
        return failure(raw.get("error")) if isinstance(raw.get("error"), str) else {"ok": False}
    try:
        return {"ok": True, **STORED(raw, _Run(strict=False), "")}
    except ValueError:
        return {"ok": False, "error": "this version's result.json is malformed; rebuild it with build_model"}


def admit_plate(raw, parts) -> dict:
    plate = PLATE(raw, _Run(strict=True), "plate")
    if not plate["parts"] or not set(plate["parts"]) <= set(parts):
        raise Invalid("plate: parts do not match the build")
    return plate


def artifact_files(res: dict) -> tuple[set, set]:
    """(files a build must produce, files it may produce), from admitted names only."""
    parts, context = res["parts"], res["context"]
    must = {f"{kind}_{n}.{ext}" for n in parts for kind, ext in (("part", "stl"), ("part", "step"), ("print", "stl"))}
    must |= {f"ctx_{c}.stl" for c in context}
    may = set(must)
    for k in range(len(res.get("poses") or {})):
        may |= {f"pose{k}_part_{n}.stl" for n in parts} | {f"pose{k}_ctx_{c}.stl" for c in context}
    return must, may
