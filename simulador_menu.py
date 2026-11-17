import tkinter as tk
from tkinter import font
import threading

try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

BEAM_FREQS = [261.63, 293.66, 329.63, 349.23, 392.00, 440.00, 493.88, 523.25]  # C4–C5 (escala Do mayor)


class AudioEngine:
    SAMPLE_RATE = 44100
    BLOCK_SIZE  = 512
    MASTER_GAIN = 0.35

    def __init__(self):
        self.enabled = AUDIO_AVAILABLE
        if not self.enabled:
            return
        self.notes = [
            {"phase": "off", "env": 0.0, "phase_t": 0.0, "release_start_env": 0.0}
            for _ in range(8)
        ]
        self.phases = np.zeros(8, dtype=np.float64)
        rev_len = int(0.08 * self.SAMPLE_RATE)   # 80 ms de retardo para el reverb
        self._rev_buf = np.zeros(rev_len, dtype=np.float32)
        self._rev_pos = 0
        self._rev_len = rev_len
        self._params_lock = threading.Lock()
        self._params = {
            "adsr":       [2, 4, 6, 3],
            "osc_type":   "SINE",
            "fx_reverb":  0,
            "eq":         [5, 2, 6],
            "comp_thresh": 4, "comp_ratio": 2,
            "lim_thresh":  6,
            "delay_time":  2, "delay_fb": 3,
            "dist_drive":  2,
        }
        self._stream = sd.OutputStream(
            samplerate=self.SAMPLE_RATE,
            blocksize=self.BLOCK_SIZE,
            channels=1,
            dtype="float32",
            callback=self._audio_callback,
        )
        self._stream.start()

    def stop(self):
        if self.enabled and self._stream.active:
            self._stream.stop()
            self._stream.close()

    def update_params(self, **kwargs):
        if not self.enabled:
            return
        with self._params_lock:
            self._params.update(kwargs)

    def _get_params(self):
        with self._params_lock:
            return dict(self._params)

    @staticmethod
    def _map(val, lo, hi):
        return lo + (hi - lo) * val / 7.0

    @staticmethod
    def _wave(osc_type, t):
        """Genera una forma de onda a partir de un array de ángulos de fase."""
        if osc_type == "SINE":
            return np.sin(t).astype(np.float32)
        if osc_type == "SAW":
            return (2.0 * (t / (2.0 * np.pi) % 1.0) - 1.0).astype(np.float32)
        if osc_type == "SQUARE":
            return np.sign(np.sin(t)).astype(np.float32)
        # TRIANGLE
        p = t / (2.0 * np.pi) % 1.0
        return (2.0 * np.abs(2.0 * p - 1.0) - 1.0).astype(np.float32)

    def _envelope_block(self, note, att, dec, sus, rel, frames):
        """Calcula el array de envelope para `frames` muestras; avanza el estado de la nota."""
        sr  = self.SAMPLE_RATE
        t0  = note["phase_t"]
        s   = np.arange(frames, dtype=np.float64) / sr
        phase = note["phase"]

        if phase == "attack":
            env = np.clip((t0 + s) / att, 0.0, 1.0) if att > 0 else np.ones(frames)
            new_t = t0 + frames / sr
            if new_t >= att:
                note["phase"]   = "decay"
                note["phase_t"] = new_t - att
            else:
                note["phase_t"] = new_t

        elif phase == "decay":
            if dec > 0:
                env = 1.0 - (1.0 - sus) * np.clip((t0 + s) / dec, 0.0, 1.0)
            else:
                env = np.full(frames, sus, dtype=np.float64)
            new_t = t0 + frames / sr
            if new_t >= dec:
                note["phase"]   = "sustain"
                note["phase_t"] = 0.0
            else:
                note["phase_t"] = new_t

        elif phase == "sustain":
            env = np.full(frames, sus, dtype=np.float64)
            note["phase_t"] = t0 + frames / sr

        elif phase == "release":
            start = note["release_start_env"]
            env   = start * np.clip(1.0 - (t0 + s) / rel, 0.0, 1.0) if rel > 0 else np.zeros(frames)
            new_t = t0 + frames / sr
            if new_t >= rel:
                note["phase"]   = "off"
                note["phase_t"] = 0.0
                note["env"]     = 0.0
                return env.astype(np.float32)
            note["phase_t"] = new_t

        else:
            return None

        note["env"] = float(env[-1])
        return env.astype(np.float32)

    def _apply_reverb(self, block, wet):
        """Comb-filter reverb vectorizado (sin bucle Python)."""
        if wet == 0.0:
            return block
        n   = len(block)
        pos = self._rev_pos
        end = pos + n
        if end <= self._rev_len:
            delayed = self._rev_buf[pos:end].copy()
            self._rev_buf[pos:end] = block + delayed * 0.4
        else:
            split   = self._rev_len - pos
            delayed = np.empty(n, dtype=np.float32)
            delayed[:split] = self._rev_buf[pos:].copy()
            delayed[split:] = self._rev_buf[:n - split].copy()
            self._rev_buf[pos:]       = block[:split]  + self._rev_buf[pos:]       * 0.4
            self._rev_buf[:n - split] = block[split:]  + self._rev_buf[:n - split] * 0.4
        self._rev_pos = end % self._rev_len
        return block * (1.0 - wet) + delayed * wet

    def _audio_callback(self, outdata, frames, time_info, status):
        p   = self._get_params()
        att = self._map(p["adsr"][0], 0.01, 2.0)
        dec = self._map(p["adsr"][1], 0.01, 2.0)
        sus = self._map(p["adsr"][2], 0.0,  1.0)
        rel = self._map(p["adsr"][3], 0.01, 3.0)
        wet = p["fx_reverb"] / 16.0
        osc = p["osc_type"]

        mixed = np.zeros(frames, dtype=np.float32)
        tw    = 2.0 * np.pi
        inc   = tw * np.array(BEAM_FREQS, dtype=np.float64) / self.SAMPLE_RATE

        for i, note in enumerate(self.notes):
            if note["phase"] == "off":
                continue
            env = self._envelope_block(note, att, dec, sus, rel, frames)
            if env is None:
                continue
            t = np.arange(frames, dtype=np.float64) * inc[i] + self.phases[i]
            self.phases[i] = (self.phases[i] + frames * inc[i]) % tw
            mixed += self._wave(osc, t) * env

        mixed = np.tanh(mixed * self.MASTER_GAIN)
        mixed = self._apply_reverb(mixed, wet)
        outdata[:, 0] = mixed

    def note_on(self, idx):
        if not self.enabled:
            return
        n = self.notes[idx]
        n["phase"]   = "attack"
        n["phase_t"] = 0.0
        n["env"]     = 0.0

    def note_off(self, idx):
        if not self.enabled:
            return
        n = self.notes[idx]
        if n["phase"] not in ("off", "release"):
            n["release_start_env"] = n["env"]
            n["phase"]             = "release"
            n["phase_t"]           = 0.0


