#!/usr/bin/env python3
"""
ArpaLaser — Full synth
  Buttons          → notes (scale-aware, octave-shifted)
  Encoder rotate   → quick effect (MORPH / SAT / FILTER) when not in menu
                     navigate / edit value when in menu
  Encoder press    → cycle quick effect when not in menu
                     confirm / enter when in menu
  OCT UP / DOWN    → shift octave
  OCT UP + DOWN    → open / close full menu
  Sensor           → tremolo depth
  Screen           → live synth UI  or  menu overlay
"""

import time, threading, math
import numpy as np
import board, busio, digitalio
import adafruit_vl53l0x
from adafruit_rgb_display import st7789
from gpiozero import RotaryEncoder, Button
from PIL import Image, ImageDraw, ImageFont
import sounddevice as sd
from menu_engine import ArpaLaserEngine

# ── Constants ──────────────────────────────────────────────────────────────────
SR        = 44100
BLOCK     = 512
TREM_RATE = 5.0
MAX_HARM  = 16
W, H      = 320, 170
OCT_MIN, OCT_MAX = -3, 3
C4        = 261.63   # base frequency

BUTTON_GPIOS = [21, 15, 18, 16, 23, 24, 25]   # left → right

MODE_COLORS = {
    'MORPH':      (255, 200,   0),
    'SATURATION': (255,  80,  80),
    'FILTER':     ( 80, 255, 150),
}

# ── Menu engine ────────────────────────────────────────────────────────────────
menu    = ArpaLaserEngine()
in_menu = False

# ── Quick-effect mode (encoder when not in menu) ───────────────────────────────
MODES     = ['MORPH', 'SATURATION', 'FILTER']
mode_idx  = 0
mode_vals = {'MORPH': 0.0, 'SATURATION': 0.0, 'FILTER': 1.0}

# ── Octave ─────────────────────────────────────────────────────────────────────
octave = 0

# ── Scale → button frequencies ────────────────────────────────────────────────
def scale_freqs(octave_shift=0):
    _, semis = menu.get_current_scale()
    base = C4 * (2.0 ** octave_shift)
    return {gpio: base * (2.0 ** (s / 12)) for gpio, s in zip(BUTTON_GPIOS, semis)}

def scale_note_names():
    name, semis = menu.get_current_scale()
    # note names for each degree
    NOTE_NAMES = ['C','C#','D','Eb','E','F','F#','G','Ab','A','Bb','B']
    base_oct = 4 + octave
    names = []
    for s in semis:
        oct_off = s // 12
        names.append(NOTE_NAMES[s % 12] + str(base_oct + oct_off))
    return names

# ── Effect buffers (global, used inside audio callback) ───────────────────────
_rev_len = int(0.08 * SR)
_rev_buf = np.zeros(_rev_len, dtype=np.float32)
_rev_pos = 0

_dly_max = int(0.55 * SR)
_dly_buf = np.zeros(_dly_max, dtype=np.float32)
_dly_wpos = 0

def _apply_reverb(block, room, wet):
    global _rev_pos
    if wet < 0.01: return block
    n, pos = len(block), _rev_pos
    end = pos + n
    if end <= _rev_len:
        delayed = _rev_buf[pos:end].copy()
        _rev_buf[pos:end] = block + delayed * (0.25 + room * 0.45)
    else:
        sp = _rev_len - pos
        delayed = np.concatenate([_rev_buf[pos:], _rev_buf[:n - sp]])
        _rev_buf[pos:]    = block[:sp]     + _rev_buf[pos:]    * (0.25 + room * 0.45)
        _rev_buf[:n - sp] = block[sp:]     + _rev_buf[:n - sp] * (0.25 + room * 0.45)
    _rev_pos = end % _rev_len
    return block * (1.0 - wet) + delayed * wet

