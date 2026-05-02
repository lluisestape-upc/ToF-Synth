import time
import board
import busio
import digitalio
import adafruit_vl53l0x
import numpy as np
import sounddevice as sd
import soundfile as sf

# --- CONFIGURACIÓN MUSICAL ---
FREQ_BASE = 261.63  # Do
SAMPLING_RATE = 44100
BLOCK_SIZE = 512

# --- VARIABLES DE ESTADO ---
fase = 0.0
frecuencia_actual = FREQ_BASE
frecuencia_objetivo = FREQ_BASE
volumen_actual = 0.0
volumen_objetivo = 0.0

grabacion = []

def sintetizador_callback(outdata, frames, time_info, status):
    global fase, frecuencia_actual, volumen_actual, grabacion

    t = np.arange(frames) / SAMPLING_RATE

    frecuencia_actual += (frecuencia_objetivo - frecuencia_actual) * 0.15

    v_vel = 0.3 if volumen_objetivo > volumen_actual else 0.2
    volumen_actual += (volumen_objetivo - volumen_actual) * v_vel
    if volumen_actual < 0.001:
        volumen_actual = 0.0

    onda = np.sin(2 * np.pi * frecuencia_actual * t + fase) * volumen_actual
    fase = (fase + 2 * np.pi * frecuencia_actual * frames / SAMPLING_RATE) % (2 * np.pi)

    final_mix = onda.astype(np.float32)
    outdata[:] = final_mix.reshape(-1, 1)
    grabacion.append(final_mix.copy())

# --- CONFIGURACIÓN LEDS ---
led_activo = digitalio.DigitalInOut(board.D17)
led_activo.direction = digitalio.Direction.OUTPUT
led_reposo = digitalio.DigitalInOut(board.D27)
led_reposo.direction = digitalio.Direction.OUTPUT

led_activo.value = False
led_reposo.value = True

# --- INICIALIZACIÓN SENSOR ---
i2c = busio.I2C(board.SCL, board.SDA)
sensor = adafruit_vl53l0x.VL53L0X(i2c)
sensor.measurement_timing_budget = 20000
print("Sensor listo (0x29)")

# --- BUCLE PRINCIPAL ---
stream = sd.OutputStream(samplerate=SAMPLING_RATE, channels=1, callback=sintetizador_callback)
stream.start()

print("¡Arpa lista! (Do) | Grabando... Ctrl+C para finalizar.")

try:
    while True:
        dist = sensor.range
        if dist < 500:
            volumen_objetivo = 1.0
            ratio = dist / 500.0
            frecuencia_objetivo = FREQ_BASE * (1.0 + ratio)
            led_activo.value = True
            led_reposo.value = False
        else:
            volumen_objetivo = 0.0
            frecuencia_objetivo = FREQ_BASE
            led_activo.value = False
            led_reposo.value = True

        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nGuardando audio y cerrando...")
    audio_completo = np.concatenate(grabacion)
    sf.write('grabacion_arpa.wav', audio_completo, SAMPLING_RATE)
    print("Archivo 'grabacion_arpa.wav' creado.")
finally:
    stream.stop()
    led_activo.value = False
    led_reposo.value = False
