#!/usr/bin/env python3
"""Prueba de la pantalla TFT ST7789 (SPI por software / bitbang).

Cableado actual (numeracion BCM / pin fisico):
  SCL (reloj)  GPIO7  (pin 26)
  SDA (MOSI)   GPIO6  (pin 31)
  CS           GPIO13 (pin 33)
  DC           GPIO19 (pin 35)
  RES, BLK, VCC -> 3V3 (pin 1), GND -> pin 9

El driver st7789 de luma.lcd no permite cambiar offsets ni MADCTL, asi que
aqui se usa solo su interfaz serie (bitbang) y se manda la inicializacion a
mano. Recorre varias configuraciones (tamano, orientacion, offset) y en cada
una borra toda la RAM (240x320) y dibuja un borde blanco de 1 px, esquinas de
colores y el numero de config.

Mira cual muestra: borde blanco completo, las 4 esquinas visibles
(rojo arriba-izq, verde arriba-der, azul abajo-izq, amarillo abajo-der),
texto legible y sin ruido. Apunta el numero y dimelo. Si los colores salen
cambiados (rojo<->azul) prueba con --bgr.

Uso:
  pip install luma.lcd
  python3 test_tft.py              # todas las configs, 6 s cada una
  python3 test_tft.py 3            # solo la config 3
  python3 test_tft.py 3 --bgr      # config 3 con orden de color BGR
"""
import sys
import time

from luma.core.interface.serial import bitbang
from PIL import Image, ImageDraw

PIN_SCLK = 7
PIN_SDA = 6
PIN_CS = 13
PIN_DC = 19
PIN_RST = None  # RES va fijo a 3V3

# (ancho, alto, MADCTL, x_offset, y_offset)
CONFIGS = [
    (240, 240, 0x00, 0, 0),
    (240, 240, 0xC0, 0, 80),
    (240, 240, 0x60, 0, 0),
    (240, 240, 0xA0, 80, 0),
    (240, 320, 0x00, 0, 0),
    (320, 240, 0x60, 0, 0),
    (320, 240, 0xA0, 0, 0),
    (240, 240, 0x70, 0, 0),  # lo que usa luma por defecto
]

BGR = "--bgr" in sys.argv
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]


class ST7789:
    def __init__(self, serial):
        self.s = serial

    def cmd(self, c, *args):
        self.s.command(c)
        if args:
            self.s.data(list(args))

    def init(self, madctl):
        self.cmd(0x01)  # SWRESET
        time.sleep(0.15)
        self.cmd(0x11)  # SLPOUT
        time.sleep(0.12)
        self.cmd(0x36, madctl | (0x08 if BGR else 0x00))
        self.cmd(0x3A, 0x55)  # 16 bit/pixel
        self.cmd(0xB2, 0x0C, 0x0C, 0x00, 0x33, 0x33)
        self.cmd(0xB7, 0x35)
        self.cmd(0xBB, 0x19)
        self.cmd(0xC0, 0x2C)
        self.cmd(0xC2, 0x01)
        self.cmd(0xC3, 0x12)
        self.cmd(0xC4, 0x20)
        self.cmd(0xC6, 0x0F)
        self.cmd(0xD0, 0xA4, 0xA1)
        self.cmd(0x21)  # INVON (casi todos los modulos IPS lo necesitan)
        self.cmd(0x13)  # NORON
        self.cmd(0x29)  # DISPON
        time.sleep(0.05)

    def window(self, x0, y0, x1, y1):
        self.cmd(0x2A, x0 >> 8, x0 & 255, x1 >> 8, x1 & 255)
        self.cmd(0x2B, y0 >> 8, y0 & 255, y1 >> 8, y1 & 255)
        self.s.command(0x2C)  # RAMWR

    def blit(self, img, xo, yo):
        w, h = img.size
        raw = img.convert("RGB").tobytes()
        out = bytearray(w * h * 2)
        j = 0
        for i in range(0, len(raw), 3):
            v = ((raw[i] & 0xF8) << 8) | ((raw[i + 1] & 0xFC) << 3) | (raw[i + 2] >> 3)
            out[j] = v >> 8
            out[j + 1] = v & 255
            j += 2
        self.window(xo, yo, xo + w - 1, yo + h - 1)
        self.s.data(list(out))


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


def main():
    serial = bitbang(SCLK=PIN_SCLK, SDA=PIN_SDA, CE=PIN_CS, DC=PIN_DC, RST=PIN_RST)
    lcd = ST7789(serial)
    sel = [int(ARGS[0])] if ARGS else range(1, len(CONFIGS) + 1)
    for n in sel:
        w, h, madctl, xo, yo = CONFIGS[n - 1]
        print(f"Config {n}: {w}x{h} MADCTL=0x{madctl:02X} x_off={xo} y_off={yo}"
              f"{' BGR' if BGR else ''}")
        lcd.init(madctl)
        # borra la RAM completa (240x320) sin offset
        lcd.blit(Image.new("RGB", (240, 320), "black"), 0, 0)
        lcd.blit(pattern(w, h, n), xo, yo)
        time.sleep(6)
    print("Fin.")


if __name__ == "__main__":
    main()
