# ToF-Synth

Sintetizador basado en Raspberry Pi 4B con una PCB propia encima (Synthesizer ToF v1.0.0). Siete teclas tocan las notas de la escala elegida y un sensor de distancia láser VL53L0X controla el trémolo con la mano. El menú se maneja con un encoder rotativo y una pantalla TFT a color ST7789.

---

## Hardware

| Componente | Detalle |
|---|---|
| Ordenador | Raspberry Pi 4B |
| PCB | Synthesizer ToF v1.0.0 (192.35 × 104.5 mm), montada sobre la Pi con extensores de GPIO |
| Sensor láser | VL53L0X por I2C (0x29; también se prueban 0x30–0x32) |
| Pantalla | TFT ST7789 de 170×320 a color, **SPI por software** (no I2C) |
| Encoder | Rotativo con pulsador |
| Teclas | 7 pulsadores (KEY1–KEY7) + OCT▲ / OCT▼ |

### Conexiones GPIO (BCM)

| GPIO (pin físico) | Función |
|---|---|
| 2 (3) / 3 (5) | I2C — sensor VL53L0X (SDA / SCL) |
| 7 (26) | Pantalla SCL (reloj SPI) |
| 6 (31) | Pantalla SDA (MOSI) |
| 13 (33) | Pantalla CS |
| 19 (35) | Pantalla DC |
| 26 (37) | Pantalla RST en el código (en el montaje actual RES va fijo a 3V3) |
| 21, 15, 18, 16, 23, 24, 25 | KEY1 … KEY7 (de izquierda a derecha) |
| 27 / 17 | Encoder A / B |
| 22 | Pulsador del encoder |
| 10 | OCT▲ |
| 9 | OCT▼ |

BLK y VCC de la pantalla van a 3V3. Todos los botones van entre el GPIO y GND (pull-up interno).

> La pantalla es SPI: **no aparece en `i2cdetect`** y eso es normal. Para comprobar el cableado usa `test_tft.py`.

---

## PCB Design

<img width="1282" height="702" alt="image" src="https://github.com/user-attachments/assets/3a41cf8d-af91-498d-83e8-5d5e3ebb37fc" />

---

## Software

### `main.py`: aplicación principal

Ejecutar en la Raspberry Pi (necesita `menu_engine.py` en la misma carpeta):

```bash
python3 main.py
```

| Control | Fuera del menú | Dentro del menú |
|---|---|---|
| KEY1–KEY7 | Notas de la escala actual | Notas de la escala actual |
| Girar encoder | Ajusta el efecto rápido (MORPH / SATURATION / FILTER) | Navegar / cambiar valor |
| Pulsar encoder | Cambia de efecto rápido | Entrar / confirmar |
| OCT▲ / OCT▼ | Sube / baja octava (−3 … +3) | — |
| OCT▲ + OCT▼ a la vez | Abre el menú | Cierra el menú |
| Sensor láser | Profundidad del trémolo (activo por debajo de ~450 mm) | |

Menú (`menu_engine.py`):

```
Instrumento → sine | sawtooth | square | violin | guitar | piano
Escala      → Major | Minor | Penta | Blues | Dorian | HarmMin
ADSR        → Attack | Decay | Sustain | Release
EQ          → Low | Mid | High
Efectos     → Reverb (Room, Wet) | Delay (Time, Feedback)
```

### `test_tft.py`: prueba de la pantalla

Inicializa la ST7789 a mano por SPI bitbang y dibuja un patrón de prueba con varias configuraciones de tamaño, orientación y offset.

```bash
python3 test_tft.py        # todas las configuraciones
python3 test_tft.py 3      # solo la 3
```

### Otros archivos

- `main_oled.py`: versión antigua para la protoboard (OLED SH1106 por I2C y pines distintos). **No sirve con la PCB ni con la pantalla actual.**
- `simulador_menu.py`: simulador del menú antiguo en Tkinter, sin hardware.
- `arpa_un_sensor.py`: versión mínima, solo sensor y audio.

---

## Instalación de dependencias (Raspberry Pi)

```bash
pip install adafruit-circuitpython-vl53l0x adafruit-circuitpython-rgb-display \
            adafruit-blinka gpiozero sounddevice numpy pillow luma.lcd \
            --break-system-packages
```

(`luma.lcd` solo hace falta para `test_tft.py`.)

### Activar SPI4 (una sola vez)

La pantalla usa el bus SPI4 de la Pi 4 (GPIO7/GPIO6), que viene apagado. Sin esto `main.py` da `/dev/spidev4.0 does not exist`:

```bash
echo 'dtoverlay=spi4-1cs' | sudo tee -a /boot/firmware/config.txt   # en OS antiguos: /boot/config.txt
sudo reboot
ls /dev/spidev*   # debe salir /dev/spidev4.0
```

---

## Arranque automático

Para que `main.py` se ejecute solo al enchufar la Raspberry:

```bash
bash install_autostart.sh
```

| Acción | Comando |
|---|---|
| Ver estado | `systemctl --user status tof-synth` |
| Ver mensajes / errores | `journalctl --user -u tof-synth -f` |
| Parar (p. ej. para lanzarlo a mano) | `systemctl --user stop tof-synth` |
| Quitar el arranque automático | `systemctl --user disable --now tof-synth` |

Si lo lanzas a mano con `python3 main.py` mientras el servicio está activo, los dos chocan por los pines. Para el servicio antes.