def _apply_delay(block, dtime, dfb):
    global _dly_wpos
    if dtime < 0.005: return block
    dsamp = min(int(dtime * SR), _dly_max - 1)
    n     = len(block)
    rpos  = (_dly_wpos - dsamp) % _dly_max
    end   = rpos + n
    if end <= _dly_max:
        delayed = _dly_buf[rpos:end].copy()
    else:
        sp = _dly_max - rpos
        delayed = np.concatenate([_dly_buf[rpos:], _dly_buf[:n - sp]])
    new_write = block + delayed * dfb
    wp_end = _dly_wpos + n
    if wp_end <= _dly_max:
        _dly_buf[_dly_wpos:wp_end] = new_write
    else:
        sp = _dly_max - _dly_wpos
        _dly_buf[_dly_wpos:] = new_write[:sp]
        _dly_buf[:n - sp]    = new_write[sp:]
    _dly_wpos = wp_end % _dly_max
    return block + delayed * 0.5

# ── Waveform generators ────────────────────────────────────────────────────────
def _gen_wave(inst, phase_arr, f, morph):
    """Generate one block of audio for a voice."""
    if inst == 'sine':
        return np.sin(phase_arr)
    elif inst == 'sawtooth' or inst == 'guitar':
        specs = [(1,1.0),(2,0.5),(3,0.28),(4,0.14),(5,0.07),(6,0.04)]
        sig, norm = np.zeros(len(phase_arr)), 0.0
        for k, amp in specs:
            if k * f < SR / 2: sig += amp * np.sin(phase_arr * k); norm += amp
        return sig / norm if norm else sig
    elif inst == 'square':
        sig, norm = np.zeros(len(phase_arr)), 0.0
        for k in range(1, 16, 2):
            if k * f < SR / 2: sig += (1/k) * np.sin(phase_arr * k); norm += 1/k
        return sig / norm if norm else sig
    elif inst == 'violin':
        specs = [(1,1.0),(2,0.7),(3,0.55),(4,0.35),(5,0.2),(6,0.12)]
        sig = np.zeros(len(phase_arr))
        for k, amp in specs:
            if k * f < SR / 2: sig += amp * np.sin(phase_arr * k)
        mx = np.max(np.abs(sig)); return sig / mx if mx > 1e-8 else sig
    elif inst == 'piano':
        mod = np.sin(2 * phase_arr)
        sig = (np.sin(phase_arr + 3.0 * mod)
             + 0.4 * np.sin(3 * phase_arr + 1.5 * mod)
             + 0.15 * np.sin(4 * phase_arr))
        mx = np.max(np.abs(sig)); return sig / mx if mx > 1e-8 else sig
    else:
        # morph: sine → sawtooth based on morph param
        n_harm = max(1, int(morph * (MAX_HARM - 1)) + 1)
        sig, norm = np.zeros(len(phase_arr)), 0.0
        for k in range(1, n_harm + 1):
            if k * f < SR / 2: sig += (1/k) * np.sin(phase_arr * k); norm += 1/k
        return sig / norm if norm else sig

# ── Shared synth state ─────────────────────────────────────────────────────────
lock  = threading.Lock()
synth = {
    'voices':     {},
    'trem_phase': 0.0,
    'trem_depth': 0.0,
    # quick controls
    'morph':      0.0,
    'saturation': 0.0,
    'filt':       1.0,
    # from menu
    'inst':   'sine',
    'adsr':   (0.05, 0.1, 0.75, 0.2),
    'eq':     [1.0, 1.0, 1.0],
    'reverb': (0.0, 0.0),
    'delay':  (0.0, 0.0),
    'dist':   0.0,
}

# ── ADSR per-block helper ──────────────────────────────────────────────────────
def _adsr_amp(v, att, dec, sus, rel, dt):
    ph = v['env_ph']
    t  = v['env_t']
    if not v['on'] and ph not in ('release', 'off'):
        v['env_ph'] = 'release'; v['env_t'] = 0.0
        v['rel_from'] = v['env_amp']; ph, t = 'release', 0.0
    if ph == 'attack':
        amp = min(1.0, t / att) if att > 0 else 1.0
        v['env_t'] += dt
        if v['env_t'] >= att: v['env_ph'] = 'decay'; v['env_t'] -= att
    elif ph == 'decay':
        amp = 1.0 - (1.0 - sus) * min(1.0, t / dec) if dec > 0 else sus
        v['env_t'] += dt
        if v['env_t'] >= dec: v['env_ph'] = 'sustain'; v['env_t'] = 0.0
    elif ph == 'sustain':
        amp = sus; v['env_t'] += dt
    elif ph == 'release':
        start = v.get('rel_from', sus)
        amp = max(0.0, start * (1.0 - t / rel)) if rel > 0 else 0.0
        v['env_t'] += dt
        if v['env_t'] >= rel: v['env_ph'] = 'off'; v['env_t'] = 0.0; amp = 0.0
    else:
        amp = 0.0
    v['env_amp'] = amp
    return amp

