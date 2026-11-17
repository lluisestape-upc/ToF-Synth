#!/bin/bash
# Configura main.py para que arranque solo al encender la Raspberry.
# Uso (una sola vez, desde la carpeta del repo):  bash install_autostart.sh
#
# Crea un servicio de usuario de systemd (tof-synth). Corre con tu usuario,
# así tiene acceso a GPIO, SPI, I2C y al audio igual que cuando lo lanzas a mano.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -n "$VIRTUAL_ENV" ]; then
    PY="$VIRTUAL_ENV/bin/python"
else
    PY="$(command -v python3)"
fi

mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/tof-synth.service" <<UNIT
[Unit]
Description=ToF Synth (main.py)
After=default.target pipewire.service pipewire-pulse.service

[Service]
WorkingDirectory=$DIR
ExecStartPre=/bin/sleep 3
ExecStart=$PY $DIR/main.py
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable tof-synth.service

# Arranca el servicio de usuario al encender, aunque nadie inicie sesión
sudo loginctl enable-linger "$USER"

systemctl --user restart tof-synth.service
echo
echo "Listo. main.py arrancará solo cada vez que enciendas la Raspberry."
echo "  Ver estado:     systemctl --user status tof-synth"
echo "  Ver mensajes:   journalctl --user -u tof-synth -f"
echo "  Parar:          systemctl --user stop tof-synth"
echo "  Desactivar:     systemctl --user disable --now tof-synth"
