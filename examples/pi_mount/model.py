"""Raspberry Pi 4 tray on the tractor's 1" handrail pipe (demo video design).

Axes: X = along the pipe (+X right), Y = forward (+Y toward the hood), Z = up. Units: mm.
Origin = pipe centre, under the middle of the tray.

Parts to print:
  tray         plate with 4 standoffs for the Pi + upper clamp halves (print floor-down)
  clamp_cap_L / clamp_cap_R   lower clamp halves (print split face down)
Hardware: 4x M2.5x8 screw (Pi), 4x M5x30 bolt + nut (clamps), 1 mm rubber sheet around the pipe.

Pi 4 board 85 x 56, holes 58 x 49, M2.5 — official mechanical drawing. Pipe Ø25.6 — build guide.
"""
from build123d import Align, Box, Cylinder, Pos, Rot

P = dict(
    pi_w=85.0, pi_d=56.0, pi_t=1.5,     # board (datasheet)
    hole_dx=58.0, hole_dy=49.0,         # mounting holes (datasheet)
    hole_from_x=3.5, hole_from_y=3.5,   # first hole from the board corner (datasheet)
    pi_h=20.0,                          # tallest component incl. USB ports; guess, display only
    pipe_d=25.6,                        # build guide
    clamp_id=27.5,                      # with 1 mm rubber sheet
    clamp_gap=2.0,
    plate_t=4.0, standoff_h=6.0, standoff_d=6.5,
    screw_d=2.4,                        # M2.5 self-tapping in PETG
    margin=6.0,                         # plate beyond the board outline
    clamp_w=18.0,
)

C, MIN, MAX = Align.CENTER, Align.MIN, Align.MAX
R = P["clamp_id"] / 2
g = P["clamp_gap"] / 2
bolt_y = R + 6
clamp_len = 2 * (bolt_y + 6)
z_plate_bot = R + 6
z_plate_top = z_plate_bot + P["plate_t"]
plate_w = P["pi_w"] + 2 * P["margin"]
plate_d = max(P["pi_d"] + 2 * P["margin"], clamp_len)

# ---- Tray: plate + standoffs ----------------------------------------------------
tray = Pos(0, 0, z_plate_bot) * Box(plate_w, plate_d, P["plate_t"], align=(C, C, MIN))
hx = [-P["hole_dx"] / 2, P["hole_dx"] / 2]
hy = [-P["hole_dy"] / 2, P["hole_dy"] / 2]
for x in hx:
    for y in hy:
        tray += Pos(x, y, z_plate_top) * Cylinder(P["standoff_d"] / 2, P["standoff_h"], align=(C, C, MIN))
        tray -= Pos(x, y, z_plate_bot + 1) * Cylinder(P["screw_d"] / 2, P["plate_t"] + P["standoff_h"], align=(C, C, MIN))
# cable-tie slots either side (strap over the Pi for vibration)
for sx in (-1, 1):
    tray -= Pos(sx * (P["pi_w"] / 2 + 2), 0, z_plate_bot - 1) * Box(3, 14, P["plate_t"] + 2, align=(C, C, MIN))

# ---- Upper clamp halves (part of the tray) --------------------------------------
clamp_xs = [sx * (plate_w / 2 - P["clamp_w"] / 2) for sx in (-1, 1)]
for x in clamp_xs:
    up = Pos(x, 0, g) * Box(P["clamp_w"], clamp_len, z_plate_bot - g, align=(C, C, MIN))
    up -= Pos(x, 0, 0) * Rot(0, 90, 0) * Cylinder(R, P["clamp_w"] + 2)
    for y in (-bolt_y, bolt_y):
        up -= Pos(x, y, g) * Cylinder(2.75, z_plate_bot + P["plate_t"] + 1, align=(C, C, MIN))
    tray += up

# ---- Lower clamp half (separate part, printed twice) ----------------------------
cap = Pos(0, 0, -g) * Box(P["clamp_w"], clamp_len, R + 6 - g, align=(C, C, MAX))
cap -= Rot(0, 90, 0) * Cylinder(R, P["clamp_w"] + 2)
for y in (-bolt_y, bolt_y):
    cap -= Pos(0, y, 0) * Cylinder(2.75, 60)
    cap -= Pos(0, y, -(R + 6)) * Cylinder(4.6, 5, align=(C, C, MIN))    # nut pocket

# ---- Context (not printed) ------------------------------------------------------
pipe = Rot(0, 90, 0) * Cylinder(P["pipe_d"] / 2, plate_w + 200)
board_z = z_plate_top + P["standoff_h"]
pi = Pos(0, 0, board_z) * Box(P["pi_w"], P["pi_d"], P["pi_t"], align=(C, C, MIN))
pi += Pos(0, 0, board_z + P["pi_t"]) * Box(P["pi_w"] - 10, P["pi_d"] - 10, P["pi_h"], align=(C, C, MIN))

parts = {"tray": tray, "clamp_cap_L": Pos(clamp_xs[0], 0, 0) * cap, "clamp_cap_R": Pos(clamp_xs[1], 0, 0) * cap}
context = {"pipe": pipe, "raspberry_pi": pi}
labels = {"tray": "トレイ", "clamp_cap_L": "クランプ下 左", "clamp_cap_R": "クランプ下 右"}
origin = "ハンドレールの中心、トレイの真下"
print_orientation = {"tray": (0, 0, 0), "clamp_cap_L": (180, 0, 0), "clamp_cap_R": (180, 0, 0)}
hardware = ["M2.5×8 ネジ 4本（Pi）", "M5×30 ボルト・ナット 4組（クランプ）", "ゴムシート 1 mm（パイプに巻く）", "結束バンド 2本（Pi の押さえ）"]
checks = ["パイプの周長 8.0 cm（Ø25.6）", "Pi の穴間隔 58×49 mm（公式図面）"]
dims = [
    {"label": "Pi 穴間隔 X", "part": "tray", "kind": "distance", "a": (hx[0], hy[0], z_plate_top + 3), "b": (hx[1], hy[0], z_plate_top + 3),
     "snap": "hole", "axis": "X", "expect": 58, "tol": 0.3, "key": True},
    {"label": "Pi 穴間隔 Y", "part": "tray", "kind": "distance", "a": (hx[0], hy[0], z_plate_top + 3), "b": (hx[0], hy[1], z_plate_top + 3),
     "snap": "hole", "axis": "Y", "expect": 49, "tol": 0.3, "key": True},
    {"label": "クランプ内径", "part": "clamp_cap_L", "kind": "diameter", "at": (clamp_xs[0], 0, -2), "expect": 27.5, "tol": 0.3,
     "vs": 25.6, "vs_label": "パイプ", "key": True},
    {"label": "ゴムシートの厚み分", "part": "tray", "kind": "clearance", "to": "pipe", "expect": 0.95, "tol": 0.2},
    {"label": "ゴムシートの厚み分", "part": "clamp_cap_*", "kind": "clearance", "to": "pipe", "expect": 0.95, "tol": 0.2},
]
