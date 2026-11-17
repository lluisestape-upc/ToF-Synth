class ArpaLaserEngine:
    INSTRUMENTOS = ["sine", "sawtooth", "square", "violin", "guitar", "piano"]
    MENU_ITEMS   = ["Instrumento", "Escala", "ADSR", "EQ", "Efectos"]
    FX_ITEMS     = ["Reverb", "Delay", "< Volver"]
    SCALES = [
        ("Major",   [0, 2, 4,  5, 7,  9, 11]),
        ("Minor",   [0, 2, 3,  5, 7,  8, 10]),
        ("Penta",   [0, 2, 4,  7, 9, 12, 14]),
        ("Blues",   [0, 3, 5,  6, 7, 10, 12]),
        ("Dorian",  [0, 2, 3,  5, 7,  9, 10]),
        ("HarmMin", [0, 2, 3,  5, 7,  8, 11]),
    ]
    _BAR = " ▁▂▃▄▅▆▇█"

    def __init__(self):
        self.estado    = "MAIN"
        self.idx_main  = 0
        self.idx_inst  = 0
        self.idx_scale = 0
        self.idx_adsr  = 0
        self.idx_eq    = 0
        self.idx_fx    = 0
        self.idx_rev   = 0
        self.idx_dly   = 0
        self.idx_dst   = 0
        self.editing   = False

        # ADSR: Attack, Decay, Sustain, Release  (0–16)
        self.adsr   = [2, 3, 12, 3]
        # EQ: Low, Mid, High  (0–16, 8 = neutral)
        self.eq     = [8, 8, 8]
        # Effects
        self.reverb = [4, 3]   # Room, Wet
        self.delay  = [4, 6]   # Time, Feedback
        self.dist   = [0]      # Gain

        self._adsr_n = ["Attack", "Decay", "Sustain", "Release"]
        self._eq_n   = ["Low", "Mid", "High"]
        self._rev_n  = ["Room", "Wet"]
        self._dly_n  = ["Time", "Feedback"]
        self._dst_n  = ["Gain"]

    # ── Getters ────────────────────────────────────────────────────────────────
    def get_current_instrument(self):
        return self.INSTRUMENTOS[self.idx_inst]

    def get_current_scale(self):
        """Returns (name, [semitone_offsets]) for 7 buttons."""
        return self.SCALES[self.idx_scale]

    def get_adsr_normalized(self):
        a, d, s, r = self.adsr
        return a / 16 * 2.0, d / 16 * 2.0, s / 16, r / 16 * 2.0

    def get_eq_normalized(self):
        """[low, mid, high] each 0–2 where 1.0 = neutral."""
        return [v / 8.0 for v in self.eq]

    def get_reverb(self):
        return self.reverb[0] / 16, self.reverb[1] / 16

    def get_delay(self):
        return self.delay[0] / 16 * 0.5, self.delay[1] / 16 * 0.8

    def get_distortion(self):
        return self.dist[0] / 16

    # ── Input ──────────────────────────────────────────────────────────────────
    def rotate(self, d):
        if self.editing:
            self._edit_val(d); return
        st = self.estado
        if   st == "MAIN":  self.idx_main  = (self.idx_main  + d) % len(self.MENU_ITEMS)
        elif st == "INST":  self.idx_inst  = (self.idx_inst  + d) % len(self.INSTRUMENTOS)
        elif st == "SCALE": self.idx_scale = (self.idx_scale + d) % len(self.SCALES)
        elif st == "ADSR":
            if self.idx_adsr < len(self._adsr_n):
                self.adsr[self.idx_adsr] = max(0, min(16, self.adsr[self.idx_adsr] + d))
        elif st == "EQ":
            if self.idx_eq < len(self._eq_n):
                self.eq[self.idx_eq] = max(0, min(16, self.eq[self.idx_eq] + d))
        elif st == "FX":    self.idx_fx    = (self.idx_fx    + d) % len(self.FX_ITEMS)
        elif st == "REV":   self.idx_rev   = (self.idx_rev   + d) % (len(self._rev_n)  + 1)
        elif st == "DLY":   self.idx_dly   = (self.idx_dly   + d) % (len(self._dly_n)  + 1)
        elif st == "DST":   self.idx_dst   = (self.idx_dst   + d) % (len(self._dst_n)  + 1)

    def _edit_val(self, d):
        def clamp(v): return max(0, min(16, v + d))
        st = self.estado
        if   st == "ADSR": self.adsr[self.idx_adsr]   = clamp(self.adsr[self.idx_adsr])
        elif st == "EQ":   self.eq[self.idx_eq]        = clamp(self.eq[self.idx_eq])
        elif st == "REV":  self.reverb[self.idx_rev]   = clamp(self.reverb[self.idx_rev])
        elif st == "DLY":  self.delay[self.idx_dly]    = clamp(self.delay[self.idx_dly])
        elif st == "DST":  self.dist[self.idx_dst]     = clamp(self.dist[self.idx_dst])

    def press(self):
        if self.editing:
            self.editing = False; return
        st = self.estado
        if st == "MAIN":
            sel = self.MENU_ITEMS[self.idx_main]
            if   sel == "Instrumento": self.estado = "INST"
            elif sel == "Escala":      self.estado = "SCALE"
            elif sel == "ADSR":        self.estado = "ADSR"; self.idx_adsr = 0
            elif sel == "EQ":          self.estado = "EQ";   self.idx_eq   = 0
            elif sel == "Efectos":     self.estado = "FX";   self.idx_fx   = 0
        elif st == "INST":  self.estado = "MAIN"
        elif st == "SCALE": self.estado = "MAIN"
        elif st == "ADSR":
            if self.idx_adsr == len(self._adsr_n):
                self.estado = "MAIN"; self.idx_adsr = 0
            else:
                self.idx_adsr = (self.idx_adsr + 1) % (len(self._adsr_n) + 1)
        elif st == "EQ":
            if self.idx_eq == len(self._eq_n):
                self.estado = "MAIN"; self.idx_eq = 0
            else:
                self.idx_eq = (self.idx_eq + 1) % (len(self._eq_n) + 1)
        elif st == "FX":
            sel = self.FX_ITEMS[self.idx_fx]
            if   sel == "Reverb":     self.estado = "REV"; self.idx_rev = 0
            elif sel == "Delay":      self.estado = "DLY"; self.idx_dly = 0
            elif sel == "Distorsion": self.estado = "DST"; self.idx_dst = 0
            elif sel == "< Volver":   self.estado = "MAIN"
        elif st in ("REV", "DLY", "DST"):
            lens = {"REV": len(self._rev_n), "DLY": len(self._dly_n), "DST": len(self._dst_n)}
            idxs = {"REV": self.idx_rev,     "DLY": self.idx_dly,     "DST": self.idx_dst}
            if idxs[st] == lens[st]: self.estado = "FX"
            else: self.editing = True

    # ── Display lines (two rows like LCD) ─────────────────────────────────────
    def _bar(self, v, m=16):
        return self._BAR[max(0, min(8, round(v / m * 8)))]

    def _row(self, name, val, active):
        return (">" if active else " ") + f"{name:<8}{self._bar(val)}{val:3d}"

    def _param_rows(self, names, vals, idx):
        items = names + ["< Volver"]
        avals = list(vals) + [None]
        def make(i, active):
            if avals[i] is None: return (">" if active else " ") + items[i]
            return self._row(items[i], avals[i], active)
        return make(idx, True), make((idx + 1) % len(items), False)

    def _edit_lines(self):
        st = self.estado
        cfg = {
            "ADSR": (self._adsr_n[self.idx_adsr], self.adsr[self.idx_adsr]),
            "EQ":   (self._eq_n[self.idx_eq],     self.eq[self.idx_eq]),
            "REV":  (self._rev_n[self.idx_rev],   self.reverb[self.idx_rev]),
            "DLY":  (self._dly_n[self.idx_dly],   self.delay[self.idx_dly]),
            "DST":  (self._dst_n[self.idx_dst],   self.dist[self.idx_dst]),
        }
        if st not in cfg: return "---", "---"
        name, val = cfg[st]
        filled = round(val / 16 * 12)
        return f"[{name[:6]}]{val:3d}", "█" * filled + "░" * (12 - filled)

    def get_lines(self):
        if self.editing: return self._edit_lines()
        st = self.estado
        if st == "MAIN":
            a = self.MENU_ITEMS[self.idx_main]
            b = self.MENU_ITEMS[(self.idx_main + 1) % len(self.MENU_ITEMS)]
            return f">{a}", f" {b}"
        if st == "INST":
            a = self.INSTRUMENTOS[self.idx_inst].upper()
            b = self.INSTRUMENTOS[(self.idx_inst + 1) % len(self.INSTRUMENTOS)].upper()
            return f">{a}", f" {b}"
        if st == "SCALE":
            a = self.SCALES[self.idx_scale][0]
            b = self.SCALES[(self.idx_scale + 1) % len(self.SCALES)][0]
            return f">{a}", f" {b}"
        if st == "ADSR": return self._param_rows(self._adsr_n, self.adsr, self.idx_adsr)
        if st == "EQ":   return self._param_rows(self._eq_n,   self.eq,   self.idx_eq)
        if st == "FX":
            a = self.FX_ITEMS[self.idx_fx]
            b = self.FX_ITEMS[(self.idx_fx + 1) % len(self.FX_ITEMS)]
            return f">{a}", f" {b}"
        if st == "REV": return self._param_rows(self._rev_n, self.reverb, self.idx_rev)
        if st == "DLY": return self._param_rows(self._dly_n, self.delay,  self.idx_dly)
        if st == "DST": return self._param_rows(self._dst_n, self.dist,   self.idx_dst)
        return "---", "---"

    def get_three_lines(self):
        """Returns (prev, active, next) label strings for 3-item scroll display."""
        st = self.estado

        def _pick(lst, idx):
            n = len(lst)
            return lst[(idx - 1) % n], lst[idx % n], lst[(idx + 1) % n]

        if st == "MAIN":
            p, a, b = _pick(self.MENU_ITEMS, self.idx_main)
            return p, f">{a}", b
        if st == "INST":
            items = [x.upper() for x in self.INSTRUMENTOS]
            p, a, b = _pick(items, self.idx_inst)
            return p, f">{a}", b
        if st == "SCALE":
            items = [x[0] for x in self.SCALES]
            p, a, b = _pick(items, self.idx_scale)
            return p, f">{a}", b
        if st == "FX":
            p, a, b = _pick(self.FX_ITEMS, self.idx_fx)
            return p, f">{a}", b

        # Param states (ADSR, EQ, REV, DLY, DST)
        cfg = {
            "ADSR": (self._adsr_n, self.adsr,   self.idx_adsr),
            "EQ":   (self._eq_n,   self.eq,      self.idx_eq),
            "REV":  (self._rev_n,  self.reverb,  self.idx_rev),
            "DLY":  (self._dly_n,  self.delay,   self.idx_dly),
            "DST":  (self._dst_n,  self.dist,     self.idx_dst),
        }
        if st in cfg:
            names, vals, idx = cfg[st]
            items = names + ["< Volver"]
            avals = list(vals) + [None]
            n = len(items)
            def _label(i):
                v = avals[i % n]
                nm = items[i % n]
                return nm if v is None else f"{nm} {self._bar(v)}{v}"
            return _label(idx - 1), f">{_label(idx)}", _label(idx + 1)

        return "", "---", ""
