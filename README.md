# LaserHarp

Instrumento musical basado en Raspberry Pi 4B. Un sensor de distancia láser (VL53L0X) detecta gestos con la mano para generar sonido continuo con glide. Tres botones adicionales tocan un acorde 1-3-5. Un encoder rotativo EC11 y una pantalla OLED SH1106 forman el menú de control de síntesis.

---

## Hardware

| Componente | Detalle |
|---|---|
| Ordenador | Raspberry Pi 4B |
| Sensor láser | VL53L0X (I2C, 0x29) |
| Pantalla | SH1106 OLED 128×64 (I2C, 0x3C) |
| Encoder | EC11 rotativo con pulsador |
| Botones acorde | 3× pulsador normalmente abierto |

### Conexiones GPIO (BCM)

| GPIO | Función |
|---|---|
| 2 (SDA) / 3 (SCL) | I2C compartido — sensor + pantalla |
| 5 | Botón acorde — 1ª (Do, raíz) |
| 6 | Botón acorde — 3ª (Mi) |
| 22 | Encoder B |
| 23 | Botón enter |
| 24 | Botón bajar menú |
| 25 | Encoder pulsador (D) |
| 26 | Botón acorde — 5ª (Sol) |
| 27 | Encoder A |

Todos los botones conectados entre el GPIO y GND (pull-up interno activo).

---

## Software

### `main.py` — Aplicación principal

Ejecutar en la Raspberry Pi:

```bash
python main.py
```

**Síntesis de audio:**
- **Sensor láser** → voz continua con glide de frecuencia (distancia < 500 mm activa la nota; la distancia modula el pitch alrededor de Do4)
- **Botones GPIO 5 / 6 / 26** → acorde mayor 1-3-5 (Do / Mi / Sol) con envolvente ADSR completa
- **Reverb** tipo comb-filter aplicado a la mezcla total
- Formas de onda seleccionables: SINE, SAW, SQUARE, TRIANGLE
- Graba todo el audio; al salir con Ctrl+C guarda `grabacion_arpa.wav`

**Menú OLED (EC11 + botones):**

| Control | Acción |
|---|---|
| Girar encoder | Navegar / ajustar valor |
| Botón 23 o EC11-D (25) | Entrar / confirmar |
| Botón 24 | Bajar en el menú |

```
INSTRUMENT → Change Type (forma de onda) | Visual ADSR
MIXING     → Visual EQ | Compressor | Limiter
EFFECTS    → Reverb | Delay | Distortion
CONFIG     → MIDI Channel | Calibration
```

Los parámetros de ADSR, forma de onda y reverb se aplican al audio en tiempo real al girar el encoder.

---

### `simulador_menu.py` — Simulador de escritorio (Windows/Linux/Mac)

Emula la interfaz LCD en una ventana Tkinter. No requiere hardware.

```bash
python simulador_menu.py
```

Controles: flechas ↑↓ para girar el encoder, Enter para pulsar.

---

### `arpa_un_sensor.py` — Versión mínima (un sensor, sin menú)

Versión de prueba: sensor + audio + LEDs, sin pantalla ni menú.

```bash
python arpa_un_sensor.py
```

---

## Instalación de dependencias (Raspberry Pi)

```bash
pip install adafruit-circuitpython-vl53l0x sounddevice soundfile numpy luma.oled RPi.GPIO --break-system-packages
```

---

## Diseño de hardware

Los esquemáticos de la protoboard están en formato Fritzing (`.fzz`):

- `LaserHarp Protoboard Design.fzz` — v1
- `LaserHarp Protoboard Design_V2.fzz` — v2
- `LaserHarp Protoboard Design_V3.beta.fzz` — v3 beta (actual)