# ── Audio callback ─────────────────────────────────────────────────────────────
def callback(outdata, frames, time_info, status):
    pi2 = 2 * math.pi
    dt  = frames / SR

    with lock:
        voices     = list(synth['voices'].values())
        trem_ph    = synth['trem_phase']
        trem_depth = synth['trem_depth']
        morph      = synth['morph']
        sat        = synth['saturation']
        filt       = synth['filt']
        inst       = synth['inst']
        att, dec, sus, rel = synth['adsr']
        eq         = synth['eq']
        reverb     = synth['reverb']
        delay      = synth['delay']
        dist       = synth['dist']
        synth['trem_phase'] = (trem_ph + pi2 * TREM_RATE * frames / SR) % pi2

    # Tremolo
    trem = 1.0 - trem_depth * 0.5 * (
        1.0 - np.sin(np.linspace(trem_ph,
                                 trem_ph + pi2 * TREM_RATE * frames / SR,
                                 frames, endpoint=False))
    )

    # Main low-pass filter: 400–6000 Hz, always has audible effect
    filt_combined = max(0.01, min(1.0, filt))
    cutoff  = 400.0 + filt_combined * 5600.0
    alpha   = min(0.92, pi2 * cutoff / SR)   # cap < 1.0 so filter is always on

    # 3-band EQ crossover alphas (fixed)
    alpha_lo = pi2 * 300.0  / SR   # low shelf  < 300 Hz
    alpha_hi = pi2 * 3000.0 / SR   # hi split   > 3000 Hz

    buf = np.zeros(frames, dtype=np.float64)

    for v in voices:
        f          = v['freq']
        phase_base = v['phase'] + pi2 * f * np.arange(frames, dtype=np.float64) / SR

        # Waveform
        sig = _gen_wave(inst, phase_base, f, morph).astype(np.float64)

        # Main low-pass filter (FILTER knob)
        y = np.zeros(frames); yv = v['filt_y']
        for i in range(frames):
            yv = alpha * sig[i] + (1.0 - alpha) * yv; y[i] = yv
        v['filt_y'] = yv; sig = y

        # 3-band EQ: Low (<300 Hz) / Mid (300–3000 Hz) / High (>3000 Hz)
        lo_y = np.zeros(frames); lo_v = v['eq_lo']
        for i in range(frames):
            lo_v = alpha_lo * sig[i] + (1.0 - alpha_lo) * lo_v; lo_y[i] = lo_v
        v['eq_lo'] = lo_v

        hi_y = np.zeros(frames); hi_v = v['eq_mid']
        for i in range(frames):
            hi_v = alpha_hi * sig[i] + (1.0 - alpha_hi) * hi_v; hi_y[i] = hi_v
        v['eq_mid'] = hi_v

        lo_band  = lo_y          # below 300 Hz
        mid_band = hi_y - lo_y   # 300–3000 Hz
        hi_band  = sig - hi_y    # above 3000 Hz
        sig = lo_band * eq[0] + mid_band * eq[1] + hi_band * eq[2]

        # ADSR envelope
        amp = _adsr_amp(v, att, dec, sus, rel, dt)
        buf += sig * amp
        v['phase'] = (v['phase'] + pi2 * f * frames / SR) % pi2

    # Tremolo + normalize
    buf *= trem
    if voices:
        buf /= max(len(voices), 1)

    # Distortion (menu dist + quick saturation)
    drive = 1.0 + max(sat, dist) * 19.0
    buf   = np.tanh(buf * drive) / math.tanh(drive + 1e-9)

    buf32 = buf.astype(np.float32)

    # Reverb
    buf32 = _apply_reverb(buf32, *reverb).astype(np.float32)

    # Delay
    buf32 = _apply_delay(buf32, *delay).astype(np.float32)

    buf32 = np.clip(buf32, -1.0, 1.0)
    outdata[:] = np.column_stack((buf32, buf32))