class ArpaLaserVisualOS:
    def __init__(self, root):
        self.root = root
        self.root.title("Laser Harp OS v2.0 - Visual Editors")
        self.root.geometry("650x510")
        self.root.configure(bg="#0a0a0a")

        # --- ESTRUCTURA DEL MENÚ ---
        self.menu_tree = {
            "INSTRUMENT": ["Change Type", "Visual ADSR", "Back"],
            "MIXING":     ["Visual EQ (3-Band)", "Compressor", "Limiter", "Back"],
            "EFFECTS":    ["Reverb Knobs", "Delay", "Distortion", "Back"],
            "CONFIG":     ["MIDI Channel", "Calibration", "Back"],
        }

        # --- MÁQUINA DE ESTADOS ---
        # MENU | EDIT_ADSR | EDIT_EQ | EDIT_FX | EDIT_INSTRUMENT |
        # EDIT_COMP | EDIT_LIM | EDIT_DELAY | EDIT_DIST | EDIT_MIDI | EDIT_CALIB
        self.state = "MENU"

        # --- NAVEGACIÓN ---
        self.current_path        = []
        self.current_folder_name = "MAIN"
        self.cursor_pos          = 0
        self.scroll_offset       = 0
        self.get_current_options()

        # --- EDITORES VISUALES ---
        self.bars       = [' ', '▂', '▃', '▄', '▅', '▆', '▇', '█']
        self.adsr_vals  = [2, 4, 6, 3]
        self.adsr_stage = 0
        self.adsr_names = ["ATTACK", "DECAY", "SUSTAIN", "RELEASE"]
        self.eq_vals    = [5, 2, 6]
        self.eq_band    = 0
        self.fx_val     = 10   # 0–16

        # --- NUEVOS EDITORES ---
        self.active_beams  = [False] * 8
        self.osc_types     = ["SINE", "SAW", "SQUARE", "TRIANGLE"]
        self.osc_index     = 0
        self.comp_vals     = [4, 2]   # [umbral 0-7, ratio 0-7]
        self.comp_stage    = 0
        self.lim_val       = 6        # 0–7
        self.delay_vals    = [2, 3]   # [tiempo 0-7, feedback 0-7]
        self.delay_stage   = 0
        self.dist_val      = 2        # 0–7
        self.midi_channel  = 1        # 1–16
        self.calib_step    = 0        # 0=idle 1=running 2=done

        # --- MOTOR DE AUDIO ---
        self.audio = AudioEngine()

        # --- UI ---
        self.lcd_font = font.Font(family="Courier New", size=28, weight="bold")
        frame = tk.Frame(root, bg="#1a1a1a", bd=10, relief="sunken")
        frame.pack(pady=30)
        self.line1 = tk.Label(frame, text="", font=self.lcd_font,
                              bg="#ffb000", fg="#2b1d00", width=16, anchor="w")
        self.line1.pack()
        self.line2 = tk.Label(frame, text="", font=self.lcd_font,
                              bg="#ffb000", fg="#2b1d00", width=16, anchor="w")
        self.line2.pack()

        info_txt = (
            "MENÚ: ↑/↓ Navegar  |  ENTER Entrar\n"
            "EDICIÓN: ↑/↓ Valor  |  ENTER Siguiente/Salir\n"
            "BEAMS (notas): teclas 1–8 (mantener = nota sostenida)"
        )
        tk.Label(root, text=info_txt, bg="#0a0a0a", fg="#aaa",
                 font=("Arial", 10)).pack(pady=12)

        # Bindings de navegación
        root.bind("<Up>",     lambda e: self.rotate_knob(-1))
        root.bind("<Left>",   lambda e: self.rotate_knob(-1))
        root.bind("<Down>",   lambda e: self.rotate_knob(1))
        root.bind("<Right>",  lambda e: self.rotate_knob(1))
        root.bind("<Return>", lambda e: self.press_knob())

        # Bindings de beams (teclas 1–8)
        for i, k in enumerate("12345678"):
            root.bind(f"<KeyPress-{k}>",   lambda e, idx=i: self._beam_on(idx))
            root.bind(f"<KeyRelease-{k}>", lambda e, idx=i: self._beam_off(idx))

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.update_display()

    # ------------------------------------------------------------------ #
    #  CICLO DE VIDA                                                       #
    # ------------------------------------------------------------------ #

    def _on_close(self):
        self.audio.stop()
        self.root.destroy()

    # ------------------------------------------------------------------ #
    #  BEAMS                                                               #
    # ------------------------------------------------------------------ #

    def _beam_on(self, idx):
        if self.active_beams[idx]:
            return   # ignorar key-repeat de Windows
        self.active_beams[idx] = True
        self.audio.note_on(idx)
        if self.state == "MENU":
            self.update_display()

    def _beam_off(self, idx):
        self.active_beams[idx] = False
        self.audio.note_off(idx)
        if self.state == "MENU":
            self.update_display()

    # ------------------------------------------------------------------ #
    #  ENCODER ROTATIVO                                                    #
    # ------------------------------------------------------------------ #

    def rotate_knob(self, direction):
        if self.state == "MENU":
            self.cursor_pos = (self.cursor_pos + direction) % len(self.current_options)
            if self.cursor_pos < self.scroll_offset:
                self.scroll_offset = self.cursor_pos
            elif self.cursor_pos >= self.scroll_offset + 2:
                self.scroll_offset = self.cursor_pos - 1
            if self.cursor_pos == 0:
                self.scroll_offset = 0

        elif self.state == "EDIT_ADSR":
            self.adsr_vals[self.adsr_stage] = max(0, min(7, self.adsr_vals[self.adsr_stage] - direction))
            self.audio.update_params(adsr=list(self.adsr_vals))

        elif self.state == "EDIT_EQ":
            self.eq_vals[self.eq_band] = max(0, min(7, self.eq_vals[self.eq_band] - direction))
            self.audio.update_params(eq=list(self.eq_vals))

        elif self.state == "EDIT_FX":
            self.fx_val = max(0, min(16, self.fx_val - direction))
            self.audio.update_params(fx_reverb=self.fx_val)

        elif self.state == "EDIT_INSTRUMENT":
            self.osc_index = (self.osc_index - direction) % len(self.osc_types)
            self.audio.update_params(osc_type=self.osc_types[self.osc_index])

        elif self.state == "EDIT_COMP":
            self.comp_vals[self.comp_stage] = max(0, min(7, self.comp_vals[self.comp_stage] - direction))
            self.audio.update_params(comp_thresh=self.comp_vals[0], comp_ratio=self.comp_vals[1])

        elif self.state == "EDIT_LIM":
            self.lim_val = max(0, min(7, self.lim_val - direction))
            self.audio.update_params(lim_thresh=self.lim_val)

        elif self.state == "EDIT_DELAY":
            self.delay_vals[self.delay_stage] = max(0, min(7, self.delay_vals[self.delay_stage] - direction))
            self.audio.update_params(delay_time=self.delay_vals[0], delay_fb=self.delay_vals[1])

        elif self.state == "EDIT_DIST":
            self.dist_val = max(0, min(7, self.dist_val - direction))
            self.audio.update_params(dist_drive=self.dist_val)

        elif self.state == "EDIT_MIDI":
            self.midi_channel = max(1, min(16, self.midi_channel - direction))

        # EDIT_CALIB: no-op

        self.update_display()

    # ------------------------------------------------------------------ #
    #  CLICK DEL ENCODER                                                   #
    # ------------------------------------------------------------------ #

    def press_knob(self):
        if self.state == "MENU":
            selected = self.current_options[self.cursor_pos]
            if selected == "Back":
                if self.current_path:
                    self.current_path.pop()
                    self.current_folder_name = self.current_path[-1] if self.current_path else "MAIN"
                    self.reset_nav()
            elif selected == "Visual ADSR":
                self.state = "EDIT_ADSR";       self.adsr_stage = 0
            elif selected == "Visual EQ (3-Band)":
                self.state = "EDIT_EQ";         self.eq_band = 0
            elif selected == "Reverb Knobs":
                self.state = "EDIT_FX"
            elif selected == "Change Type":
                self.state = "EDIT_INSTRUMENT"
            elif selected == "Compressor":
                self.state = "EDIT_COMP";       self.comp_stage = 0
            elif selected == "Limiter":
                self.state = "EDIT_LIM"
            elif selected == "Delay":
                self.state = "EDIT_DELAY";      self.delay_stage = 0
            elif selected == "Distortion":
                self.state = "EDIT_DIST"
            elif selected == "MIDI Channel":
                self.state = "EDIT_MIDI"
            elif selected == "Calibration":
                self.state = "EDIT_CALIB";      self.calib_step = 0
            elif isinstance(self.get_target(), dict) and (
                isinstance(self.get_target().get(selected), (dict, list))
            ):
                self.current_path.append(selected)
                self.current_folder_name = selected
                self.reset_nav()

        elif self.state == "EDIT_ADSR":
            self.adsr_stage += 1
            if self.adsr_stage > 3:
                self.state = "MENU";  self.adsr_stage = 0
                self.flash_feedback("GUARDADO!")
                return

        elif self.state == "EDIT_EQ":
            self.eq_band += 1
            if self.eq_band > 2:
                self.state = "MENU";  self.eq_band = 0
                self.flash_feedback("GUARDADO!")
                return

        elif self.state == "EDIT_FX":
            self.state = "MENU"
            self.flash_feedback("GUARDADO!")
            return

        elif self.state == "EDIT_INSTRUMENT":
            self.state = "MENU"
            self.flash_feedback("GUARDADO!")
            return

        elif self.state == "EDIT_COMP":
            self.comp_stage += 1
            if self.comp_stage > 1:
                self.state = "MENU";  self.comp_stage = 0
                self.flash_feedback("GUARDADO!")
                return

        elif self.state == "EDIT_LIM":
            self.state = "MENU"
            self.flash_feedback("GUARDADO!")
            return

        elif self.state == "EDIT_DELAY":
            self.delay_stage += 1
            if self.delay_stage > 1:
                self.state = "MENU";  self.delay_stage = 0
                self.flash_feedback("GUARDADO!")
                return

        elif self.state == "EDIT_DIST":
            self.state = "MENU"
            self.flash_feedback("GUARDADO!")
            return

        elif self.state == "EDIT_MIDI":
            self.state = "MENU"
            self.flash_feedback("GUARDADO!")
            return

        elif self.state == "EDIT_CALIB":
            if self.calib_step == 0:
                self.calib_step = 1
                self.update_display()
                self.root.after(1500, self._calib_done)
                return
            elif self.calib_step == 2:
                self.state = "MENU";  self.calib_step = 0

        self.update_display()

    def _calib_done(self):
        if self.state == "EDIT_CALIB":
            self.calib_step = 2
            self.update_display()

    # ------------------------------------------------------------------ #
    #  RENDERIZADO                                                         #
    # ------------------------------------------------------------------ #

    def update_display(self):
        dispatch = {
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
        }
        fn = dispatch.get(self.state)
        if fn:
            fn()

    def draw_menu(self):
        opt1      = self.current_options[self.scroll_offset]
        l1_prefix = ">" if self.cursor_pos == self.scroll_offset else " "
        self.line1.config(text=f"{l1_prefix}{opt1}"[:16].ljust(16))
        if self.scroll_offset + 1 < len(self.current_options):
            opt2      = self.current_options[self.scroll_offset + 1]
            l2_prefix = ">" if self.cursor_pos == self.scroll_offset + 1 else " "
            self.line2.config(text=f"{l2_prefix}{opt2}"[:16].ljust(16))
        else:
            chars = "".join(str(i + 1) if a else "." for i, a in enumerate(self.active_beams))
            self.line2.config(text=f"BEAMS:{chars}".ljust(16))

    def draw_adsr(self):
        l1 = f"ADSR:{self.adsr_names[self.adsr_stage]}".ljust(16)
        l2 = ""
        for i, v in enumerate(self.adsr_vals):
            b   = self.bars[v]
            l2 += f"[{b}] " if i == self.adsr_stage else f" {b}  "
        self.line1.config(text=l1[:16])
        self.line2.config(text=l2[:16].ljust(16))

    def draw_eq(self):
        labels = ["LOW ", "MID ", "HIGH"]
        labels[self.eq_band] = f"*{labels[self.eq_band].strip()}*"
        l1  = f"{labels[0]:<5} {labels[1]:<5} {labels[2]:<4}"
        l2  = f"  {self.bars[self.eq_vals[0]]}     {self.bars[self.eq_vals[1]]}     {self.bars[self.eq_vals[2]]}  "
        self.line1.config(text=l1[:16])
        self.line2.config(text=l2[:16].ljust(16))

    def draw_fx(self):
        bar = "█" * self.fx_val + "-" * (16 - self.fx_val)
        self.line1.config(text="REVERB MIX:".ljust(16))
        self.line2.config(text=bar[:16].ljust(16))

    def draw_instrument(self):
        name = self.osc_types[self.osc_index]
        n    = len(self.osc_types)
        self.line1.config(text=f"TIPO OSC {self.osc_index + 1}/{n}".ljust(16))
        self.line2.config(text=f">{name:<14}".ljust(16))

    def draw_comp(self):
        names = ["UMBRAL", "RATIO "]
        l1 = f"COMP:{names[self.comp_stage]}".ljust(16)
        l2 = ""
        for i, v in enumerate(self.comp_vals):
            b   = self.bars[v]
            l2 += f"[{b}]     " if i == self.comp_stage else f" {b}      "
        self.line1.config(text=l1[:16])
        self.line2.config(text=l2[:16].ljust(16))

    def draw_lim(self):
        n_fill = int(self.lim_val * 16 / 7)
        bar    = "█" * n_fill + "-" * (16 - n_fill)
        self.line1.config(text="LIMITADOR:".ljust(16))
        self.line2.config(text=bar[:16].ljust(16))

    def draw_delay(self):
        names = ["TIEMPO", "FEEDBK"]
        l1 = f"DELAY:{names[self.delay_stage]}".ljust(16)
        l2 = ""
        for i, v in enumerate(self.delay_vals):
            b   = self.bars[v]
            l2 += f"[{b}]     " if i == self.delay_stage else f" {b}      "
        self.line1.config(text=l1[:16])
        self.line2.config(text=l2[:16].ljust(16))

    def draw_dist(self):
        n_fill = int(self.dist_val * 16 / 7)
        bar    = "█" * n_fill + "-" * (16 - n_fill)
        self.line1.config(text="DISTORSION:".ljust(16))
        self.line2.config(text=bar[:16].ljust(16))

    def draw_midi(self):
        self.line1.config(text="CANAL MIDI:".ljust(16))
        self.line2.config(text=f"CH {self.midi_channel:02d}".center(16))

    def draw_calib(self):
        if self.calib_step == 0:
            self.line1.config(text="CALIBRACION".ljust(16))
            self.line2.config(text="ENTER=INICIAR".ljust(16))
        elif self.calib_step == 1:
            self.line1.config(text="CALIBRANDO...".ljust(16))
            self.line2.config(text="Por favor...".ljust(16))
        else:
            self.line1.config(text="CALIBRADO! OK".ljust(16))
            self.line2.config(text="ENTER=SALIR".ljust(16))

    # ------------------------------------------------------------------ #
    #  AUXILIARES                                                          #
    # ------------------------------------------------------------------ #

    def get_target(self):
        target = self.menu_tree
        for folder in self.current_path:
            target = target[folder]
        return target

    def get_current_options(self):
        target = self.get_target()
        self.current_options = list(target.keys()) if isinstance(target, dict) else target

    def reset_nav(self):
        self.get_current_options()
        self.cursor_pos   = 0
        self.scroll_offset = 0

    def flash_feedback(self, text, duration_ms=400):
        """Muestra texto de confirmación brevemente sin bloquear el hilo de UI."""
        self.line1.config(text=text.center(16))
        self.line2.config(text=" " * 16)
        self.root.after(duration_ms, self.update_display)


if __name__ == "__main__":
    root = tk.Tk()
    app  = ArpaLaserVisualOS(root)
    root.mainloop()
