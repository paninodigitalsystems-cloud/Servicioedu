import sqlite3, hashlib

conn = sqlite3.connect("servicioedu.db")
cur = conn.cursor()

# Contraseña temporal original
temp = hashlib.sha256("profe1234".encode("utf-8")).hexdigest()

cur.execute("""
    UPDATE profesores
    SET password=NULL,
        password_temp=?,
        primer_inicio=1
    WHERE usuario='profe_demo'
""", (temp,))

conn.commit()
conn.close()

print("Profesor demo reiniciado correctamente")
