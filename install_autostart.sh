#!/bin/bash
# Configura main.py para que arranque solo al encender la Raspberry.
# Uso (una sola vez, desde la carpeta del repo, SIN sudo delante):
#     bash install_autostart.sh
# Si usas un venv, actívalo antes de ejecutarlo.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
USR="$(id -un)"
UID_N="$(id -u)"
if [ -n "$VIRTUAL_ENV" ]; then
    PY="$VIRTUAL_ENV/bin/python"
else
    PY="$(command -v python3)"
fi

if [ "$UID_N" = "0" ]; then
    echo "Ejecútalo sin sudo:  bash install_autostart.sh"; exit 1
fi

echo "Usuario: $USR   Python: $PY   Carpeta: $DIR"

# 1) Comprobar que ese Python tiene las librerías
if ! "$PY" -c "import adafruit_rgb_display, sounddevice, gpiozero, adafruit_vl53l0x" 2>/dev/null; then
    echo
    echo "ERROR: $PY no encuentra las librerías de main.py."
    echo "Si usas un venv, actívalo (source .../bin/activate) y vuelve a ejecutar esto."
    exit 1
fi

# 2) Limpiar el intento anterior (servicio de usuario)
systemctl --user disable tof-synth.service 2>/dev/null || true
systemctl --user unmask  tof-synth.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/tof-synth.service"
systemctl --user daemon-reload 2>/dev/null || true

# 3) Que la sesión de audio del usuario (PipeWire) arranque sin iniciar sesión
sudo loginctl enable-linger "$USR"

# 4) Servicio del sistema
sudo tee /etc/systemd/system/tof-synth.service >/dev/null <<UNIT
[Unit]
Description=ToF Synth (main.py)
After=multi-user.target sound.target user@$UID_N.service
Wants=user@$UID_N.service

[Service]
Type=simple
User=$USR
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
Environment=XDG_RUNTIME_DIR=/run/user/$UID_N
ExecStartPre=/bin/sleep 8
ExecStart=$PY $DIR/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl unmask tof-synth.service 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl enable tof-synth.service
sudo systemctl restart tof-synth.service

echo
echo "Listo. main.py arrancará solo cada vez que enciendas la Raspberry"
echo "(tarda unos segundos más que el escritorio)."
echo "  Ver estado:    sudo systemctl status tof-synth"
echo "  Ver errores:   sudo journalctl -u tof-synth -b"
echo "  Parar:         sudo systemctl stop tof-synth"
echo "  Desactivar:    sudo systemctl disable --now tof-synth"
