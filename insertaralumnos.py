import sqlite3

conn = sqlite3.connect("servicioedu.db")
cur = conn.cursor()

cur.execute("""
ALTER TABLE chat_mensajes
ADD COLUMN centro_id INTEGER DEFAULT 1
""")

conn.commit()
conn.close()

print("Columna centro_id añadida correctamente.")
