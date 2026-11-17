"""Genera schematic.png — diagrama de conexiones del LaserHarp."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

# ── Paleta ─────────────────────────────────────────────────────────────────
BG      = '#0d1117'
C_RPI   = '#1c2b3a'
C_COMP  = '#1a2b1a'
C_WIRE  = '#e0e0e0'
C_3V3   = '#e05252'
C_GND   = '#888888'
C_I2C   = '#4fc3f7'
C_GPIO  = '#81c784'
C_CHORD = '#ffb74d'
C_TITLE = '#e0e0e0'
C_LABEL = '#cfd8dc'

def box(ax, x, y, w, h, label, sub='', fc=C_COMP, ec='#37474f', lc='white'):
    r = FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.03',
                       fc=fc, ec=ec, lw=1.5, zorder=3)
    ax.add_patch(r)
    ty = y + h/2 + (0.08 if sub else 0)
    ax.text(x + w/2, ty, label, ha='center', va='center',
            fontsize=8.5, fontweight='bold', color=lc, zorder=4)
    if sub:
        ax.text(x + w/2, y + h/2 - 0.13, sub, ha='center', va='center',
                fontsize=6.5, color='#aaaaaa', zorder=4)

def pin(ax, x, y, label, col, side='right'):
    ha = 'left' if side == 'right' else 'right'
    ax.plot(x, y, 'o', color=col, ms=5, zorder=5)
    ox = 0.08 if side == 'right' else -0.08
    ax.text(x + ox, y, label, ha=ha, va='center',
            fontsize=6.5, color=col, zorder=5)

def wire(ax, pts, col, lw=1.5, style='-'):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ax.plot(xs, ys, color=col, lw=lw, ls=style, zorder=2, solid_capstyle='round')

# ── Canvas ─────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(18, 11))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 18)
ax.set_ylim(0, 11)
ax.axis('off')

ax.text(9, 10.65, 'LaserHarp — Diagrama de Conexiones',
        ha='center', va='center', fontsize=14, fontweight='bold', color=C_TITLE)
ax.text(9, 10.35, 'Raspberry Pi 4B  ·  VL53L0X  ·  SH1106 OLED  ·  EC11  ·  5 Botones',
        ha='center', va='center', fontsize=8, color='#78909c')

# ── Raspberry Pi block ─────────────────────────────────────────────────────
RX, RY, RW, RH = 0.3, 0.4, 2.8, 9.8
r = FancyBboxPatch((RX, RY), RW, RH, boxstyle='round,pad=0.05',
                   fc=C_RPI, ec='#1565c0', lw=2, zorder=3)
ax.add_patch(r)
ax.text(RX + RW/2, RY + RH + 0.18, 'Raspberry Pi 4B',
        ha='center', va='center', fontsize=9, fontweight='bold', color='#42a5f5', zorder=4)

# Pin definitions: (label_inside, y, color, gpio_num_or_None)
rpi_pins = [
    ('3.3 V',  9.8, C_3V3,   None),
    ('5 V',    9.2, C_3V3,   None),
    ('GND',    8.5, C_GND,   None),
    ('GPIO 2 (SDA)', 7.6, C_I2C,   2),
    ('GPIO 3 (SCL)', 6.9, C_I2C,   3),
    ('GPIO 5', 5.9, C_CHORD, 5),
    ('GPIO 6', 5.2, C_CHORD, 6),
    ('GPIO 22',4.4, C_GPIO,  22),
    ('GPIO 23',3.7, C_GPIO,  23),
    ('GPIO 24',3.0, C_GPIO,  24),
    ('GPIO 25',2.3, C_GPIO,  25),
    ('GPIO 26',1.6, C_CHORD, 26),
    ('GPIO 27',0.9, C_GPIO,  27),
]

for label, y, col, _ in rpi_pins:
    ax.plot(RX + RW, y, 'o', color=col, ms=6, zorder=6)
    ax.text(RX + RW - 0.1, y, label, ha='right', va='center',
            fontsize=6.5, color=col, zorder=6)

# ── I2C bus vertical rail ──────────────────────────────────────────────────
BUS_X = 4.5
ax.plot([BUS_X, BUS_X], [6.5, 9.9], color=C_I2C, lw=2.5, zorder=2)
ax.text(BUS_X, 10.1, 'I2C Bus', ha='center', va='center',
        fontsize=7, color=C_I2C, fontstyle='italic')

# ── Power rails ────────────────────────────────────────────────────────────
PWR_X1, PWR_X2 = RX + RW, 13.5
ax.plot([PWR_X1, PWR_X2], [9.8, 9.8], color=C_3V3, lw=1.5, ls='--', zorder=2, alpha=0.6)
ax.plot([PWR_X1, PWR_X2], [8.5, 8.5], color=C_GND, lw=1.5, ls='--', zorder=2, alpha=0.6)
ax.text(PWR_X2 + 0.1, 9.8, '3.3V', ha='left', va='center', fontsize=7, color=C_3V3)
ax.text(PWR_X2 + 0.1, 8.5, 'GND',  ha='left', va='center', fontsize=7, color=C_GND)

# ── VL53L0X ───────────────────────────────────────────────────────────────
VX, VY = 5.5, 8.0
box(ax, VX, VY, 2.8, 1.3, 'VL53L0X', 'Sensor láser I2C (0x29)', fc='#0d2b0d', ec='#2e7d32')

# pines del componente
for lbl, px, py, col in [
    ('VIN', VX,       VY+0.95, C_3V3),
    ('GND', VX,       VY+0.55, C_GND),
    ('SDA', VX,       VY+0.25, C_I2C),
    ('SCL', VX+2.8,   VY+0.85, C_I2C),
]:
    side = 'right' if px == VX else 'left'
    pin(ax, px, py, lbl, col, side=side)

# wires VL53L0X
wire(ax, [(RX+RW, 9.8), (VX, VY+0.95)],              C_3V3)
wire(ax, [(RX+RW, 8.5), (VX, VY+0.55)],              C_GND)
wire(ax, [(BUS_X, 7.6), (VX, VY+0.25)],              C_I2C)   # SDA
wire(ax, [(BUS_X, 9.0), (BUS_X, 9.0),                # SCL: bus → sensor right side
          (VX+2.8, VY+0.85)], C_I2C)
# RPi SDA/SCL → bus
wire(ax, [(RX+RW, 7.6), (BUS_X, 7.6)], C_I2C)
wire(ax, [(RX+RW, 6.9), (BUS_X, 6.9)], C_I2C)

# ── SH1106 OLED ───────────────────────────────────────────────────────────
OX, OY = 5.5, 5.8
box(ax, OX, OY, 2.8, 1.3, 'SH1106 OLED', '128×64 I2C (0x3C)', fc='#1a1a2e', ec='#5c6bc0')

for lbl, px, py, col in [
    ('VCC', OX,       OY+0.95, C_3V3),
    ('GND', OX,       OY+0.55, C_GND),
    ('SDA', OX,       OY+0.25, C_I2C),
    ('SCL', OX+2.8,   OY+0.65, C_I2C),
]:
    side = 'right' if px == OX else 'left'
    pin(ax, px, py, lbl, col, side=side)

wire(ax, [(RX+RW, 9.8), (4.0, 9.8), (4.0, OY+0.95), (OX, OY+0.95)], C_3V3)
wire(ax, [(RX+RW, 8.5), (3.8, 8.5), (3.8, OY+0.55), (OX, OY+0.55)], C_GND)
wire(ax, [(BUS_X, 7.6), (BUS_X, OY+0.25), (OX, OY+0.25)], C_I2C)
wire(ax, [(BUS_X, 6.9), (BUS_X, 6.9), (OX+2.8, OY+0.65)], C_I2C)

# ── EC11 Encoder ──────────────────────────────────────────────────────────
EX, EY = 5.5, 3.5
box(ax, EX, EY, 2.8, 1.8, 'EC11', 'Encoder rotativo + pulsador', fc='#2b1a0d', ec='#e65100')

for lbl, px, py, col in [
    ('A (→27)',  EX,       EY+1.4, C_GPIO),
    ('B (→22)',  EX,       EY+1.0, C_GPIO),
    ('C / GND',  EX,       EY+0.6, C_GND),
    ('D (→25)',  EX+2.8,   EY+1.4, C_GPIO),
    ('E / GND',  EX+2.8,   EY+1.0, C_GND),
]:
    side = 'right' if px == EX else 'left'
    pin(ax, px, py, lbl, col, side=side)

wire(ax, [(RX+RW, 4.4), (5.0, 4.4), (5.0, EY+1.0), (EX, EY+1.0)], C_GPIO)  # GPIO22 → B
wire(ax, [(RX+RW, 0.9), (4.8, 0.9), (4.8, EY+1.4), (EX, EY+1.4)], C_GPIO)  # GPIO27 → A
wire(ax, [(RX+RW, 2.3), (EX+2.8, EY+1.4)], C_GPIO)                           # GPIO25 → D
wire(ax, [(RX+RW, 8.5), (3.6, 8.5), (3.6, EY+0.6), (EX, EY+0.6)], C_GND)   # GND → C
wire(ax, [(RX+RW, 8.5), (EX+2.8, EY+1.0)], C_GND)                            # GND → E

# ── Botón Enter (GPIO23) ───────────────────────────────────────────────────
BNX, BNY = 5.5, 2.4
box(ax, BNX, BNY, 2.0, 0.7, 'BTN Enter', 'GPIO 23', fc='#1a1a2b', ec='#7986cb')
pin(ax, BNX,     BNY+0.35, 'GPIO23', C_GPIO, 'right')
pin(ax, BNX+2.0, BNY+0.35, 'GND',    C_GND,  'left')
wire(ax, [(RX+RW, 3.7), (BNX, BNY+0.35)], C_GPIO)
wire(ax, [(RX+RW, 8.5), (3.4, 8.5), (3.4, BNY+0.35), (BNX+2.0, BNY+0.35)], C_GND)

# ── Botón Down (GPIO24) ────────────────────────────────────────────────────
BDX, BDY = 5.5, 1.5
box(ax, BDX, BDY, 2.0, 0.7, 'BTN Down', 'GPIO 24', fc='#1a1a2b', ec='#7986cb')
pin(ax, BDX,     BDY+0.35, 'GPIO24', C_GPIO, 'right')
pin(ax, BDX+2.0, BDY+0.35, 'GND',    C_GND,  'left')
wire(ax, [(RX+RW, 3.0), (BDX, BDY+0.35)], C_GPIO)
wire(ax, [(RX+RW, 8.5), (3.2, 8.5), (3.2, BDY+0.35), (BDX+2.0, BDY+0.35)], C_GND)

# ── Botones Acorde ─────────────────────────────────────────────────────────
chord_data = [
    (10.5, 7.0, 'BTN Acorde — 1ª (Do)', 'GPIO 5',  5,  5.9),
    (10.5, 5.7, 'BTN Acorde — 3ª (Mi)', 'GPIO 6',  6,  5.2),
    (10.5, 4.4, 'BTN Acorde — 5ª (Sol)','GPIO 26', 26, 1.6),
]

for cx, cy, lbl, sub, gpio, rpi_y in chord_data:
    box(ax, cx, cy, 3.2, 0.9, lbl, sub, fc='#2b1a00', ec='#f57f17')
    pin(ax, cx,     cy+0.45, f'GPIO{gpio}', C_CHORD, 'right')
    pin(ax, cx+3.2, cy+0.45, 'GND',         C_GND,   'left')
    # wire from RPi
    rx_out = RX + RW
    wire(ax, [(rx_out, rpi_y), (9.5, rpi_y), (9.5, cy+0.45), (cx, cy+0.45)], C_CHORD)
    wire(ax, [(cx+3.2, cy+0.45), (14.2, cy+0.45)], C_GND, style='--')
    ax.text(14.3, cy+0.45, 'GND', ha='left', va='center', fontsize=6.5, color=C_GND)

# ── Leyenda ────────────────────────────────────────────────────────────────
LX, LY = 9.5, 1.0
ax.text(LX, LY + 1.8, 'Leyenda', ha='left', va='center',
        fontsize=8, fontweight='bold', color=C_TITLE)
for i, (col, lbl) in enumerate([
    (C_3V3,   '3.3 V'),
    (C_GND,   'GND'),
    (C_I2C,   'I2C (SDA/SCL)'),
    (C_GPIO,  'GPIO — Menú'),
    (C_CHORD, 'GPIO — Acorde'),
]):
    yl = LY + 1.4 - i * 0.35
    ax.plot([LX, LX + 0.5], [yl, yl], color=col, lw=2.5)
    ax.text(LX + 0.65, yl, lbl, ha='left', va='center',
            fontsize=7.5, color=C_LABEL)

# ── Notas de frecuencia ────────────────────────────────────────────────────
ax.text(10.5, 3.5, 'Frecuencias acorde mayor (Do4):', ha='left', va='center',
        fontsize=7.5, color='#b0bec5', fontstyle='italic')
for i, (n, f, g) in enumerate([
    ('1ª  Do  (C4)', '261.6 Hz', 'GPIO 5'),
    ('3ª  Mi  (E4)', '327.0 Hz', 'GPIO 6'),
    ('5ª  Sol (G4)', '392.4 Hz', 'GPIO 26'),
]):
    ax.text(10.5, 3.1 - i*0.35, f'  {g}  →  {n}  —  {f}',
            ha='left', va='center', fontsize=7, color='#90a4ae')

plt.tight_layout(pad=0.2)
plt.savefig('schematic.png', dpi=150, bbox_inches='tight',
            facecolor=BG, edgecolor='none')
plt.savefig('schematic.pdf', bbox_inches='tight',
            facecolor=BG, edgecolor='none')
print("Generados: schematic.png  schematic.pdf")