# ── Hardware: sensor ───────────────────────────────────────────────────────────
i2c = busio.I2C(board.SCL, board.SDA)
sensor = None
for _addr in (0x29, 0x30, 0x31, 0x32):
    try:
        sensor = adafruit_vl53l0x.VL53L0X(i2c, address=_addr)
        sensor.measurement_timing_budget = 20000
        print(f"[SENSOR] detectado en 0x{_addr:02x}")
        break
    except Exception:
        pass
if sensor is None:
    print("[SENSOR] no detectado — tremolo desactivado")

# ── Hardware: screen ───────────────────────────────────────────────────────────
spi_disp = busio.SPI(clock=board.D7, MOSI=board.D6)
disp = st7789.ST7789(
    spi_disp,
    cs=digitalio.DigitalInOut(board.D13),
    dc=digitalio.DigitalInOut(board.D19),
    rst=digitalio.DigitalInOut(board.D26),
    width=170, height=320, rotation=270, x_offset=35,
    baudrate=24000000,
)

try:
    _B = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    _R = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    FONT_XL = ImageFont.truetype(_B, 36)   # big menu item
    FONT_LG = ImageFont.truetype(_B, 24)
    FONT_BG = ImageFont.truetype(_B, 26)   # second menu item
    FONT_MD = ImageFont.truetype(_B, 16)
    FONT_SM = ImageFont.truetype(_R, 13)
    FONT_MN = ImageFont.truetype(_B, 20)
except Exception:
    FONT_XL = FONT_BG = FONT_LG = FONT_MD = FONT_SM = FONT_MN = ImageFont.load_default()

# ── Hardware: encoder & buttons ───────────────────────────────────────────────
encoder    = RotaryEncoder(27, 17, wrap=False)
btn_enc    = Button(22, pull_up=True, bounce_time=0.15)
btn_octup  = Button(10, pull_up=True, bounce_time=0.05)
btn_octdn  = Button(9,  pull_up=True, bounce_time=0.05)

def _make_voice(freq):
    return {'freq': freq, 'phase': 0.0, 'env_ph': 'attack',
            'env_t': 0.0, 'env_amp': 0.0, 'rel_from': 0.0,
            'filt_y': 0.0, 'eq_lo': 0.0, 'eq_mid': 0.0, 'on': True}

def press(gpio):
    freqs = scale_freqs(octave)
    if gpio not in freqs: return
    with lock:
        synth['voices'][gpio] = _make_voice(freqs[gpio])

def release(gpio):
    with lock:
        if gpio in synth['voices']:
            synth['voices'][gpio]['on'] = False

note_buttons = {}
for gpio in BUTTON_GPIOS:
    b = Button(gpio, pull_up=True, bounce_time=0.05)
    b.when_pressed  = lambda g=gpio: press(g)
    b.when_released = lambda g=gpio: release(g)
    note_buttons[gpio] = b

# ── Screen drawing ─────────────────────────────────────────────────────────────
def _bar(draw, x, y, w, h, val, color):
    draw.rectangle((x, y, x+w, y+h), fill=(20,20,30), outline=color, width=1)
    fw = int((w-4) * max(0.0, min(1.0, val)))
    if fw > 0: draw.rectangle((x+2, y+2, x+2+fw, y+h-2), fill=color)

