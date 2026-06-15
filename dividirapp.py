# -*- coding: utf-8 -*-

ARCHIVO = "app.py"   # Cambia si tu archivo se llama distinto

def mostrar_archivo_entero():
    with open(ARCHIVO, "r", encoding="utf-8") as f:
        contenido = f.read()

    print("\n" + "="*80)
    print("📌 COPIA TODO LO QUE SALE DEBAJO Y PÉGALO EN COPILOT EN UN SOLO MENSAJE")
    print("="*80 + "\n")

    print(contenido)

    print("\n" + "="*80)
    print("📌 FIN — YA PUEDES COPIAR TODO EL TEXTO DE ARRIBA")
    print("="*80 + "\n")

if __name__ == "__main__":
    mostrar_archivo_entero()
