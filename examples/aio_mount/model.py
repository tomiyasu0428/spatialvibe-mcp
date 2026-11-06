"""AgOpen AIO box (Hammond 1455Q2201) mount for the tractor's 1" handrail pipe — concept v2.

Axes: X = left/right (+X right), Y = forward (+Y toward the hood front), Z = up. Units: mm.
Origin = pipe centre. The pipe runs along X and is horizontal.

Parts to print:
  mount_tray.stl  tray + upper clamp halves + adjustable foot boss (print floor-down)
  clamp_cap.stl   lower clamp half (print 2, split face down)
Hardware: 4x M5 bolt + nut (clamps), 2x M4 screw ~4 mm longer than the panel screws,
1x M8 bolt (~60 mm) + nut + rubber cap (foot), 1 mm rubber sheet around the pipe, 1 velcro strap.

Measurements come from the user's build guide (AgOpenGPS_製作・構築手順書) unless marked "guess".
"""
import json
import sys
from pathlib import Path

from build123d import Align, Box, Cylinder, Pos, Rot, RegularPolygon, extrude, export_stl

P = dict(
    # box: Hammond 1455Q2201 (build guide)
    box_w=125.0,          # width incl. black bezel
    box_h=56.0,           # height incl. bezel
    box_l=220.0,          # length (Y)
    body_w=120.5, body_h=51.5,
    bezel_t=8.0,          # guess, display only
    screw_px=115.5, screw_pz=43.52, screw_d=4.0,
    # pipe (build guide)
    pipe_d=25.6,
    clamp_id=27.5,        # with 1 mm rubber sheet
    clamp_gap=2.0,        # split gap = bolt take-up
    # layout
    box_rear_y=0.0,       # rear (connector) face of the box relative to the pipe centre; guess
    rear_space=50.0,      # pipe centre -> obstacle behind (user)
    # tray
    clearance=1.0, wall=3.0, floor=5.0, lip=15.0,
    clamp_w=20.0,         # clamp thickness along X
    foot_x=-50.0, foot_y=165.0,   # foot position (x from centre, y from box rear face); guess
    foot_boss_h=20.0,
)

C, MIN, MAX = Align.CENTER, Align.MIN, Align.MAX
R = P["clamp_id"] / 2
g = P["clamp_gap"] / 2
ear = 6.0                                  # bolt centre distance outside the bore
bolt_y = R + ear
clamp_len = 2 * (bolt_y + 6)
z_floor_bot = R + 6                        # 6 mm of material above the bore
z_floor_top = z_floor_bot + P["floor"]

iw = P["box_w"] + 2 * P["clearance"]
il = P["box_l"] + P["clearance"]
ow = iw + 2 * P["wall"]
y0 = P["box_rear_y"]                       # box rear face
tab_t = 4.0
floor_y0 = y0 - tab_t
floor_len = il + P["wall"] + tab_t
floor_yc = floor_y0 + floor_len / 2


def m5_nut_pocket(x, y, z, outward):
    """Side-opening slot for an M5 nut (8 mm A/F)."""
    return Pos(x + outward * 5, y, z) * Box(10.5, 8.6, 4.4)


# ---- Tray -------------------------------------------------------------------
tray = Pos(0, floor_yc, z_floor_bot) * Box(ow, floor_len, P["floor"], align=(C, C, MIN))
# side walls
for sx in (-1, 1):
    tray += Pos(sx * (ow / 2 - P["wall"] / 2), y0 + il / 2, z_floor_top) * Box(P["wall"], il, P["lip"], align=(C, C, MIN))
# front stop wall
tray += Pos(0, y0 + il + P["wall"] / 2, z_floor_top) * Box(ow, P["wall"], P["lip"], align=(C, C, MIN))
# rear tabs: lock the box with two of its own rear-panel screws (lower pair)
screw_z = z_floor_top + P["box_h"] / 2 - P["screw_pz"] / 2
for sx in (-1, 1):
    x = sx * P["screw_px"] / 2
    tab = Pos(x, y0 - tab_t / 2, z_floor_top) * Box(14, tab_t, screw_z - z_floor_top + 7, align=(C, C, MIN))
    slot = Pos(x, y0 - tab_t / 2, screw_z) * (Box(P["screw_d"] + 0.5, tab_t + 2, 3) +
                                              Pos(0, 0, 1.5) * Rot(90, 0, 0) * Cylinder((P["screw_d"] + 0.5) / 2, tab_t + 2) +
                                              Pos(0, 0, -1.5) * Rot(90, 0, 0) * Cylinder((P["screw_d"] + 0.5) / 2, tab_t + 2))
    tray += tab - slot