def draw_synth(mode, vals, depth, dist_mm, active_notes, oct, inst, scale_name):
    img  = Image.new('RGB', (W, H), (5, 5, 15))
    draw = ImageDraw.Draw(img)
    col  = MODE_COLORS[mode]

    # Header
    draw.rectangle((0, 0, W, 33), fill=(0, 18, 45))
    draw.text((8, 5),   'ToF Synth',           font=FONT_LG, fill=(0, 200, 255))
    draw.text((195, 6), inst.upper()[:6],      font=FONT_SM, fill=(180, 180, 60))
    oct_str = f'OCT {oct:+d}'
    draw.text((255, 17), oct_str, font=FONT_SM,
              fill=(255, 160, 0) if oct != 0 else (80, 80, 100))

    # Scale name
    draw.text((195, 18), scale_name, font=FONT_SM, fill=(120, 200, 120))

    # Active mode bar
    draw.text((8, 38), mode[:4], font=FONT_SM, fill=col)
    _bar(draw, 50, 37, W-95, 22, vals[mode], col)
    draw.text((W-40, 38), f'{vals[mode]:.2f}', font=FONT_SM, fill=col)

    # Mini bars all modes
    for i, m in enumerate(MODES):
        c = MODE_COLORS[m]; cx = 5 + i * 107
        draw.text((cx, 65), m[:4], font=FONT_SM, fill=c)
        _bar(draw, cx, 80, 98, 10, vals[m], c)

    # Tremolo
    TC = (255, 80, 220)
    draw.text((5, 97), 'TREM', font=FONT_SM, fill=TC)
    _bar(draw, 50, 97, 185, 14, depth, TC)
    draw.text((245, 97), f'{int(dist_mm)}mm', font=FONT_SM, fill=(120,120,120))

    # Note keys
    draw.line([(0,115),(W,115)], fill=(40,40,60))
    note_labels = scale_note_names()
    kw = W // 7
    for i, name in enumerate(note_labels):
        on = name in active_notes
        x0 = i * kw
        draw.rectangle((x0+1, 117, x0+kw-2, H-1),
                        fill=(0,70,25) if on else (18,18,30),
                        outline=(0,220,80) if on else (40,40,55))
        draw.text((x0+4, 129), name[:2], font=FONT_MD,
                  fill=(0,255,100) if on else (65,65,75))
        draw.text((x0+4, 150), name[2:], font=FONT_SM,
                  fill=(0,180,60) if on else (40,40,50))
    disp.image(img)

