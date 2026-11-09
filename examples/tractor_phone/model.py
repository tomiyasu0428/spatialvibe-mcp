"""Phone holder for the tractor's 1" handrail pipe — the subject of the assembly reel.

Axes: X = left/right (+X right), Y = forward (+Y toward the hood), Z = up. Units: mm.
Origin = pipe centre; the pipe runs along X. The driver sits on the −Y side and looks at the screen.

Parts to print (4):
  clamp_lower  lower clamp half (print split face down)
  clamp_upper  upper clamp half + mounting flange
  arm          riser bolted to the flange, tilted back toward the driver
  cradle       phone cradle with side walls, bottom lip and a cable slot
Hardware: 2x M5x35 (clamp), 2x M5x16 (arm to flange), 1x M6x30 + wing nut (cradle tilt),
1 mm rubber sheet around the pipe.

Pipe Ø25.6 mm comes from the AgOpenGPS build guide (same pipe as examples/aio_mount).
Phone size is WITH case and is a guess (160 x 78 x 12) — measure the real one before printing.
"""
from build123d import Align, Box, Cylinder, Pos, Rot

C, MIN, MAX = Align.CENTER, Align.MIN, Align.MAX

P = dict(
    pipe_d=25.6,              # build guide
    clamp_id=27.5,            # with 1 mm rubber sheet
    clamp_gap=2.0,
    clamp_w=26.0,             # along X
    phone_l=160.0, phone_w=78.0, phone_t=12.0,   # with case — guess, measure
    fit=1.0,                  # clearance each side
    tilt=15.0,                # cradle leans back toward the driver (deg)
    arm_h=70.0,
)

R = P["clamp_id"] / 2
g = P["clamp_gap"] / 2
ear = 6.5
bolt_y = R + ear
clamp_len = 2 * (bolt_y + 6.5)
top = R + 7                     # top of the upper clamp body

# ---- clamp halves --------------------------------------------------------------------------
upper = Pos(0, 0, g) * Box(P["clamp_w"], clamp_len, top - g, align=(C, C, MIN))
upper += Pos(0, 0, top) * Box(40, 34, 6, align=(C, C, MIN))            # flange for the arm
upper -= Rot(0, 90, 0) * Cylinder(R, P["clamp_w"] + 2)
for y in (-bolt_y, bolt_y):
    upper -= Pos(0, y, 0) * Cylinder(2.75, 2 * top)
for x in (-12, 12):
    upper -= Pos(x, 0, top) * Cylinder(2.75, 20)

lower = Pos(0, 0, -g) * Box(P["clamp_w"], clamp_len, R + 7 - g, align=(C, C, MAX))
lower -= Rot(0, 90, 0) * Cylinder(R, P["clamp_w"] + 2)
for y in (-bolt_y, bolt_y):
    lower -= Pos(0, y, 0) * Cylinder(2.75, 80)

# ---- arm: foot on the flange, riser, round head for the tilt bolt -------------------------
z_arm = top + 6
arm = Pos(0, 0, z_arm) * Box(40, 34, 6, align=(C, C, MIN))
arm += Pos(0, 0, z_arm) * Box(20, 14, P["arm_h"], align=(C, C, MIN))
head_z = z_arm + P["arm_h"]
arm += Pos(0, 0, head_z) * Rot(0, 90, 0) * Cylinder(10, 20)
arm -= Pos(0, 0, head_z) * Rot(0, 90, 0) * Cylinder(3.25, 30)
for x in (-12, 12):
    arm -= Pos(x, 0, z_arm) * Cylinder(2.75, 20)

# ---- cradle (built upright, then tilted about the tilt bolt) ------------------------------
iw = P["phone_w"] + 2 * P["fit"]       # inner width (X)
it = P["phone_t"] + 2 * P["fit"]       # inner depth (Y)
wall, back = 3.0, 4.0
ow = iw + 2 * wall
h = 120.0                               # back plate height; phone sticks out the top
z0 = -40.0                              # cradle bottom relative to the tilt bolt
yb = -11 - back                         # back plate's front face (phone side)
cr = Pos(0, yb + back / 2, z0) * Box(ow, back, h, align=(C, C, MIN))                    # back plate
for sx in (-1, 1):
    cr += Pos(sx * (iw / 2 + wall / 2), yb - it / 2, z0) * Box(wall, it, 75, align=(C, C, MIN))
cr += Pos(0, yb - it / 2, z0 - wall) * Box(ow, it + back, wall, align=(C, C, MIN))      # floor
cr += Pos(0, yb - it - wall / 2, z0 - wall) * Box(ow, wall, 14, align=(C, C, MIN))      # front lip
cr -= Pos(0, yb - it / 2, z0 - wall / 2) * Box(24, it + 10, wall + 2)                   # cable slot
cr -= Pos(0, yb - it - wall / 2, z0 + 4) * Box(30, wall + 2, 14, align=(C, C, MIN))     # lip notch
for sx in (-1, 1):                                                                       # tilt ears
    cr += Pos(sx * 15.5, 0, 0) * Rot(0, 90, 0) * Cylinder(10, 10)
    cr += Pos(sx * 15.5, (yb + back) / 2, 0) * Box(10, -(yb + back) + 0.5, 20)
cr -= Rot(0, 90, 0) * Cylinder(3.25, 60)
cradle = Pos(0, 0, head_z) * Rot(-P["tilt"], 0, 0) * cr

phone = Pos(0, 0, head_z) * Rot(-P["tilt"], 0, 0) * Pos(0, yb - it / 2, z0 + 0.5) * Box(
    P["phone_w"], P["phone_t"], P["phone_l"], align=(C, C, MIN))
pipe = Rot(0, 90, 0) * Cylinder(P["pipe_d"] / 2, 360)

parts = {"clamp_lower": lower, "clamp_upper": upper, "arm": arm, "cradle": cradle}
context = {"pipe": pipe, "phone": phone}
