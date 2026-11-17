#!/usr/bin/env python3
"""Prueba de la pantalla TFT ST7789 (SPI por software / bitbang).

Cableado actual (numeracion BCM / pin fisico):
  SCL (reloj)  GPIO7  (pin 26)
  SDA (MOSI)   GPIO6  (pin 31)
  CS           GPIO13 (pin 33)
  DC           GPIO19 (pin 35)
  RES, BLK, VCC -> 3V3 (pin 1), GND -> pin 9

Uso:
  pip install luma.lcd
  python3 test_tft.py            # prueba 240x240 y luego 240x320
  python3 test_tft.py 240 240    # solo un tamano
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

if len(sys.argv) == 3:
    SIZES = [(int(sys.argv[1]), int(sys.argv[2]))]
else:
    SIZES = [(240, 240), (240, 320)]

serial = bitbang(SCLK=PIN_SCLK, SDA=PIN_SDA, CE=PIN_CS, DC=PIN_DC, RST=PIN_RST)

for w, h in SIZES:
    print(f"Probando {w}x{h}...")
    dev = st7789(serial, width=w, height=h, rotate=0)
    img = Image.new("RGB", (w, h), "black")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w - 1, h // 2), fill="red")
    d.text((10, 10), f"{w}x{h} OK", fill="white")
    dev.display(img)
    time.sleep(8)

print("Fin.")