# strap slots (one velcro strap over the front half)
for sx in (-1, 1):
    tray -= Pos(sx * (iw / 2 - 4), y0 + 120, z_floor_bot + P["floor"] / 2) * Box(4, 26, P["floor"] + 1)
# drain holes
for x in (-30, 30):
    for y in (y0 + 70, y0 + 200):
        tray -= Pos(x, y, z_floor_bot + P["floor"] / 2) * Cylinder(3, P["floor"] + 1)

# ---- Upper clamp halves (part of the tray) -------------------------------------
clamp_xs = [sx * (ow / 2 - P["clamp_w"] / 2) for sx in (-1, 1)]
for x in clamp_xs:
    outward = 1 if x > 0 else -1
    up = Pos(x, 0, g) * Box(P["clamp_w"], clamp_len, z_floor_bot - g, align=(C, C, MIN))
    up -= Pos(x, 0, 0) * Rot(0, 90, 0) * Cylinder(R, P["clamp_w"] + 2)
    for y in (-bolt_y, bolt_y):
        up -= Pos(x, y, g) * Cylinder(2.75, z_floor_bot - g - 1, align=(C, C, MIN))
        up -= m5_nut_pocket(x, y, g + 6, outward)
    tray += up

# ---- Adjustable foot boss (M8 bolt rests on the dash cover → sets pitch / stops nodding) --
fx, fy = P["foot_x"], y0 + P["foot_y"]
boss = Pos(fx, fy, z_floor_bot) * Cylinder(10, P["foot_boss_h"], align=(C, C, MAX))
boss -= Pos(fx, fy, z_floor_bot - P["foot_boss_h"]) * extrude(RegularPolygon(13.4 / 2 / 0.866, 6), amount=7)
boss -= Pos(fx, fy, z_floor_bot - P["foot_boss_h"]) * Cylinder(4.3, P["foot_boss_h"] - 2, align=(C, C, MIN))
tray += boss

# ---- Lower clamp half (separate part) ------------------------------------------
cap = Box(P["clamp_w"], clamp_len, R + 6 - g, align=(C, C, MAX))
cap = Pos(0, 0, -g) * cap
cap -= Rot(0, 90, 0) * Cylinder(R, P["clamp_w"] + 2)
for y in (-bolt_y, bolt_y):
    cap -= Pos(0, y, 0) * Cylinder(2.75, 60)
    cap -= Pos(0, y, -(R + 6)) * Cylinder(5.2, 8, align=(C, C, MIN))     # counterbore for the head

# ---- Context geometry (not printed) ---------------------------------------------
pipe = Rot(0, 90, 0) * Cylinder(P["pipe_d"] / 2, ow + 200)
bz = z_floor_top
body_l = P["box_l"] - 2 * P["bezel_t"]
box = Pos(0, y0 + P["box_l"] / 2, bz + P["box_h"] / 2) * Box(P["body_w"], body_l, P["body_h"])
for yy in (y0 + P["bezel_t"] / 2, y0 + P["box_l"] - P["bezel_t"] / 2):
    box += Pos(0, yy, bz + P["box_h"] / 2) * Box(P["box_w"], P["bezel_t"], P["box_h"])
foot_bolt = Pos(fx, fy, z_floor_bot - 8) * Cylinder(4, 50, align=(C, C, MAX))
caps_placed = [Pos(x, 0, 0) * cap for x in clamp_xs]


parts = {"tray": tray, "clamp_cap_L": Pos(clamp_xs[0], 0, 0) * cap, "clamp_cap_R": Pos(clamp_xs[1], 0, 0) * cap}
context = {"pipe": pipe, "aio_box": box, "foot_bolt": foot_bolt}
