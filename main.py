import time
import threading
import board
import busio
import adafruit_vl53l0x
import numpy as np
import sounddevice as sd
import soundfile as sf
import RPi.GPIO as GPIO
from luma.core.interface.serial import i2c as luma_i2c
from luma.oled.device import sh1106
from luma.core.render import canvas
from PIL import ImageFont

# ── PINES ──────────────────────────────────────────────────────────────────
PIN_A    = 27   # Encoder A
PIN_B    = 22   # Encoder B
PIN_BTN  = 23   # Botón enter
PIN_DOWN = 24   # Botón bajar menú
PIN_EC11 = 25   # EC11 pin D (enter)
BTN_PINS = [5, 6, 26]  # Botones acorde: 1ª, 3ª, 5ª

# ── AUDIO ──────────────────────────────────────────────────────────────────
SR        = 44100
BLOCK     = 512
FREQ_BASE = 261.63                  # Do (C4)
CHORD     = [1.0, 5/4, 3/2]        # grados 1-3-5 del acorde mayor

# ── PANTALLA ───────────────────────────────────────────────────────────────
OLED_ADDR = 0x3C
W, H      = 128, 64
LINE_H    = 13
VISIBLE   = H // LINE_H

try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 11)
except OSError:
    FONT = ImageFont.load_default()


