import sqlite3
import hashlib

DB = "servicioedu.db"
usuario = "cheis"  # cámbialo por el usuario que quieras

# Nueva contraseña temporal
nueva_contra = "Temp-2024"
hash_pw = hashlib.sha256(nueva_contra.encode("utf-8")).hexdigest()

conn = sqlite3.connect(DB)
cursor = conn.cursor()

cursor.execute("""
UPDATE profesores
SET password = ?, password_temporal = 1
WHERE usuario = ?
""", (hash_pw, usuario))

conn.commit()
conn.close()

print(f"✔ Contraseña de {usuario} cambiada a {nueva_contra}")
