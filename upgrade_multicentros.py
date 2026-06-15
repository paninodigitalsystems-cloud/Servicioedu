import sqlite3

DB = "servicioedu.db"

conn = sqlite3.connect(DB)
cur = conn.cursor()

print("🔧 Reparando tabla CURSOS para multicentro...\n")

# 1) Comprobar si existe la tabla cursos
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursos'")
if not cur.fetchone():
    print("⛔ La tabla 'cursos' NO existe en tu base de datos.")
    conn.close()
    exit()

# 2) Comprobar columnas
cur.execute("PRAGMA table_info(cursos)")
columnas = [c[1] for c in cur.fetchall()]

# 3) Añadir centro_id si falta
if "centro_id" not in columnas:
    print("➕ Añadiendo columna centro_id a cursos...")
    cur.execute("ALTER TABLE cursos ADD COLUMN centro_id INTEGER DEFAULT 1")
else:
    print("✔ La tabla cursos ya tenía centro_id")

# 4) Asignar centro DEMO a filas existentes
cur.execute("UPDATE cursos SET centro_id = 1 WHERE centro_id IS NULL")

conn.commit()
conn.close()

print("\n🎉 Tabla CURSOS reparada correctamente.")