class ArpaMain:

    # ── INIT ────────────────────────────────────────────────────────────────
    def __init__(self):
        # Parámetros de audio (lock para seguridad entre threads)
        self._lock   = threading.Lock()
        self._params = {'adsr': [2, 4, 6, 3], 'osc': 'SINE', 'reverb': 10}

        # Voz del sensor — glide continuo
        self._sv_phase  = 0.0
        self._sv_freq_c = FREQ_BASE
        self._sv_freq_t = FREQ_BASE
        self._sv_vol_c  = 0.0
        self._sv_vol_t  = 0.0

        # Voces de botones acorde (3 tonos) — ADSR completo
        self._bv = [
            {'phase': 0.0, 'stage': 'off', 'env': 0.0, 'pt': 0.0, 'renv': 0.0}
            for _ in range(3)
        ]
        self._note_q    = []   # cola de eventos note-on/off (thread-safe)
        self._note_lock = threading.Lock()

        # Reverb
        rl = int(0.08 * SR)
        self._rev_buf = np.zeros(rl, dtype=np.float32)
        self._rev_pos = 0
        self._rev_len = rl

        # Grabación
        self._rec = []

        # Sensor VL53L0X en hilo propio (bloquea ~20 ms por lectura)
        self._running = True
        i2c = busio.I2C(board.SCL, board.SDA)
        self._sensor = adafruit_vl53l0x.VL53L0X(i2c)
        self._sensor.measurement_timing_budget = 20000
        threading.Thread(target=self._sensor_loop, daemon=True).start()
        print("Sensor listo.")

        # Stream de audio
        self._stream = sd.OutputStream(
            samplerate=SR, channels=1, blocksize=BLOCK,
            dtype='float32', callback=self._audio_cb
        )
        self._stream.start()

        # OLED
        serial   = luma_i2c(port=1, address=OLED_ADDR)
        self.dev = sh1106(serial, rotate=0)

        # Estado del menú
        self.menu_tree = {
            "INSTRUMENT": ["Change Type", "Visual ADSR", "Back"],
            "MIXING":     ["Visual EQ", "Compressor", "Limiter", "Back"],
            "EFFECTS":    ["Reverb", "Delay", "Distortion", "Back"],
            "CONFIG":     ["MIDI Channel", "Calibration", "Back"],
        }
        self.state        = "MENU"
        self.current_path = []
        self.cursor_pos   = 0
        self.scroll_off   = 0

        self.adsr_vals    = [2, 4, 6, 3]
        self.adsr_stage   = 0
        self.adsr_names   = ["ATTACK", "DECAY", "SUSTAIN", "RELEASE"]
        self.eq_vals      = [5, 2, 6]
        self.eq_band      = 0
        self.fx_val       = 10
        self.osc_types    = ["SINE", "SAW", "SQUARE", "TRIANGLE"]
        self.osc_index    = 0
        self.comp_vals    = [4, 2]
        self.comp_stage   = 0
        self.lim_val      = 6
        self.delay_vals   = [2, 3]
        self.delay_stage  = 0
        self.dist_val     = 2
        self.midi_channel = 1
        self.calib_step   = 0

        # GPIO
        GPIO.setmode(GPIO.BCM)
        for pin in [PIN_A, PIN_B, PIN_BTN, PIN_DOWN, PIN_EC11] + BTN_PINS:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self._prev_a    = bool(GPIO.input(PIN_A))
        self._prev_btn  = True
        self._prev_down = True
        self._prev_ec11 = True
        self._prev_btns = [True] * 3
        self._t_enc     = 0.0

    # ── SENSOR THREAD ───────────────────────────────────────────────────────
    def _sensor_loop(self):
        while self._running:
            try:
                dist = self._sensor.range
                if dist < 500:
                    self._sv_vol_t  = 1.0
                    self._sv_freq_t = FREQ_BASE * (1.0 + dist / 500.0)
                else:
                    self._sv_vol_t  = 0.0
                    self._sv_freq_t = FREQ_BASE
            except Exception:
                pass

    # ── AUDIO CALLBACK ──────────────────────────────────────────────────────
    def _audio_cb(self, outdata, frames, time_info, status):
        with self._lock:
            p = dict(self._params)

        # Procesar eventos note-on/off pendientes
        with self._note_lock:
            events, self._note_q = self._note_q[:], []
        for idx, action in events:
            bv = self._bv[idx]
            if action == 'on':
                bv['stage'] = 'attack'; bv['pt'] = 0.0; bv['env'] = 0.0
            elif bv['stage'] not in ('off', 'release'):
                bv['renv'] = bv['env']; bv['stage'] = 'release'; bv['pt'] = 0.0

        t   = np.arange(frames, dtype=np.float64) / SR
        mix = np.zeros(frames, dtype=np.float32)

        # Voz sensor — glide + envolvente suave
        self._sv_freq_c += (self._sv_freq_t - self._sv_freq_c) * 0.15
        vv = 0.3 if self._sv_vol_t > self._sv_vol_c else 0.2
        self._sv_vol_c  += (self._sv_vol_t - self._sv_vol_c) * vv
        if self._sv_vol_c < 0.001:
            self._sv_vol_c = 0.0
        mix += self._wave(p['osc'], 2*np.pi*self._sv_freq_c*t + self._sv_phase) * self._sv_vol_c
        self._sv_phase = (self._sv_phase + 2*np.pi*self._sv_freq_c*frames/SR) % (2*np.pi)

        # Voces acorde — ADSR
        att = self._map(p['adsr'][0], 0.01, 2.0)
        dec = self._map(p['adsr'][1], 0.01, 2.0)
        sus = self._map(p['adsr'][2], 0.0,  1.0)
        rel = self._map(p['adsr'][3], 0.01, 3.0)

        for i, bv in enumerate(self._bv):
            if bv['stage'] == 'off':
                continue
            freq = FREQ_BASE * CHORD[i]
            env  = self._adsr_block(bv, att, dec, sus, rel, frames)
            mix += self._wave(p['osc'], 2*np.pi*freq*t + bv['phase']) * env
            bv['phase'] = (bv['phase'] + 2*np.pi*freq*frames/SR) % (2*np.pi)

        # Reverb
        if p['reverb'] > 0:
            mix = self._reverb(mix, p['reverb'] / 16.0)

        outdata[:, 0] = np.tanh(mix * 0.3)
        self._rec.append(outdata[:, 0].copy())

    # ── AUDIO HELPERS ───────────────────────────────────────────────────────
    def _wave(self, osc, t):
        if osc == 'SINE':   return np.sin(t).astype(np.float32)
        if osc == 'SAW':    return (2*(t/(2*np.pi) % 1) - 1).astype(np.float32)
        if osc == 'SQUARE': return np.sign(np.sin(t)).astype(np.float32)
        p = t / (2*np.pi) % 1
        return (2*np.abs(2*p - 1) - 1).astype(np.float32)

    @staticmethod
    def _map(v, lo, hi): return lo + (hi - lo) * v / 7.0

    def _adsr_block(self, bv, att, dec, sus, rel, frames):
        t0, s = bv['pt'], np.arange(frames, dtype=np.float64) / SR
        stg   = bv['stage']
        if stg == 'attack':
            env = np.clip((t0 + s) / att, 0, 1) if att > 0 else np.ones(frames)
            new_t = t0 + frames / SR
            bv['stage'], bv['pt'] = ('decay', new_t - att) if new_t >= att else ('attack', new_t)
        elif stg == 'decay':
            env = 1.0 - (1.0 - sus) * np.clip((t0 + s) / dec, 0, 1) if dec > 0 else np.full(frames, sus)
            new_t = t0 + frames / SR
            bv['stage'], bv['pt'] = ('sustain', 0.0) if new_t >= dec else ('decay', new_t)
        elif stg == 'sustain':
            env = np.full(frames, sus); bv['pt'] = t0 + frames / SR
        elif stg == 'release':
            env = bv['renv'] * np.clip(1 - (t0 + s) / rel, 0, 1) if rel > 0 else np.zeros(frames)
            new_t = t0 + frames / SR
            if new_t >= rel:
                bv['stage'] = 'off'; bv['pt'] = bv['env'] = 0.0
            else:
                bv['pt'] = new_t
        else:
            return np.zeros(frames, dtype=np.float32)
        bv['env'] = float(env[-1])
        return env.astype(np.float32)

    def _reverb(self, block, wet):
        n, pos = len(block), self._rev_pos
        end    = pos + n
        if end <= self._rev_len:
            delayed = self._rev_buf[pos:end].copy()
            self._rev_buf[pos:end] = block + delayed * 0.4
        else:
            sp = self._rev_len - pos
            delayed = np.concatenate([self._rev_buf[pos:].copy(), self._rev_buf[:n-sp].copy()])
            self._rev_buf[pos:]    = block[:sp]   + self._rev_buf[pos:]    * 0.4
            self._rev_buf[:n-sp]   = block[sp:]   + self._rev_buf[:n-sp]  * 0.4
        self._rev_pos = end % self._rev_len
        return (block * (1 - wet) + delayed * wet).astype(np.float32)

    def note_on(self, i):
        with self._note_lock:
            self._note_q.append((i, 'on'))

    def note_off(self, i):
        with self._note_lock:
            self._note_q.append((i, 'off'))

    def _sync_params(self):
        with self._lock:
            self._params = {
                'adsr':   list(self.adsr_vals),
                'osc':    self.osc_types[self.osc_index],
                'reverb': self.fx_val,
            }

    # ── BUCLE PRINCIPAL ─────────────────────────────────────────────────────
    def run(self):
        self.render()
        print("ArpaLaser activa. Ctrl+C para guardar y salir.")
        try:
            while True:
                now = time.time()

                # Encoder
                curr_a = bool(GPIO.input(PIN_A))
                if not curr_a and self._prev_a and (now - self._t_enc) > 0.012:
                    self._t_enc = now
                    self.rotate(1 if GPIO.input(PIN_B) else -1)
                self._prev_a = curr_a

                # Botones de menú
                curr_btn  = bool(GPIO.input(PIN_BTN))
                curr_down = bool(GPIO.input(PIN_DOWN))
                curr_ec11 = bool(GPIO.input(PIN_EC11))
                if not curr_down and self._prev_down: self.rotate(1)
                if not curr_btn  and self._prev_btn:  self.press()
                if not curr_ec11 and self._prev_ec11: self.press()
                self._prev_btn  = curr_btn
                self._prev_down = curr_down
                self._prev_ec11 = curr_ec11

                # Botones acorde (5 → raíz, 6 → 3ª, 26 → 5ª)
                for i, pin in enumerate(BTN_PINS):
                    curr = bool(GPIO.input(pin))
                    if not curr and self._prev_btns[i]:  self.note_on(i)
                    elif curr and not self._prev_btns[i]: self.note_off(i)
                    self._prev_btns[i] = curr

                time.sleep(0.005)

        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            self._stream.stop()
            print("\nGuardando grabación...")
            if self._rec:
                sf.write('grabacion_arpa.wav', np.concatenate(self._rec), SR)
                print("Guardado: grabacion_arpa.wav")
            self.dev.cleanup()
            GPIO.cleanup()

    # ── RENDER ──────────────────────────────────────────────────────────────
    def render(self):
        fn = {
            "MENU":            self.draw_menu,
            "EDIT_ADSR":       self.draw_adsr,
            "EDIT_EQ":         self.draw_eq,
            "EDIT_FX":         self.draw_fx,
            "EDIT_INSTRUMENT": self.draw_instrument,
            "EDIT_COMP":       self.draw_comp,
            "EDIT_LIM":        self.draw_lim,
            "EDIT_DELAY":      self.draw_delay,
            "EDIT_DIST":       self.draw_dist,
            "EDIT_MIDI":       self.draw_midi,
            "EDIT_CALIB":      self.draw_calib,
        }.get(self.state)
        if fn:
            try: fn()
            except Exception as e: print(f"ERROR render [{self.state}]: {e}")

    def _rows(self, draw, rows):
        for i, (text, sel) in enumerate(rows):
            y = i * LINE_H
            if sel:
                draw.rectangle([(0, y), (W-1, y+LINE_H-1)], fill="white")
                draw.text((2, y+1), text, font=FONT, fill="black")
            else:
                draw.text((2, y+1), text, font=FONT, fill="white")

    def draw_menu(self):
        opts = self._options()
        rows = []
        for i in range(VISIBLE):
            idx = self.scroll_off + i
            if idx >= len(opts): break
            rows.append(((">" if idx == self.cursor_pos else " ") + opts[idx],
                         idx == self.cursor_pos))
        with canvas(self.dev) as draw:
            self._rows(draw, rows)

    def _vbar(self, draw, x, bot, bw, bh, value, max_val, active=False):
        fill_h = int(bh * value / max_val)
        draw.rectangle([(x, bot-bh), (x+bw, bot)], outline="white")
        if fill_h > 0:
            draw.rectangle([(x+1, bot-fill_h), (x+bw-1, bot)], fill="white")
        if active:
            draw.rectangle([(x-1, bot-bh-3), (x+bw+1, bot-bh-1)], fill="white")

    def draw_adsr(self):
        bw, bh = 22, 40
        sp = (W - 4*bw) // 5
        with canvas(self.dev) as draw:
            draw.text((0, 0), f"ADSR:{self.adsr_names[self.adsr_stage]}", font=FONT, fill="white")
            for i, v in enumerate(self.adsr_vals):
                x = sp + i*(bw+sp)
                self._vbar(draw, x, H-2, bw, bh, v, 7, active=(i==self.adsr_stage))
                draw.text((x+bw//2-3, H-2-bh-11), "ADSR"[i], font=FONT, fill="white")

    def draw_eq(self):
        bw, bh = 28, 40
        sp = (W - 3*bw) // 4
        labels = ["LOW", "MID", "HI"]
        with canvas(self.dev) as draw:
            draw.text((0, 0), "ECUALIZADOR", font=FONT, fill="white")
            for i, v in enumerate(self.eq_vals):
                x, sel = sp + i*(bw+sp), i == self.eq_band
                self._vbar(draw, x, H-2, bw, bh, v, 7, active=sel)
                lx, ly = x+bw//2-len(labels[i])*3, H-2-bh-12
                if sel:
                    draw.rectangle([(lx-1, ly-1), (lx+len(labels[i])*6, ly+10)], fill="white")
                    draw.text((lx, ly), labels[i], font=FONT, fill="black")
                else:
                    draw.text((lx, ly), labels[i], font=FONT, fill="white")

    def _hbar(self, draw, value, max_val, title):
        draw.text((0, 0), title, font=FONT, fill="white")
        by, bh = LINE_H+6, 14
        fw = int((W-4) * value / max_val)
        draw.rectangle([(2, by), (W-2, by+bh)], outline="white")
        if fw > 0: draw.rectangle([(3, by+1), (2+fw, by+bh-1)], fill="white")
        draw.text((0, by+bh+4), f"{value} / {max_val}", font=FONT, fill="white")

    def draw_fx(self):
        with canvas(self.dev) as draw: self._hbar(draw, self.fx_val, 16, "REVERB MIX")

    def draw_instrument(self):
        with canvas(self.dev) as draw:
            draw.text((0, 5),  f"OSC {self.osc_index+1}/{len(self.osc_types)}", font=FONT, fill="white")
            draw.text((0, 30), f"> {self.osc_types[self.osc_index]}", font=FONT, fill="white")

    def _two_vbars(self, draw, title, values, labels, active_idx):
        bw, bh = 46, 38
        draw.text((0, 0), title, font=FONT, fill="white")
        for i, v in enumerate(values):
            x, sel = 10 + i*(bw+20), i == active_idx
            self._vbar(draw, x, H-2, bw, bh, v, 7, active=sel)
            lx, ly = x+bw//2-len(labels[i])*3, H-2-bh-12
            if sel:
                draw.rectangle([(lx-1, ly-1), (lx+len(labels[i])*6, ly+10)], fill="white")
                draw.text((lx, ly), labels[i], font=FONT, fill="black")
            else:
                draw.text((lx, ly), labels[i], font=FONT, fill="white")

    def draw_comp(self):
        with canvas(self.dev) as draw:
            self._two_vbars(draw, "COMPRESOR", self.comp_vals, ["UMBRAL", "RATIO"], self.comp_stage)

    def draw_lim(self):
        with canvas(self.dev) as draw: self._hbar(draw, self.lim_val, 7, "LIMITADOR")

    def draw_delay(self):
        with canvas(self.dev) as draw:
            self._two_vbars(draw, "DELAY", self.delay_vals, ["TIEMPO", "FEEDBK"], self.delay_stage)

    def draw_dist(self):
        with canvas(self.dev) as draw: self._hbar(draw, self.dist_val, 7, "DISTORSION")

    def draw_midi(self):
        ch = f"CH {self.midi_channel:02d}"
        with canvas(self.dev) as draw:
            draw.text((0, 10), "CANAL MIDI", font=FONT, fill="white")
            draw.text((W//2 - len(ch)*4, 35), ch, font=FONT, fill="white")

    def draw_calib(self):
        msgs = [("CALIBRACION", "Pulsar=INICIAR"), ("CALIBRANDO...", "Espere..."), ("CALIBRADO!", "Pulsar=SALIR")]
        l1, l2 = msgs[self.calib_step]
        with canvas(self.dev) as draw:
            draw.text((0, 10), l1, font=FONT, fill="white")
            draw.text((0, 32), l2, font=FONT, fill="white")

    # ── LÓGICA DE MENÚ ──────────────────────────────────────────────────────
    def rotate(self, direction):
        if self.state == "MENU":
            opts = self._options()
            self.cursor_pos = (self.cursor_pos + direction) % len(opts)
            if self.cursor_pos < self.scroll_off:
                self.scroll_off = self.cursor_pos
            elif self.cursor_pos >= self.scroll_off + VISIBLE:
                self.scroll_off = self.cursor_pos - VISIBLE + 1
            if self.cursor_pos == 0: self.scroll_off = 0
        elif self.state == "EDIT_ADSR":
            self.adsr_vals[self.adsr_stage] = max(0, min(7, self.adsr_vals[self.adsr_stage] - direction))
            self._sync_params()
        elif self.state == "EDIT_EQ":
            self.eq_vals[self.eq_band] = max(0, min(7, self.eq_vals[self.eq_band] - direction))
        elif self.state == "EDIT_FX":
            self.fx_val = max(0, min(16, self.fx_val - direction))
            self._sync_params()
        elif self.state == "EDIT_INSTRUMENT":
            self.osc_index = (self.osc_index - direction) % len(self.osc_types)
            self._sync_params()
        elif self.state == "EDIT_COMP":
            self.comp_vals[self.comp_stage] = max(0, min(7, self.comp_vals[self.comp_stage] - direction))
        elif self.state == "EDIT_LIM":
            self.lim_val = max(0, min(7, self.lim_val - direction))
        elif self.state == "EDIT_DELAY":
            self.delay_vals[self.delay_stage] = max(0, min(7, self.delay_vals[self.delay_stage] - direction))
        elif self.state == "EDIT_DIST":
            self.dist_val = max(0, min(7, self.dist_val - direction))
        elif self.state == "EDIT_MIDI":
            self.midi_channel = max(1, min(16, self.midi_channel - direction))
        self.render()

    def press(self):
        if self.state == "MENU":
            sel = self._options()[self.cursor_pos]
            if sel == "Back":
                if self.current_path: self.current_path.pop()
                self.cursor_pos = self.scroll_off = 0
            elif sel == "Visual ADSR":   self.state = "EDIT_ADSR";  self.adsr_stage = 0
            elif sel == "Visual EQ":     self.state = "EDIT_EQ";    self.eq_band = 0
            elif sel == "Reverb":        self.state = "EDIT_FX"
            elif sel == "Change Type":   self.state = "EDIT_INSTRUMENT"
            elif sel == "Compressor":    self.state = "EDIT_COMP";  self.comp_stage = 0
            elif sel == "Limiter":       self.state = "EDIT_LIM"
            elif sel == "Delay":         self.state = "EDIT_DELAY"; self.delay_stage = 0
            elif sel == "Distortion":    self.state = "EDIT_DIST"
            elif sel == "MIDI Channel":  self.state = "EDIT_MIDI"
            elif sel == "Calibration":   self.state = "EDIT_CALIB"; self.calib_step = 0
            elif sel in self.menu_tree:
                self.current_path.append(sel); self.cursor_pos = self.scroll_off = 0
        elif self.state == "EDIT_ADSR":
            self.adsr_stage += 1
            if self.adsr_stage > 3: self.state = "MENU"; self.adsr_stage = 0; self._saved(); return
        elif self.state == "EDIT_EQ":
            self.eq_band += 1
            if self.eq_band > 2: self.state = "MENU"; self.eq_band = 0; self._saved(); return
        elif self.state in ("EDIT_FX", "EDIT_INSTRUMENT", "EDIT_LIM", "EDIT_DIST", "EDIT_MIDI"):
            self.state = "MENU"; self._saved(); return
        elif self.state == "EDIT_COMP":
            self.comp_stage += 1
            if self.comp_stage > 1: self.state = "MENU"; self.comp_stage = 0; self._saved(); return
        elif self.state == "EDIT_DELAY":
            self.delay_stage += 1
            if self.delay_stage > 1: self.state = "MENU"; self.delay_stage = 0; self._saved(); return
        elif self.state == "EDIT_CALIB":
            if self.calib_step == 0:
                self.calib_step = 1; self.render(); time.sleep(1.5); self.calib_step = 2
            elif self.calib_step == 2:
                self.state = "MENU"; self.calib_step = 0
        self.render()

    def _saved(self):
        self._sync_params()
        with canvas(self.dev) as draw:
            draw.text((W//2-36, H//2-8), "GUARDADO!", font=FONT, fill="white")
        time.sleep(0.5)
        self.render()

    def _options(self):
        t = self.menu_tree
        for folder in self.current_path: t = t[folder]
        return list(t.keys()) if isinstance(t, dict) else t


if __name__ == "__main__":
    ArpaMain().run()
