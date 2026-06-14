import time
import traceback

while True:
    try:
        from app import app

        print("Iniciando Panino Labs - servidor Flask...")
        app.run(host="0.0.0.0", port=5000, debug=False)
        print("El servidor Flask se detuvo. Reiniciando en 5 segundos...")
    except Exception:
        traceback.print_exc()
        print("Error detectado. Reiniciando la aplicación en 5 segundos...")
        time.sleep(5)
