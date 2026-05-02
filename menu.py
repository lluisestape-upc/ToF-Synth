import RPi.GPIO as GPIO
import time
from luma.core.interface.serial import i2c as luma_i2c
from luma.oled.device import sh1106
from luma.core.render import canvas
from PIL import ImageFont

# --- CONFIGURACIÓN ---
OLED_ADDR = 0x3C
PIN_A    = 27   # Encoder canal A
PIN_B    = 22   # Encoder canal B
PIN_BTN  = 23   # Botón entrar/seleccionar
PIN_DOWN = 24   # Botón bajar menú
PIN_EC11 = 25   # EC11 pin D (también entra/selecciona)

W, H   = 128, 64
LINE_H = 13   # píxeles por fila de texto

try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 11)
except OSError:
    FONT = ImageFont.load_default()

VISIBLE = H // LINE_H   # filas visibles en el menú (~4)


class ArpaMenu:
    def __init__(self):
        serial     = luma_i2c(port=1, address=OLED_ADDR)
        self.dev   = sh1106(serial, rotate=0)

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
        self.fx_val       = 10        # 0–16
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

        GPIO.setmode(GPIO.BCM)
        for pin in (PIN_A, PIN_B, PIN_BTN, PIN_DOWN, PIN_EC11):
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # Todo por polling — sin interrupts, sin ruido espurio
        self._prev_a    = bool(GPIO.input(PIN_A))
        self._prev_btn  = True
        self._prev_down = True
        self._prev_ec11 = True
        self._t_enc     = 0.0   # debounce encoder

    # ------------------------------------------------------------------ #
    #  BUCLE PRINCIPAL                                                     #
    # ------------------------------------------------------------------ #

    def run(self):
        print("Iniciando pantalla...")
        try:
            with canvas(self.dev) as draw:
                draw.text((0, 0),  "PANTALLA OK",  font=FONT, fill="white")
                draw.text((0, 20), "MENU CARGANDO", font=FONT, fill="white")
            print("  -> canvas() OK")
        except Exception as e:
            print(f"  -> ERROR canvas(): {e}")

        print("Llamando render()...")
        try:
            self.render()
            print("  -> render() OK")
        except Exception as e:
            print(f"  -> ERROR render(): {e}")

        print("Menú activo. Ctrl+C para salir.")
        print(f"  Pines — BTN(GPIO{PIN_BTN}):{GPIO.input(PIN_BTN)}  DOWN(GPIO{PIN_DOWN}):{GPIO.input(PIN_DOWN)}  EC11(GPIO{PIN_EC11}):{GPIO.input(PIN_EC11)}")
        print("  (1=reposo, 0=pulsado)")
        try:
            while True:
                now       = time.time()
                curr_a    = bool(GPIO.input(PIN_A))
                curr_btn  = bool(GPIO.input(PIN_BTN))
                curr_down = bool(GPIO.input(PIN_DOWN))
                curr_ec11 = bool(GPIO.input(PIN_EC11))

                # Encoder: flanco bajada de A + estado de B → dirección
                if not curr_a and self._prev_a and (now - self._t_enc) > 0.012:
                    self._t_enc = now
                    d = 1 if GPIO.input(PIN_B) else -1
                    print(f"[ENC] {'CW' if d==1 else 'CCW'}")
                    self.rotate(d)

                # Botones
                if not curr_down and self._prev_down:
                    print(f"[GPIO{PIN_DOWN}] DOWN pulsado")
                    self.rotate(1)
                if not curr_btn and self._prev_btn:
                    print(f"[GPIO{PIN_BTN}] BTN pulsado")
                    self.press()
                if not curr_ec11 and self._prev_ec11:
                    print(f"[GPIO{PIN_EC11}] EC11 pulsado")
                    self.press()

                self._prev_a    = curr_a
                self._prev_btn  = curr_btn
                self._prev_down = curr_down
                self._prev_ec11 = curr_ec11

                time.sleep(0.005)   # 5 ms — suficiente para capturar giros rápidos
        except KeyboardInterrupt:
            pass
        finally:
            self.dev.cleanup()
            GPIO.cleanup()

    # ------------------------------------------------------------------ #
    #  GPIO CALLBACKS                                                      #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  RENDER                                                              #
    # ------------------------------------------------------------------ #

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
        if fn is None:
            print(f"WARN: estado desconocido '{self.state}'")
            return
        try:
            fn()
        except Exception as e:
            print(f"ERROR en draw [{self.state}]: {e}")

    def _rows(self, draw, rows):
        """Dibuja filas de (texto, seleccionado). Seleccionado = texto invertido."""
        for i, (text, sel) in enumerate(rows):
            y = i * LINE_H
            if sel:
                draw.rectangle([(0, y), (W - 1, y + LINE_H - 1)], fill="white")
                draw.text((2, y + 1), text, font=FONT, fill="black")
            else:
                draw.text((2, y + 1), text, font=FONT, fill="white")

    def draw_menu(self):
        opts = self._options()
        rows = []
        for i in range(VISIBLE):
            idx = self.scroll_off + i
            if idx >= len(opts):
                break
            rows.append(((">" if idx == self.cursor_pos else " ") + opts[idx],
                         idx == self.cursor_pos))
        with canvas(self.dev) as draw:
            self._rows(draw, rows)

    def _vbar(self, draw, x, bot, bw, bh, value, max_val, active=False):
        """Barra vertical desde bot hacia arriba."""
        fill_h = int(bh * value / max_val)
        draw.rectangle([(x, bot - bh), (x + bw, bot)], outline="white")
        if fill_h > 0:
            draw.rectangle([(x + 1, bot - fill_h), (x + bw - 1, bot)], fill="white")
        if active:
            # marcador superior
            draw.rectangle([(x - 1, bot - bh - 3), (x + bw + 1, bot - bh - 1)], fill="white")

    def draw_adsr(self):
        bw, bh  = 22, 40
        spacing = (W - 4 * bw) // 5
        bot     = H - 2
        labels  = ["A", "D", "S", "R"]
        with canvas(self.dev) as draw:
            draw.text((0, 0), f"ADSR: {self.adsr_names[self.adsr_stage]}", font=FONT, fill="white")
            for i, v in enumerate(self.adsr_vals):
                x = spacing + i * (bw + spacing)
                self._vbar(draw, x, bot, bw, bh, v, 7, active=(i == self.adsr_stage))
                draw.text((x + bw // 2 - 3, bot - bh - 11), labels[i], font=FONT, fill="white")

    def draw_eq(self):
        bw, bh  = 28, 40
        spacing = (W - 3 * bw) // 4
        bot     = H - 2
        labels  = ["LOW", "MID", "HI"]
        with canvas(self.dev) as draw:
            draw.text((0, 0), "ECUALIZADOR", font=FONT, fill="white")
            for i, v in enumerate(self.eq_vals):
                x   = spacing + i * (bw + spacing)
                sel = i == self.eq_band
                self._vbar(draw, x, bot, bw, bh, v, 7, active=sel)
                lx  = x + bw // 2 - len(labels[i]) * 3
                ly  = bot - bh - 12
                if sel:
                    draw.rectangle([(lx - 1, ly - 1), (lx + len(labels[i]) * 6, ly + 10)], fill="white")
                    draw.text((lx, ly), labels[i], font=FONT, fill="black")
                else:
                    draw.text((lx, ly), labels[i], font=FONT, fill="white")

    def _hbar(self, draw, value, max_val, title):
        draw.text((0, 0), title, font=FONT, fill="white")
        by     = LINE_H + 6
        bh_px  = 14
        fw     = int((W - 4) * value / max_val)
        draw.rectangle([(2, by), (W - 2, by + bh_px)], outline="white")
        if fw > 0:
            draw.rectangle([(3, by + 1), (2 + fw, by + bh_px - 1)], fill="white")
        draw.text((0, by + bh_px + 4), f"{value} / {max_val}", font=FONT, fill="white")

    def draw_fx(self):
        with canvas(self.dev) as draw:
            self._hbar(draw, self.fx_val, 16, "REVERB MIX")

    def draw_instrument(self):
        with canvas(self.dev) as draw:
            draw.text((0, 5), f"TIPO OSC  {self.osc_index+1}/{len(self.osc_types)}", font=FONT, fill="white")
            draw.text((0, 30), f"> {self.osc_types[self.osc_index]}", font=FONT, fill="white")

    def _two_vbars(self, draw, title, values, labels, active_idx):
        bw, bh  = 46, 38
        bot     = H - 2
        draw.text((0, 0), title, font=FONT, fill="white")
        xs = [10, 10 + bw + 20]
        for i, v in enumerate(values):
            x   = xs[i]
            sel = i == active_idx
            self._vbar(draw, x, bot, bw, bh, v, 7, active=sel)
            lx  = x + bw // 2 - len(labels[i]) * 3
            ly  = bot - bh - 12
            if sel:
                draw.rectangle([(lx - 1, ly - 1), (lx + len(labels[i]) * 6, ly + 10)], fill="white")
                draw.text((lx, ly), labels[i], font=FONT, fill="black")
            else:
                draw.text((lx, ly), labels[i], font=FONT, fill="white")

    def draw_comp(self):
        with canvas(self.dev) as draw:
            self._two_vbars(draw, "COMPRESOR", self.comp_vals,
                            ["UMBRAL", "RATIO"], self.comp_stage)

    def draw_lim(self):
        with canvas(self.dev) as draw:
            self._hbar(draw, self.lim_val, 7, "LIMITADOR")

    def draw_delay(self):
        with canvas(self.dev) as draw:
            self._two_vbars(draw, "DELAY", self.delay_vals,
                            ["TIEMPO", "FEEDBK"], self.delay_stage)

    def draw_dist(self):
        with canvas(self.dev) as draw:
            self._hbar(draw, self.dist_val, 7, "DISTORSION")

    def draw_midi(self):
        ch = f"CH {self.midi_channel:02d}"
        with canvas(self.dev) as draw:
            draw.text((0, 10), "CANAL MIDI", font=FONT, fill="white")
            draw.text((W // 2 - len(ch) * 4, 35), ch, font=FONT, fill="white")

    def draw_calib(self):
        msgs = [("CALIBRACION",   "Pulsar=INICIAR"),
                ("CALIBRANDO...", "Espere..."),
                ("CALIBRADO!",    "Pulsar=SALIR")]
        l1, l2 = msgs[self.calib_step]
        with canvas(self.dev) as draw:
            draw.text((0, 10), l1, font=FONT, fill="white")
            draw.text((0, 32), l2, font=FONT, fill="white")

    # ------------------------------------------------------------------ #
    #  LÓGICA DE ENCODER                                                   #
    # ------------------------------------------------------------------ #

    def rotate(self, direction):
        if self.state == "MENU":
            opts = self._options()
            self.cursor_pos = (self.cursor_pos + direction) % len(opts)
            if self.cursor_pos < self.scroll_off:
                self.scroll_off = self.cursor_pos
            elif self.cursor_pos >= self.scroll_off + VISIBLE:
                self.scroll_off = self.cursor_pos - VISIBLE + 1
            if self.cursor_pos == 0:
                self.scroll_off = 0
        elif self.state == "EDIT_ADSR":
            self.adsr_vals[self.adsr_stage] = max(0, min(7, self.adsr_vals[self.adsr_stage] - direction))
        elif self.state == "EDIT_EQ":
            self.eq_vals[self.eq_band] = max(0, min(7, self.eq_vals[self.eq_band] - direction))
        elif self.state == "EDIT_FX":
            self.fx_val = max(0, min(16, self.fx_val - direction))
        elif self.state == "EDIT_INSTRUMENT":
            self.osc_index = (self.osc_index - direction) % len(self.osc_types)
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

    # ------------------------------------------------------------------ #
    #  LÓGICA DE PULSADOR                                                  #
    # ------------------------------------------------------------------ #

    def press(self):
        if self.state == "MENU":
            sel = self._options()[self.cursor_pos]
            if sel == "Back":
                if self.current_path:
                    self.current_path.pop()
                self.cursor_pos = 0
                self.scroll_off = 0
            elif sel == "Visual ADSR":
                self.state = "EDIT_ADSR";  self.adsr_stage = 0
            elif sel == "Visual EQ":
                self.state = "EDIT_EQ";    self.eq_band = 0
            elif sel == "Reverb":
                self.state = "EDIT_FX"
            elif sel == "Change Type":
                self.state = "EDIT_INSTRUMENT"
            elif sel == "Compressor":
                self.state = "EDIT_COMP";  self.comp_stage = 0
            elif sel == "Limiter":
                self.state = "EDIT_LIM"
            elif sel == "Delay":
                self.state = "EDIT_DELAY"; self.delay_stage = 0
            elif sel == "Distortion":
                self.state = "EDIT_DIST"
            elif sel == "MIDI Channel":
                self.state = "EDIT_MIDI"
            elif sel == "Calibration":
                self.state = "EDIT_CALIB"; self.calib_step = 0
            elif sel in self.menu_tree:
                self.current_path.append(sel)
                self.cursor_pos = 0
                self.scroll_off = 0

        elif self.state == "EDIT_ADSR":
            self.adsr_stage += 1
            if self.adsr_stage > 3:
                self.state = "MENU"; self.adsr_stage = 0
                self._saved(); return

        elif self.state == "EDIT_EQ":
            self.eq_band += 1
            if self.eq_band > 2:
                self.state = "MENU"; self.eq_band = 0
                self._saved(); return

        elif self.state in ("EDIT_FX", "EDIT_INSTRUMENT", "EDIT_LIM",
                            "EDIT_DIST", "EDIT_MIDI"):
            self.state = "MENU"
            self._saved(); return

        elif self.state == "EDIT_COMP":
            self.comp_stage += 1
            if self.comp_stage > 1:
                self.state = "MENU"; self.comp_stage = 0
                self._saved(); return

        elif self.state == "EDIT_DELAY":
            self.delay_stage += 1
            if self.delay_stage > 1:
                self.state = "MENU"; self.delay_stage = 0
                self._saved(); return

        elif self.state == "EDIT_CALIB":
            if self.calib_step == 0:
                self.calib_step = 1
                self.render()
                time.sleep(1.5)
                self.calib_step = 2
            elif self.calib_step == 2:
                self.state = "MENU"; self.calib_step = 0

        self.render()

    def _saved(self):
        with canvas(self.dev) as draw:
            draw.text((W // 2 - 36, H // 2 - 8), "GUARDADO!", font=FONT, fill="white")
        time.sleep(0.5)
        self.render()

    def _options(self):
        t = self.menu_tree
        for folder in self.current_path:
            t = t[folder]
        return list(t.keys()) if isinstance(t, dict) else t


if __name__ == "__main__":
    ArpaMenu().run()