def _draw_param_bars(draw, names, vals, active_idx, colors):
    """Vertical bar chart for EQ / ADSR display."""
    n       = len(names)
    top     = 28          # below header
    bot     = H - 22      # above bottom bar
    bar_h   = bot - top - 18   # height for the bar fill area
    lbl_y   = bot - 16         # label row
    val_gap = 14               # gap above bar top for value text

    slot_w = W // n
    pad    = 7

    for i in range(n):
        x0   = i * slot_w + pad
        x1   = (i + 1) * slot_w - pad
        bw   = x1 - x0
        act  = (i == active_idx)
        col  = tuple(min(255, c + 50) for c in colors[i]) if act else colors[i]
        dim  = tuple(c // 3 for c in colors[i])

        # Background slot
        outline_col = (160, 80, 255) if act else (40, 35, 60)
        draw.rectangle((x0, top, x1, top + bar_h),
                       fill=(12, 10, 28), outline=outline_col, width=2 if act else 1)

        # Filled bar (bottom-up)
        filled = int(vals[i] / 16 * bar_h)
        if filled > 0:
            draw.rectangle((x0 + 2, top + bar_h - filled,
                            x1 - 2, top + bar_h - 1), fill=col)
        # Neutral line at 8 (only for EQ where 8=neutral)
        if n == 3:
            ny = top + bar_h // 2
            draw.line([(x0, ny), (x1, ny)],
                      fill=(180, 180, 80) if act else (60, 55, 80), width=1)

        # Value number above bar
        val_str = str(vals[i])
        vx = x0 + bw // 2 - 6
        vy = top + bar_h - filled - val_gap
        vy = max(top + 2, min(vy, top + bar_h - val_gap))
        draw.text((vx, vy), val_str, font=FONT_SM,
                  fill=(255, 255, 255) if act else (130, 120, 150))

        # Label below
        lx = x0 + bw // 2 - 6
        draw.text((lx, lbl_y), names[i][:3], font=FONT_SM,
                  fill=col if act else dim)

    # Back-button indicator when active_idx == n (outside bars range)
    if active_idx == n:
        draw.rectangle((W // 4, lbl_y - 2, 3 * W // 4, lbl_y + 14),
                       fill=(60, 0, 120), outline=(160, 70, 255))
        draw.text((W // 2 - 22, lbl_y), '< Volver', font=FONT_SM,
                  fill=(255, 150, 255))


def draw_menu_screen():
    img  = Image.new('RGB', (W, H), (0, 5, 20))
    draw = ImageDraw.Draw(img)

    # ── Header bar (compact) ──────────────────────────────────────────────────
    draw.rectangle((0, 0, W, 22), fill=(25, 0, 60))
    draw.text((8, 3), 'MENU', font=FONT_MD, fill=(200, 100, 255))
    draw.text((W - 70, 4), menu.estado, font=FONT_SM, fill=(150, 100, 220))
    draw.line([(0, 23), (W, 23)], fill=(80, 30, 140))

    st = menu.estado

    if st == "EQ":
        # ── 3 vertical bars: Low / Mid / High ─────────────────────────────────
        _draw_param_bars(draw, menu._eq_n, menu.eq, menu.idx_eq,
                         [(80, 150, 255), (100, 255, 100), (255, 120, 80)])

    elif st == "ADSR":
        # ── 4 vertical bars: A / D / S / R ────────────────────────────────────
        _draw_param_bars(draw, menu._adsr_n, menu.adsr, menu.idx_adsr,
                         [(255, 80, 80), (255, 180, 0), (80, 220, 80), (80, 180, 255)])

    elif menu.editing:
        # ── Edit mode for REV / DLY / DST (big bar) ───────────────────────────
        cfg = {
            'REV': (menu._rev_n[menu.idx_rev],   menu.reverb[menu.idx_rev]),
            'DLY': (menu._dly_n[menu.idx_dly],   menu.delay[menu.idx_dly]),
            'DST': (menu._dst_n[menu.idx_dst],   menu.dist[menu.idx_dst]),
        }
        name, val = cfg.get(st, ('?', 0))
        draw.text((10, 28), name, font=FONT_BG, fill=(255, 220, 0))
        draw.text((W - 55, 28), str(val), font=FONT_BG, fill=(255, 220, 0))
        _bar(draw, 8, 65, W - 16, 32, val / 16, (255, 200, 0))
        filled = round(val / 16 * 22)
        draw.text((10, 108), '█' * filled + '░' * (22 - filled),
                  font=FONT_SM, fill=(255, 180, 0))

    else:
        # ── Navigation mode: 3 items ──────────────────────────────────────────
        prev, active, nxt = menu.get_three_lines()

        draw.rectangle((0, 24, W, 55), fill=(8, 5, 20))
        draw.text((14, 27), prev[:22], font=FONT_MD, fill=(90, 80, 120))

        draw.rectangle((0, 56, W, 107), fill=(40, 0, 90))
        draw.line([(0, 56), (W, 56)], fill=(100, 40, 180))
        draw.line([(0, 107), (W, 107)], fill=(100, 40, 180))
        draw.text((14, 61), active[:20], font=FONT_LG, fill=(255, 255, 80))

        draw.rectangle((0, 108, W, H - 20), fill=(8, 5, 20))
        draw.text((14, 111), nxt[:22], font=FONT_MD, fill=(90, 80, 120))

    # ── Bottom bar ────────────────────────────────────────────────────────────
    draw.rectangle((0, H - 19, W, H), fill=(20, 0, 50))
    draw.text((8, H - 16), 'OCT▲+OCT▼ = cerrar', font=FONT_SM,
              fill=(160, 70, 255))

    disp.image(img)

# ── Audio stream ───────────────────────────────────────────────────────────────
stream = sd.OutputStream(samplerate=SR, channels=2, dtype='float32',
                          blocksize=BLOCK, callback=callback, device=1)
stream.start()

# Boot screen
boot = Image.new('RGB', (W, H), (0, 10, 30))
bd   = ImageDraw.Draw(boot)
bd.text((60, 65),  'ToF Synth',   font=FONT_LG, fill=(0, 200, 255))
bd.text((100, 105),'starting...', font=FONT_SM, fill=(80,80,80))
disp.image(boot)
time.sleep(1)

# ── Main loop ──────────────────────────────────────────────────────────────────
dist_suav   = 8000.0
prev_steps  = encoder.steps
frame_cnt   = 0
prev_both   = False
prev_oct_up = False
prev_oct_dn = False
prev_enc    = False

print("=== ToF Synth ===  OCT▲+OCT▼ = menu  |  Ctrl+C = exit")

try:
    while True:
        now_oct_up = btn_octup.is_pressed
        now_oct_dn = btn_octdn.is_pressed
        now_enc    = btn_enc.is_pressed
        both_oct   = now_oct_up and now_oct_dn

        # ── Both OCT: toggle menu ────────────────────────────────────────────
        if both_oct and not prev_both:
            in_menu = not in_menu
            if in_menu:
                menu.estado = "MAIN"   # always start at top
        prev_both = both_oct

        # ── Encoder press ────────────────────────────────────────────────────
        if now_enc and not prev_enc:
            if in_menu:
                menu.press()
            else:
                mode_idx = (mode_idx + 1) % len(MODES)
        prev_enc = now_enc

        # ── Encoder rotation ─────────────────────────────────────────────────
        steps = encoder.steps
        delta = steps - prev_steps
        prev_steps = steps
        if delta:
            if in_menu:
                menu.rotate(-delta)   # CW = scroll down
            else:
                m = MODES[mode_idx]
                mode_vals[m] = max(0.0, min(1.0, mode_vals[m] - delta * 0.09))

        # ── Octave (only when not in both-OCT context) ───────────────────────
        if not both_oct:
            if now_oct_up and not prev_oct_up and not in_menu:
                octave = min(OCT_MAX, octave + 1)
            if now_oct_dn and not prev_oct_dn and not in_menu:
                octave = max(OCT_MIN, octave - 1)
        prev_oct_up = now_oct_up
        prev_oct_dn = now_oct_dn

        # ── Sensor ───────────────────────────────────────────────────────────
        if sensor is not None:
            try:
                raw = sensor.range
                raw = 8000 if raw > 1500 else raw
                dist_suav = dist_suav * 0.7 + raw * 0.3
                depth = max(0.0, 1.0 - dist_suav / 450.0) if dist_suav < 450 else 0.0
            except Exception:
                depth = 0.0
        else:
            depth = 0.0

        # ── Pull menu params into synth ───────────────────────────────────────
        with lock:
            synth['trem_depth'] = depth
            synth['morph']      = mode_vals['MORPH']
            synth['saturation'] = mode_vals['SATURATION']
            synth['filt']       = mode_vals['FILTER']
            synth['inst']       = menu.get_current_instrument()
            synth['adsr']       = menu.get_adsr_normalized()
            synth['eq']         = menu.get_eq_normalized()
            synth['reverb']     = menu.get_reverb()
            synth['delay']      = menu.get_delay()
            synth['dist']       = menu.get_distortion()
            # Clean up silent voices
            synth['voices'] = {g: v for g, v in synth['voices'].items()
                               if v['on'] or v['env_amp'] > 0.001}
            active_gpios = {g for g, v in synth['voices'].items()
                            if v['on'] or v['env_amp'] > 0.05}

        active_notes = set(scale_note_names()[i]
                           for i, g in enumerate(BUTTON_GPIOS) if g in active_gpios)

        # ── Screen refresh ~10 fps ────────────────────────────────────────────
        frame_cnt += 1
        if frame_cnt >= 5:
            frame_cnt = 0
            try:
                if in_menu:
                    draw_menu_screen()
                else:
                    scale_name, _ = menu.get_current_scale()
                    draw_synth(MODES[mode_idx], mode_vals, depth, dist_suav,
                               active_notes, octave,
                               menu.get_current_instrument(), scale_name)
            except Exception:
                pass

        time.sleep(0.02)

except KeyboardInterrupt:
    print("\n[Closing...]")
    stream.stop()
    stream.close()
