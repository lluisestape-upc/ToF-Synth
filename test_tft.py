#!/usr/bin/env python3
"""Prueba de la pantalla TFT ST7789 (SPI por software / bitbang).

Cableado actual (numeracion BCM / pin fisico):
  SCL (reloj)  GPIO7  (pin 26)
  SDA (MOSI)   GPIO6  (pin 31)
  CS           GPIO13 (pin 33)
  DC           GPIO19 (pin 35)
  RES, BLK, VCC -> 3V3 (pin 1), GND -> pin 9

Recorre varias configuraciones (tamano, rotacion, offset) y en cada una
dibuja un borde blanco de 1 px, esquinas de colores y el numero de config.
Antes de cada prueba borra toda la memoria de la pantalla (240x320), asi
no quedan pixeles aleatorios.

Mira cual muestra: borde blanco completo, las 4 esquinas visibles
(rojo arriba-izq, verde arriba-der, azul abajo-izq, amarillo abajo-der),
texto legible y sin ruido. Apunta el numero y dimelo.

Uso:
  pip install luma.lcd
  python3 test_tft.py          # todas las configuraciones, 6 s cada una
  python3 test_tft.py 3        # solo la configuracion 3
"""
import sys
import time

from luma.core.interface.serial import bitbang
from luma.lcd.device import st7789
from PIL import Image, ImageDraw

PIN_SCLK = 7
PIN_SDA = 6
PIN_CS = 13
PIN_DC = 19
PIN_RST = None  # RES va fijo a 3V3

# (ancho, alto, rotate, h_offset, v_offset)
CONFIGS = [
    (240, 240, 0, 0, 0),
    (240, 240, 1, 0, 0),
    (240, 240, 2, 0, 80),
    (240, 240, 3, 80, 0),
    (240, 320, 0, 0, 0),
    (240, 320, 2, 0, 0),
    (320, 240, 1, 0, 0),
    (320, 240, 3, 0, 0),
]

serial = bitbang(SCLK=PIN_SCLK, SDA=PIN_SDA, CE=PIN_CS, DC=PIN_DC, RST=PIN_RST)


def clear_all():
    """Pone a negro toda la RAM del controlador (240x320)."""
    dev = st7789(serial, width=240, height=320, rotate=0)
    dev.display(Image.new("RGB", (240, 320), "black"))


def pattern(w, h, n):
    img = Image.new("RGB", (w, h), "black")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w - 1, h - 1), outline="white")
    s = 24
    d.rectangle((1, 1, s, s), fill="red")
    d.rectangle((w - 1 - s, 1, w - 2, s), fill="green")
    d.rectangle((1, h - 1 - s, s, h - 2), fill="blue")
    d.rectangle((w - 1 - s, h - 1 - s, w - 2, h - 2), fill="yellow")
    d.text((w // 2 - 40, h // 2 - 10), f"CONFIG {n}", fill="white")
    d.text((w // 2 - 40, h // 2 + 5), f"{w}x{h}", fill="white")
    return img


sel = [int(sys.argv[1])] if len(sys.argv) > 1 else range(1, len(CONFIGS) + 1)

for n in sel:
    w, h, rot, ho, vo = CONFIGS[n - 1]
    print(f"Config {n}: {w}x{h} rotate={rot} h_offset={ho} v_offset={vo}")
    clear_all()
    dev = st7789(serial, width=w, height=h, rotate=rot, h_offset=ho, v_offset=vo)
    dev.display(pattern(w, h, n))
    time.sleep(6)

print("Fin.")
