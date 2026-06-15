from flask import Flask, render_template, request, redirect, session, jsonify
import hashlib
import secrets
import sqlite3
import csv
import io
import os
import json
from datetime import datetime
from database import get_db

print("BASE DE DATOS REAL:", os.path.abspath("servicioedu.db"))

app = Flask(__name__)
app.secret_key = "TU_CLAVE_SECRETA"


# ============================
# HELPERS
# ============================

def get_centro_id():
    """Devuelve el centro_id de la sesión activa."""
    return session.get("centro_id")




def get_modo_mantenimiento():
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT, centro_id INTEGER)")
    centro_id = get_centro_id()
    if centro_id:
        row = cur.execute(
            "SELECT valor FROM config WHERE clave = 'modo_mantenimiento' AND centro_id = ?",
            (centro_id,)
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT valor FROM config WHERE clave = 'modo_mantenimiento'"
        ).fetchone()
    conn.close()
    return row["valor"] == "1" if row else False


def registrar_accion(usuario, accion):
    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO registros (usuario, accion, fecha, centro_id)
        VALUES (?, ?, datetime('now', 'localtime'), ?)
    """, (usuario, accion, get_centro_id()))
    conn.commit()
    conn.close()


def es_coordinador_o_tde():
    if "coordinador_id" in session:
        return True
    if "profesor_id" in session and "tde" in session.get("roles", []):
        return True
    return False


def puede_ver_hall_of_fame():
    if "coordinador_id" in session:
        return True
    if "profesor_id" in session:
        roles = session.get("roles", [])
        if "tde" in roles or "tecnico" in roles:
            return True
    return False


# ============================
# NUEVO HELPER SUPERADMIN
# ============================

def es_superadmin():
    """Devuelve True si el técnico activo tiene permiso superadmin."""
    return session.get("superadmin") is True


def require_superadmin():
    """Redirige si el usuario no es superadmin."""
    if not es_superadmin():
        return redirect("/panel_tecnico")
    return None


def _init_chat_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_mensajes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            profesor_usuario TEXT    NOT NULL,
            remitente        TEXT    NOT NULL CHECK(remitente IN ('profesor','tecnico')),
            mensaje          TEXT    NOT NULL,
            fecha            TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            leido            INTEGER NOT NULL DEFAULT 0,
            centro_id        INTEGER
        )
    """)
    conn.commit()


# ============================
# INICIO
# ============================

@app.route("/")
def index():
    return render_template("index.html")


# ============================
# REGISTRO DE CENTRO (NUEVO)
# ============================

@app.route("/registro-centro", methods=["GET", "POST"])
def registro_centro():
    if request.method == "GET":
        return render_template("registro_centro.html") if os.path.exists(
            os.path.join("templates", "registro_centro.html")
        ) else (
            "<form method='POST'>"
            "Centro: <input name='nombre_centro'><br>"
            "Admin usuario: <input name='usuario_admin'><br>"
            "Admin password: <input name='password_admin' type='password'><br>"
            "<button type='submit'>Crear centro</button>"
            "</form>"
        )

    data = request.get_json(silent=True) or request.form
    nombre_centro  = (data.get("nombre_centro") or "").strip()
    usuario_admin  = (data.get("usuario_admin") or "").strip()
    password_admin = (data.get("password_admin") or "").strip()

    if not nombre_centro or not usuario_admin or not password_admin:
        msg = "Faltan campos: nombre_centro, usuario_admin, password_admin"
        if request.is_json:
            return jsonify({"ok": False, "error": msg}), 400
        return msg, 400

    hash_pw = hashlib.sha256(password_admin.encode("utf-8")).hexdigest()

    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS centros (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre  TEXT NOT NULL UNIQUE,
            creado  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()

    if cur.execute("SELECT 1 FROM centros WHERE nombre = ?", (nombre_centro,)).fetchone():
        conn.close()
        msg = f"Ya existe un centro con el nombre '{nombre_centro}'"
        if request.is_json:
            return jsonify({"ok": False, "error": msg}), 409
        return msg, 409

    cur.execute("INSERT INTO centros (nombre) VALUES (?)", (nombre_centro,))
    centro_id = cur.lastrowid

    if cur.execute("SELECT 1 FROM coordinadores WHERE usuario = ?", (usuario_admin,)).fetchone():
        conn.close()
        msg = f"Ya existe un coordinador con el usuario '{usuario_admin}'"
        if request.is_json:
            return jsonify({"ok": False, "error": msg}), 409
        return msg, 409

    cur.execute("""
        INSERT INTO coordinadores (usuario, password, centro_id)
        VALUES (?, ?, ?)
    """, (usuario_admin, hash_pw, centro_id))
    conn.commit()
    conn.close()

    if request.is_json:
        return jsonify({"ok": True, "centro_id": centro_id, "nombre": nombre_centro})
    return f"Centro creado correctamente. centro_id={centro_id}"


# ============================
# MANTENIMIENTO
# ============================

@app.route("/mantenimiento")
def mantenimiento():
    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT, centro_id INTEGER)")

    if centro_id:
        cola = cur.execute(
            "SELECT COUNT(*) AS c FROM cola_banio WHERE centro_id = ?", (centro_id,)
        ).fetchone()["c"]
        pendientes = cur.execute(
            "SELECT COUNT(*) AS c FROM solicitudes_reset WHERE estado='pendiente' AND centro_id = ?",
            (centro_id,)
        ).fetchone()["c"]
    else:
        cola = cur.execute("SELECT COUNT(*) AS c FROM cola_banio").fetchone()["c"]
        pendientes = cur.execute(
            "SELECT COUNT(*) AS c FROM solicitudes_reset WHERE estado='pendiente'"
        ).fetchone()["c"]

    demanda = cola + pendientes
    conn.close()

    return render_template("mantenimiento.html", cola=cola, pendientes=pendientes, demanda=demanda)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("index.html")

    usuario = request.form["usuario"]
    password = request.form["password"]
    hash_pw = hashlib.sha256(password.encode("utf-8")).hexdigest()

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ============================
    # LOGIN COORDINADOR
    # ============================
    coordinador = cur.execute(
        "SELECT * FROM coordinadores WHERE usuario=?", (usuario,)
    ).fetchone()

    if coordinador:
        conn.close()
        if hash_pw != coordinador["password"]:
            return render_template("index.html", error="Contraseña incorrecta")

        session.clear()
        session.permanent = True
        session["coordinador_id"] = coordinador["id"]
        session["usuario"] = coordinador["usuario"]
        session["rol"] = "tde"
        session["centro_id"] = coordinador["centro_id"]

        return redirect("/panel_tde")

    # ============================
    # LOGIN CONSERJERÍA
    # ============================
    conserje = cur.execute(
        "SELECT * FROM conserjeria WHERE usuario=?", (usuario,)
    ).fetchone()

    if conserje:
        conn.close()
        if hash_pw != conserje["password"]:
            return render_template("index.html", error="Contraseña incorrecta")

        session.clear()
        session.permanent = True
        session["conserjeria_id"] = conserje["id"]
        session["usuario"] = conserje["usuario"]
        session["rol"] = "conserjeria"
        session["centro_id"] = conserje["centro_id"]

        return redirect("/conserjeria")

    # ============================
    # LOGIN PROFESOR / TÉCNICO
    # ============================
    profesor = cur.execute(
        "SELECT * FROM profesores WHERE usuario=?", (usuario,)
    ).fetchone()
    conn.close()

    if not profesor:
        return render_template("index.html", error="Usuario no encontrado")

    roles_profesor = [r.strip() for r in profesor["rol"].split(",") if r.strip()]

    # ── Detectar superadmin ──────────────────────────────────────────────
    # El campo superadmin=1 en la tabla profesores activa permisos globales.
    # El rol sigue siendo "tecnico" — no cambia nada más.
    keys_disponibles = profesor.keys() if hasattr(profesor, "keys") else []
    es_super = bool(profesor["superadmin"]) if "superadmin" in keys_disponibles else False

    # Mantenimiento (solo bloquea a no técnicos)
    if get_modo_mantenimiento() and "tecnico" not in roles_profesor and not es_super:
        return redirect("/mantenimiento")

    # ============================
    # PRIMER INICIO
    # ============================
    if profesor["primer_inicio"] == 1:
        if password != profesor["password_temp"]:
            return render_template("index.html", error="Contraseña temporal incorrecta")

        session.clear()
        session.permanent = True
        session["profesor_id"] = profesor["id"]
        session["usuario"] = profesor["usuario"]
        session["profesor_usuario"] = profesor["usuario"]
        session["rol"] = profesor["rol"]
        session["roles"] = roles_profesor
        session["centro_id"] = profesor["centro_id"]
        session["superadmin"] = es_super

        return render_template("primer_inicio.html")

    # ============================
    # CONTRASEÑA INCORRECTA
    # ============================
    if profesor["password"] is None or hash_pw != profesor["password"]:
        return render_template("index.html", error="Contraseña incorrecta")

    # ============================
    # LOGIN CORRECTO
    # ============================
    session.clear()
    session.permanent = True
    session["profesor_id"] = profesor["id"]
    session["usuario"] = profesor["usuario"]
    session["profesor_usuario"] = profesor["usuario"]
    session["rol"] = profesor["rol"]
    session["roles"] = roles_profesor
    session["centro_id"] = profesor["centro_id"]
    session["superadmin"] = es_super          # ← NUEVO: se guarda True/False

    # ============================
    # REDIRECCIONES POR ROL
    # El superadmin va al panel_tecnico (mismo panel, funciones extra)
    # ============================
    if "tde" in roles_profesor:
        return redirect("/panel_tde")
    elif "tecnico" in roles_profesor:
        if es_super:
            return redirect("/panel_superadmin")   # <-- superadmin va aquí
        return redirect("/panel_tecnico")     # ← igual para técnico normal y superadmin
    else:
        return redirect("/panel")


# ============================
# CAMBIAR CONTRASEÑA (primer inicio)
# ============================

@app.route("/cambiar_password", methods=["POST"])
def cambiar_password():
    if "profesor_id" not in session:
        return redirect("/")

    nueva = request.form["nueva"]
    confirmar = request.form["confirmar"]

    if nueva != confirmar:
        return render_template("primer_inicio.html", error="Las contraseñas no coinciden")

    hash_pw = hashlib.sha256(nueva.encode("utf-8")).hexdigest()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE profesores
        SET password=?, password_temp=NULL, primer_inicio=0
        WHERE id=? AND centro_id=?
    """, (hash_pw, session["profesor_id"], get_centro_id()))
    conn.commit()
    conn.close()

    session["mensaje_ok"] = "Contraseña cambiada correctamente"
    session["mostrar_tutorial"] = True

    if "roles" not in session:
        session["roles"] = [r.strip() for r in session.get("rol", "").split(",") if r.strip()]

    if "tde" in session.get("roles", []):
        return redirect("/panel_tde")
    elif "tecnico" in session.get("roles", []):
        return redirect("/panel_tecnico")
    else:
        return redirect("/primer_datos")


@app.route("/primer_datos")
def primer_datos():
    if "profesor_id" not in session:
        return redirect("/")
    return render_template("primer_datos.html")


@app.route("/guardar_datos", methods=["POST"])
def guardar_datos():
    if "profesor_id" not in session:
        return redirect("/")

    nombre = request.form.get("nombre", "").strip()
    email  = request.form.get("email", "").strip()
    centro = request.form.get("centro", "").strip()

    if not nombre or not email or not centro:
        return render_template("primer_datos.html", error="Rellena todos los campos")

    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    cur.execute("""
        UPDATE profesores
        SET nombre=?, email=?, centro=?, datos_completados=1
        WHERE id=? AND centro_id=?
    """, (nombre, email, centro, session["profesor_id"], get_centro_id()))
    conn.commit()
    conn.close()

    return redirect("/panel")


@app.route("/actualizar_datos", methods=["POST"])
def actualizar_datos():
    if "profesor_id" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401

    data = request.get_json()
    nombre = data.get("nombre", "")
    email  = data.get("email", "")
    centro = data.get("centro", "")

    if not nombre or not email or not centro:
        return jsonify({"ok": False, "error": "Rellena todos los campos."})

    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    cur.execute("""
        UPDATE profesores
        SET nombre=?, email=?, centro=?
        WHERE id=? AND centro_id=?
    """, (nombre, email, centro, session["profesor_id"], get_centro_id()))
    conn.commit()
    conn.close()

    return jsonify({"ok": True})


# ============================
# LOGOUT
# ============================

@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect("/login")


# ============================
# PANEL PROFESOR
# ============================

@app.route("/panel")
def panel():
    if "profesor_id" not in session:
        return redirect("/")

    mensaje_ok    = session.pop("mensaje_ok", None)
    mensaje_error = session.pop("mensaje_error", None)
    mostrar_tutorial = session.pop("mostrar_tutorial", False)

    curso_id  = request.args.get("curso_id")
    centro_id = get_centro_id()

    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT, centro_id INTEGER)")
    if centro_id:
        mantenimiento_row = cur.execute(
            "SELECT valor FROM config WHERE clave = 'modo_mantenimiento' AND centro_id = ?",
            (centro_id,)
        ).fetchone()
    else:
        mantenimiento_row = cur.execute(
            "SELECT valor FROM config WHERE clave = 'modo_mantenimiento'"
        ).fetchone()
    modo_mantenimiento = mantenimiento_row["valor"] == "1" if mantenimiento_row else False

    if modo_mantenimiento and "tecnico" not in session.get("roles", []):
        conn.close()
        return redirect("/mantenimiento")

    if centro_id:
        cur.execute("SELECT * FROM cursos WHERE centro_id = ? ORDER BY nombre ASC", (centro_id,))
    else:
        cur.execute("SELECT * FROM cursos ORDER BY nombre ASC")
    cursos = cur.fetchall()

    alumnos = []
    if curso_id:
        row = cur.execute("SELECT nombre FROM cursos WHERE id = ?", (curso_id,)).fetchone()
        if row:
            if centro_id:
                cur.execute(
                    "SELECT * FROM alumnos WHERE curso = ? AND centro_id = ? ORDER BY nombre ASC",
                    (row["nombre"], centro_id)
                )
            else:
                cur.execute(
                    "SELECT * FROM alumnos WHERE curso = ? ORDER BY nombre ASC",
                    (row["nombre"],)
                )
            alumnos = cur.fetchall()

    if centro_id:
        cur.execute("""
            SELECT
                en_banio.id,
                alumnos.nombre AS alumno,
                alumnos.curso,
                alumnos.genero,
                en_banio.hora_entrada,
                CAST((strftime('%s','now') - strftime('%s', en_banio.hora_entrada)) / 60 AS INT) AS minutos
            FROM en_banio
            JOIN alumnos ON alumnos.id = en_banio.alumno_id
            WHERE en_banio.centro_id = ?
            ORDER BY en_banio.hora_entrada ASC
        """, (centro_id,))
    else:
        cur.execute("""
            SELECT
                en_banio.id,
                alumnos.nombre AS alumno,
                alumnos.curso,
                alumnos.genero,
                en_banio.hora_entrada,
                CAST((strftime('%s','now') - strftime('%s', en_banio.hora_entrada)) / 60 AS INT) AS minutos
            FROM en_banio
            JOIN alumnos ON alumnos.id = en_banio.alumno_id
            ORDER BY en_banio.hora_entrada ASC
        """)
    en_banio = [dict(r) for r in cur.fetchall()]

    def estado_color(minutos):
        if minutos < 5:    return "verde"
        elif minutos < 10: return "amarillo"
        return "rojo"

    def progreso(minutos):
        return int((min(minutos, 15) / 15) * 100)

    for a in en_banio:
        a["estado_color"] = estado_color(a["minutos"])
        a["progreso"]     = progreso(a["minutos"])

    if centro_id:
        cur.execute("""
            SELECT salud.id, alumnos.nombre AS alumno, alumnos.curso, alumnos.genero,
                   salud.hora_salida,
                   CAST((strftime('%s','now') - strftime('%s', salud.hora_salida)) / 60 AS INT) AS minutos
            FROM salud
            JOIN alumnos ON alumnos.id = salud.alumno_id
            WHERE salud.centro_id = ?
            ORDER BY salud.hora_salida ASC
        """, (centro_id,))
    else:
        cur.execute("""
            SELECT salud.id, alumnos.nombre AS alumno, alumnos.curso, alumnos.genero,
                   salud.hora_salida,
                   CAST((strftime('%s','now') - strftime('%s', salud.hora_salida)) / 60 AS INT) AS minutos
            FROM salud
            JOIN alumnos ON alumnos.id = salud.alumno_id
            ORDER BY salud.hora_salida ASC
        """)
    salud_actual = cur.fetchall()

    if centro_id:
        cur.execute("""
            SELECT cola_banio.id, alumnos.nombre AS alumno, alumnos.curso, alumnos.genero,
                   cola_banio.orden
            FROM cola_banio
            JOIN alumnos ON alumnos.id = cola_banio.alumno_id
            WHERE cola_banio.centro_id = ?
            ORDER BY cola_banio.orden ASC
        """, (centro_id,))
    else:
        cur.execute("""
            SELECT cola_banio.id, alumnos.nombre AS alumno, alumnos.curso, alumnos.genero,
                   cola_banio.orden
            FROM cola_banio
            JOIN alumnos ON alumnos.id = cola_banio.alumno_id
            ORDER BY cola_banio.orden ASC
        """)
    cola_banio = cur.fetchall()

    if centro_id:
        cur.execute("""
            SELECT historial_banio.id, alumnos.nombre AS alumno, alumnos.curso,
                   historial_banio.hora_entrada, historial_banio.hora_salida, historial_banio.minutos
            FROM historial_banio
            JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            WHERE historial_banio.centro_id = ?
            ORDER BY historial_banio.id DESC LIMIT 50
        """, (centro_id,))
    else:
        cur.execute("""
            SELECT historial_banio.id, alumnos.nombre AS alumno, alumnos.curso,
                   historial_banio.hora_entrada, historial_banio.hora_salida, historial_banio.minutos
            FROM historial_banio
            JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            ORDER BY historial_banio.id DESC LIMIT 50
        """)
    historial_banio = cur.fetchall()

    if centro_id:
        cur.execute("""
            SELECT historial_global.id, alumnos.nombre AS alumno, alumnos.curso, alumnos.genero,
                   historial_global.hora_salida, historial_global.hora_regreso, historial_global.estado
            FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE DATE(hora_salida) = DATE('now') AND historial_global.centro_id = ?
            ORDER BY historial_global.id DESC
        """, (centro_id,))
    else:
        cur.execute("""
            SELECT historial_global.id, alumnos.nombre AS alumno, alumnos.curso, alumnos.genero,
                   historial_global.hora_salida, historial_global.hora_regreso, historial_global.estado
            FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE DATE(hora_salida) = DATE('now')
            ORDER BY historial_global.id DESC
        """)

    def icono_estado(estado):
        if estado == "salida":   return "🟡"
        elif estado == "regreso": return "🟢"
        return "⚪"

    historial_global = []
    for h in cur.fetchall():
        h = dict(h)
        h["icono"] = icono_estado(h["estado"])
        historial_global.append(h)

    conn.close()

    return render_template(
        "panel.html",
        mensaje_ok=mensaje_ok,
        mensaje_error=mensaje_error,
        mostrar_tutorial=mostrar_tutorial,
        cursos=cursos,
        alumnos=alumnos,
        curso_seleccionado=curso_id,
        en_banio=en_banio,
        salud_actual=salud_actual,
        cola_banio=cola_banio,
        historial_banio=historial_banio,
        historial_global=historial_global,
        roles=session.get("roles", [])
    )


# ============================
# BAÑO
# ============================

@app.route("/banio", methods=["POST"])
def banio():
    alumno_id = request.form.get("id")
    if not alumno_id:
        return redirect("/panel")

    centro_id = get_centro_id()
    conn = get_db()
    cur = conn.cursor()

    if centro_id:
        alumno = cur.execute(
            "SELECT genero FROM alumnos WHERE id = ? AND centro_id = ?", (alumno_id, centro_id)
        ).fetchone()
    else:
        alumno = cur.execute(
            "SELECT genero FROM alumnos WHERE id = ?", (alumno_id,)
        ).fetchone()

    if not alumno:
        conn.close()
        return redirect("/panel")

    if centro_id:
        en_banio_check = cur.execute(
            "SELECT 1 FROM en_banio WHERE alumno_id = ? AND centro_id = ?", (alumno_id, centro_id)
        ).fetchone()
        cola_check = cur.execute(
            "SELECT 1 FROM cola_banio WHERE alumno_id = ? AND centro_id = ?", (alumno_id, centro_id)
        ).fetchone()
    else:
        en_banio_check = cur.execute("SELECT 1 FROM en_banio WHERE alumno_id = ?", (alumno_id,)).fetchone()
        cola_check     = cur.execute("SELECT 1 FROM cola_banio WHERE alumno_id = ?", (alumno_id,)).fetchone()

    if en_banio_check:
        session["mensaje_error"] = "Este alumno ya está registrado en el baño."
        conn.close()
        return redirect("/panel")

    if cola_check:
        session["mensaje_error"] = "Este alumno ya está esperando en la cola del baño."
        conn.close()
        return redirect("/panel")

    if centro_id:
        mismo_genero = cur.execute("""
            SELECT 1 FROM en_banio
            JOIN alumnos ON alumnos.id = en_banio.alumno_id
            WHERE alumnos.genero = ? AND en_banio.centro_id = ? LIMIT 1
        """, (alumno["genero"], centro_id)).fetchone()
    else:
        mismo_genero = cur.execute("""
            SELECT 1 FROM en_banio
            JOIN alumnos ON alumnos.id = en_banio.alumno_id
            WHERE alumnos.genero = ? LIMIT 1
        """, (alumno["genero"],)).fetchone()

    if mismo_genero:
        if centro_id:
            orden = cur.execute(
                "SELECT COALESCE(MAX(orden), 0) + 1 FROM cola_banio WHERE centro_id = ?", (centro_id,)
            ).fetchone()[0]
            cur.execute(
                "INSERT INTO cola_banio (alumno_id, genero, orden, centro_id) VALUES (?, ?, ?, ?)",
                (alumno_id, alumno["genero"], orden, centro_id)
            )
        else:
            orden = cur.execute(
                "SELECT COALESCE(MAX(orden), 0) + 1 FROM cola_banio"
            ).fetchone()[0]
            cur.execute(
                "INSERT INTO cola_banio (alumno_id, genero, orden) VALUES (?, ?, ?)",
                (alumno_id, alumno["genero"], orden)
            )
        cur.execute("UPDATE alumnos SET autorizado = 1 WHERE id = ?", (alumno_id,))
        session["mensaje_ok"] = "Alumno añadido a la cola del baño."
        conn.commit()
        conn.close()
        return redirect("/panel")

    hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if centro_id:
        cur.execute(
            "INSERT INTO historial_global (alumno_id, hora_salida, estado, centro_id) VALUES (?, ?, 'salida', ?)",
            (alumno_id, hora, centro_id)
        )
        cur.execute(
            "INSERT INTO en_banio (alumno_id, hora_entrada, centro_id) VALUES (?, ?, ?)",
            (alumno_id, hora, centro_id)
        )
    else:
        cur.execute(
            "INSERT INTO historial_global (alumno_id, hora_salida, estado) VALUES (?, ?, 'salida')",
            (alumno_id, hora)
        )
        cur.execute(
            "INSERT INTO en_banio (alumno_id, hora_entrada) VALUES (?, ?)",
            (alumno_id, hora)
        )
    cur.execute("UPDATE alumnos SET autorizado = 1 WHERE id = ?", (alumno_id,))
    session["mensaje_ok"] = "Alumno registrado en el baño."
    conn.commit()
    conn.close()
    return redirect("/panel")


@app.route("/cola_banio/entrar/<int:cola_id>", methods=["POST"])
def cola_banio_entrar(cola_id):
    if "profesor_id" not in session:
        return redirect("/login")

    centro_id = get_centro_id()
    conn = get_db()
    cur = conn.cursor()

    if centro_id:
        fila = cur.execute(
            "SELECT id, alumno_id, genero FROM cola_banio WHERE id = ? AND centro_id = ?",
            (cola_id, centro_id)
        ).fetchone()
    else:
        fila = cur.execute(
            "SELECT id, alumno_id, genero FROM cola_banio WHERE id = ?", (cola_id,)
        ).fetchone()

    if not fila:
        conn.close()
        return redirect("/panel")

    if centro_id:
        mismo_genero = cur.execute("""
            SELECT 1 FROM en_banio
            JOIN alumnos ON alumnos.id = en_banio.alumno_id
            WHERE alumnos.genero = ? AND en_banio.centro_id = ? LIMIT 1
        """, (fila["genero"], centro_id)).fetchone()
    else:
        mismo_genero = cur.execute("""
            SELECT 1 FROM en_banio
            JOIN alumnos ON alumnos.id = en_banio.alumno_id
            WHERE alumnos.genero = ? LIMIT 1
        """, (fila["genero"],)).fetchone()

    if mismo_genero:
        session["mensaje_error"] = "Aún hay un alumno del mismo género en el baño."
        conn.close()
        return redirect("/panel")

    hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if centro_id:
        cur.execute(
            "INSERT INTO historial_global (alumno_id, hora_salida, estado, centro_id) VALUES (?, ?, 'salida', ?)",
            (fila["alumno_id"], hora, centro_id)
        )
        cur.execute(
            "INSERT INTO en_banio (alumno_id, hora_entrada, centro_id) VALUES (?, ?, ?)",
            (fila["alumno_id"], hora, centro_id)
        )
    else:
        cur.execute(
            "INSERT INTO historial_global (alumno_id, hora_salida, estado) VALUES (?, ?, 'salida')",
            (fila["alumno_id"], hora)
        )
        cur.execute(
            "INSERT INTO en_banio (alumno_id, hora_entrada) VALUES (?, ?)",
            (fila["alumno_id"], hora)
        )
    cur.execute("DELETE FROM cola_banio WHERE id = ?", (cola_id,))
    session["mensaje_ok"] = "Alumno autorizado para entrar al baño."
    conn.commit()
    conn.close()
    return redirect("/panel")


@app.route("/salir_banio/<int:id>", methods=["POST"])
def salir_banio(id):
    centro_id = get_centro_id()
    conn = get_db()
    cur = conn.cursor()

    if centro_id:
        row = cur.execute(
            "SELECT alumno_id, hora_entrada FROM en_banio WHERE id=? AND centro_id=?",
            (id, centro_id)
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT alumno_id, hora_entrada FROM en_banio WHERE id=?", (id,)
        ).fetchone()

    if row:
        hora_salida = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            SELECT CAST((strftime('%s', ?) - strftime('%s', ?)) / 60 AS INT)
        """, (hora_salida, row["hora_entrada"]))
        minutos = cur.fetchone()[0]

        if centro_id:
            cur.execute("""
                INSERT INTO historial_banio (alumno_id, hora_entrada, hora_salida, minutos, centro_id)
                VALUES (?, ?, ?, ?, ?)
            """, (row["alumno_id"], row["hora_entrada"], hora_salida, minutos, centro_id))
        else:
            cur.execute("""
                INSERT INTO historial_banio (alumno_id, hora_entrada, hora_salida, minutos)
                VALUES (?, ?, ?, ?)
            """, (row["alumno_id"], row["hora_entrada"], hora_salida, minutos))
        cur.execute("DELETE FROM en_banio WHERE id=?", (id,))

    conn.commit()
    conn.close()
    return redirect("/panel")


@app.route("/volver", methods=["POST"])
def volver():
    if "profesor_id" not in session:
        return jsonify({"ok": False, "error": "No autenticado"})

    id_registro = request.form.get("id")
    if not id_registro:
        return jsonify({"ok": False, "error": "Falta ID"})

    centro_id = get_centro_id()
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if centro_id:
        registro = cur.execute(
            "SELECT alumno_id FROM en_banio WHERE id = ? AND centro_id = ?",
            (id_registro, centro_id)
        ).fetchone()
    else:
        registro = cur.execute(
            "SELECT alumno_id FROM en_banio WHERE id = ?", (id_registro,)
        ).fetchone()

    if not registro:
        conn.close()
        return jsonify({"ok": True})

    alumno_id    = registro["alumno_id"]
    hora_regreso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if centro_id:
        fila_hist = cur.execute("""
            SELECT id FROM historial_global
            WHERE alumno_id = ? AND hora_regreso IS NULL AND centro_id = ?
            ORDER BY id DESC LIMIT 1
        """, (alumno_id, centro_id)).fetchone()
    else:
        fila_hist = cur.execute("""
            SELECT id FROM historial_global
            WHERE alumno_id = ? AND hora_regreso IS NULL
            ORDER BY id DESC LIMIT 1
        """, (alumno_id,)).fetchone()

    if fila_hist:
        cur.execute("""
            UPDATE historial_global
            SET hora_regreso = ?, estado = 'regreso'
            WHERE id = ?
        """, (hora_regreso, fila_hist["id"]))

    cur.execute("UPDATE alumnos SET autorizado = 0 WHERE id = ?", (alumno_id,))
    cur.execute("DELETE FROM en_banio WHERE id = ?", (id_registro,))

    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ============================
# SALUD
# ============================

@app.route("/salir_salud", methods=["POST"])
def salir_salud():
    if "profesor_id" not in session:
        return redirect("/login")

    alumno_id = request.form.get("alumno_id")
    if not alumno_id:
        return redirect("/panel")

    centro_id = get_centro_id()
    conn = get_db()
    if centro_id:
        conn.execute("""
            INSERT INTO salud (alumno_id, descripcion, hora_salida, centro_id)
            VALUES (?, 'salud', time('now','localtime'), ?)
        """, (alumno_id, centro_id))
        conn.execute("""
            INSERT INTO historial (alumno_id, accion, hora, estado, motivo, fecha, centro_id)
            VALUES (?, 'salida_salud', time('now','localtime'), 'fuera', 'salud', date('now'), ?)
        """, (alumno_id, centro_id))
    else:
        conn.execute("""
            INSERT INTO salud (alumno_id, descripcion, hora_salida)
            VALUES (?, 'salud', time('now','localtime'))
        """, (alumno_id,))
        conn.execute("""
            INSERT INTO historial (alumno_id, accion, hora, estado, motivo, fecha)
            VALUES (?, 'salida_salud', time('now','localtime'), 'fuera', 'salud', date('now'))
        """, (alumno_id,))
    conn.commit()
    conn.close()
    return redirect("/panel")


@app.route("/regreso_salud", methods=["POST"])
def regreso_salud():
    if "profesor_id" not in session:
        return redirect("/login")

    id_registro = request.form.get("id")
    if not id_registro:
        return redirect("/panel")

    centro_id = get_centro_id()
    conn = get_db()
    if centro_id:
        registro = conn.execute(
            "SELECT alumno_id FROM salud WHERE id = ? AND centro_id = ?", (id_registro, centro_id)
        ).fetchone()
    else:
        registro = conn.execute(
            "SELECT alumno_id FROM salud WHERE id = ?", (id_registro,)
        ).fetchone()

    if not registro:
        conn.close()
        return redirect("/panel")

    if centro_id:
        conn.execute("""
            INSERT INTO historial (alumno_id, accion, hora, estado, motivo, fecha, centro_id)
            VALUES (?, 'regreso_salud', time('now','localtime'), 'regreso', 'salud', date('now'), ?)
        """, (registro["alumno_id"], centro_id))
    else:
        conn.execute("""
            INSERT INTO historial (alumno_id, accion, hora, estado, motivo, fecha)
            VALUES (?, 'regreso_salud', time('now','localtime'), 'regreso', 'salud', date('now'))
        """, (registro["alumno_id"],))
    conn.execute("UPDATE salud SET hora_regreso = time('now','localtime') WHERE id = ?", (id_registro,))
    conn.execute("DELETE FROM salud WHERE id = ?", (id_registro,))
    conn.commit()
    conn.close()
    return redirect("/panel")


# ============================
# PANEL TDE
# ============================

@app.route("/panel_tde")
def panel_tde():
    if not es_coordinador_o_tde():
        return redirect("/login")

    mensaje_ok       = session.pop("mensaje_ok", None)
    mostrar_tutorial = session.pop("mostrar_tutorial", False)

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if centro_id:
        pendientes = cur.execute(
            "SELECT COUNT(*) AS total FROM solicitudes_reset WHERE estado='pendiente' AND centro_id = ?",
            (centro_id,)
        ).fetchone()["total"]
        historial_reciente = cur.execute("""
            SELECT historial_global.id, alumnos.nombre AS alumno,
                   historial_global.hora_salida, historial_global.hora_regreso, historial_global.estado
            FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE historial_global.centro_id = ?
            ORDER BY historial_global.id DESC LIMIT 6
        """, (centro_id,)).fetchall()
    else:
        pendientes = cur.execute(
            "SELECT COUNT(*) AS total FROM solicitudes_reset WHERE estado='pendiente'"
        ).fetchone()["total"]
        historial_reciente = cur.execute("""
            SELECT historial_global.id, alumnos.nombre AS alumno,
                   historial_global.hora_salida, historial_global.hora_regreso, historial_global.estado
            FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id
            ORDER BY historial_global.id DESC LIMIT 6
        """).fetchall()
    conn.close()

    return render_template(
        "panel_tde.html",
        usuario=session.get("usuario"),
        mensaje_ok=mensaje_ok,
        mostrar_tutorial=mostrar_tutorial,
        pendientes=pendientes,
        historial_reciente=historial_reciente
    )


# ============================
# PANEL TÉCNICO
# ============================

@app.route("/panel_tecnico")
def panel_tecnico():
    if "profesor_id" not in session or "tecnico" not in session.get("roles", []):
        return redirect("/panel")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT, centro_id INTEGER)")
    conn.commit()

    if centro_id:
        total_profesores  = cur.execute("SELECT COUNT(*) AS c FROM profesores WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_alumnos     = cur.execute("SELECT COUNT(*) AS c FROM alumnos WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_cursos      = cur.execute("SELECT COUNT(*) AS c FROM cursos WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_solicitudes = cur.execute(
            "SELECT COUNT(*) AS c FROM solicitudes_reset WHERE estado='pendiente' AND centro_id = ?",
            (centro_id,)
        ).fetchone()["c"]
        total_cola  = cur.execute("SELECT COUNT(*) AS c FROM cola_banio WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        cola_chicos = cur.execute("SELECT COUNT(*) AS c FROM cola_banio WHERE genero='M' AND centro_id = ?", (centro_id,)).fetchone()["c"]
        cola_chicas = cur.execute("SELECT COUNT(*) AS c FROM cola_banio WHERE genero='F' AND centro_id = ?", (centro_id,)).fetchone()["c"]
        mant = cur.execute(
            "SELECT valor FROM config WHERE clave = 'modo_mantenimiento' AND centro_id = ?", (centro_id,)
        ).fetchone()
        ultimos_registros = cur.execute("""
            SELECT historial_global.id, alumnos.nombre AS alumno,
                   historial_global.hora_salida, historial_global.hora_regreso, historial_global.estado
            FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE historial_global.centro_id = ?
            ORDER BY historial_global.id DESC LIMIT 6
        """, (centro_id,)).fetchall()
    else:
        total_profesores  = cur.execute("SELECT COUNT(*) AS c FROM profesores").fetchone()["c"]
        total_alumnos     = cur.execute("SELECT COUNT(*) AS c FROM alumnos").fetchone()["c"]
        total_cursos      = cur.execute("SELECT COUNT(*) AS c FROM cursos").fetchone()["c"]
        total_solicitudes = cur.execute(
            "SELECT COUNT(*) AS c FROM solicitudes_reset WHERE estado='pendiente'"
        ).fetchone()["c"]
        total_cola  = cur.execute("SELECT COUNT(*) AS c FROM cola_banio").fetchone()["c"]
        cola_chicos = cur.execute("SELECT COUNT(*) AS c FROM cola_banio WHERE genero='M'").fetchone()["c"]
        cola_chicas = cur.execute("SELECT COUNT(*) AS c FROM cola_banio WHERE genero='F'").fetchone()["c"]
        mant = cur.execute(
            "SELECT valor FROM config WHERE clave = 'modo_mantenimiento'"
        ).fetchone()
        ultimos_registros = cur.execute("""
            SELECT historial_global.id, alumnos.nombre AS alumno,
                   historial_global.hora_salida, historial_global.hora_regreso, historial_global.estado
            FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id
            ORDER BY historial_global.id DESC LIMIT 6
        """).fetchall()

    demanda = total_solicitudes + total_cola
    modo_mantenimiento = mant["valor"] == "1" if mant else False

    # ── Datos extra para superadmin ──────────────────────────────────────
    # Solo se calculan si el técnico tiene superadmin=True en sesión.
    # El técnico normal nunca ejecuta este bloque.
    centros_global = []
    stats_global   = {}
    if es_superadmin():
        cur.execute("CREATE TABLE IF NOT EXISTS centros (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE, creado TEXT DEFAULT (datetime('now','localtime')))")
        conn.commit()
        centros_rows = cur.execute("SELECT * FROM centros ORDER BY nombre ASC").fetchall()
        for c in centros_rows:
            cid = c["id"]
            profes  = cur.execute("SELECT COUNT(*) AS n FROM profesores WHERE centro_id=?", (cid,)).fetchone()["n"]
            alumnos = cur.execute("SELECT COUNT(*) AS n FROM alumnos WHERE centro_id=?", (cid,)).fetchone()["n"]
            cursos  = cur.execute("SELECT COUNT(*) AS n FROM cursos WHERE centro_id=?", (cid,)).fetchone()["n"]
            en_b    = cur.execute("SELECT COUNT(*) AS n FROM en_banio WHERE centro_id=?", (cid,)).fetchone()["n"]
            hist    = cur.execute("SELECT COUNT(*) AS n FROM historial_global WHERE centro_id=?", (cid,)).fetchone()["n"]
            cola_c  = cur.execute("SELECT COUNT(*) AS n FROM cola_banio WHERE centro_id=?", (cid,)).fetchone()["n"]
            hoy_c   = cur.execute(
                "SELECT COUNT(*) AS n FROM historial_global WHERE centro_id=? AND DATE(hora_salida)=DATE('now')", (cid,)
            ).fetchone()["n"]
            mant_c  = cur.execute(
                "SELECT valor FROM config WHERE clave='modo_mantenimiento' AND centro_id=?", (cid,)
            ).fetchone()
            centros_global.append({
                "id":           cid,
                "nombre":       c["nombre"],
                "creado":       c["creado"],
                "profesores":   profes,
                "alumnos":      alumnos,
                "cursos":       cursos,
                "en_banio":     en_b,
                "historial":    hist,
                "cola":         cola_c,
                "hoy":          hoy_c,
                "mantenimiento": mant_c["valor"] == "1" if mant_c else False,
            })

        stats_global = {
            "total_centros":    len(centros_global),
            "total_profesores": cur.execute("SELECT COUNT(*) AS n FROM profesores").fetchone()["n"],
            "total_alumnos":    cur.execute("SELECT COUNT(*) AS n FROM alumnos").fetchone()["n"],
            "total_en_banio":   cur.execute("SELECT COUNT(*) AS n FROM en_banio").fetchone()["n"],
            "total_hoy":        cur.execute(
                "SELECT COUNT(*) AS n FROM historial_global WHERE DATE(hora_salida)=DATE('now')"
            ).fetchone()["n"],
        }

    conn.close()

    return render_template(
        "panel_tecnico.html",
        usuario=session.get("usuario"),
        roles=session.get("roles", []),
        total_profesores=total_profesores,
        total_alumnos=total_alumnos,
        total_cursos=total_cursos,
        total_solicitudes=total_solicitudes,
        total_cola=total_cola,
        cola_chicos=cola_chicos,
        cola_chicas=cola_chicas,
        demanda=demanda,
        ultimos_registros=ultimos_registros,
        modo_mantenimiento=modo_mantenimiento,
        # ── nuevas variables para superadmin (vacías para técnico normal) ─
        centros_global=centros_global,
        stats_global=stats_global,
        centro_activo=get_centro_id(),
    )


# ============================
# RUTAS SUPERADMIN
# ============================

@app.route("/superadmin/cambiar_centro/<int:centro_id>")
def superadmin_cambiar_centro(centro_id):
    """Cambia el centro_id activo en sesión. Solo superadmin."""
    if not es_superadmin():
        return redirect("/panel_tecnico")

    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    centro = cur.execute("SELECT id, nombre FROM centros WHERE id = ?", (centro_id,)).fetchone()
    conn.close()

    if not centro:
        session["mensaje_error"] = "Centro no encontrado."
        return redirect("/panel_tecnico")

    session["centro_id"]     = centro["id"]
    session["centro_nombre"] = centro["nombre"]
    session["mensaje_ok"]    = f"Ahora gestionando: {centro['nombre']}"
    return redirect("/panel_tecnico")


@app.route("/superadmin/salir_centro")
def superadmin_salir_centro():
    """Elimina el filtro de centro activo. Solo superadmin."""
    if not es_superadmin():
        return redirect("/panel_tecnico")

    session.pop("centro_id", None)
    session.pop("centro_nombre", None)
    session["mensaje_ok"] = "Vista global restaurada."
    return redirect("/panel_tecnico")


@app.route("/superadmin/crear_centro", methods=["POST"])
def superadmin_crear_centro():
    """Crea un nuevo centro. Solo superadmin."""
    if not es_superadmin():
        return redirect("/panel_tecnico")

    nombre = (request.form.get("nombre") or "").strip()
    if not nombre:
        session["mensaje_error"] = "El nombre del centro no puede estar vacío."
        return redirect("/panel_tecnico")

    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS centros (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            creado TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()

    if cur.execute("SELECT 1 FROM centros WHERE nombre = ?", (nombre,)).fetchone():
        conn.close()
        session["mensaje_error"] = f"Ya existe un centro con el nombre '{nombre}'."
        return redirect("/panel_tecnico")

    cur.execute("INSERT INTO centros (nombre) VALUES (?)", (nombre,))
    conn.commit()
    conn.close()

    registrar_accion(session.get("usuario"), f"Superadmin creó centro: {nombre}")
    session["mensaje_ok"] = f"Centro '{nombre}' creado correctamente."
    return redirect("/panel_tecnico")


@app.route("/superadmin/eliminar_centro", methods=["POST"])
def superadmin_eliminar_centro():
    """Elimina un centro y todos sus datos. Solo superadmin."""
    if not es_superadmin():
        return redirect("/panel_tecnico")

    centro_id = request.form.get("centro_id")
    if not centro_id:
        session["mensaje_error"] = "Falta el ID del centro."
        return redirect("/panel_tecnico")

    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    centro = cur.execute("SELECT nombre FROM centros WHERE id = ?", (centro_id,)).fetchone()
    if not centro:
        conn.close()
        session["mensaje_error"] = "Centro no encontrado."
        return redirect("/panel_tecnico")

    nombre_centro = centro["nombre"]

    # Borrar todos los datos del centro
    tablas_con_centro = [
        "profesores", "alumnos", "cursos", "en_banio", "cola_banio",
        "salud", "historial", "historial_banio", "historial_global",
        "registros", "solicitudes_reset", "config", "chat_mensajes",
        "coordinadores", "conserjeria", "notificaciones"
    ]
    for tabla in tablas_con_centro:
        try:
            cur.execute(f"DELETE FROM {tabla} WHERE centro_id = ?", (centro_id,))
        except Exception:
            pass  # tabla puede no existir

    cur.execute("DELETE FROM centros WHERE id = ?", (centro_id,))
    conn.commit()
    conn.close()

    # Si el centro eliminado era el activo, limpiar sesión
    if session.get("centro_id") == int(centro_id):
        session.pop("centro_id", None)
        session.pop("centro_nombre", None)

    registrar_accion(session.get("usuario"), f"Superadmin eliminó centro: {nombre_centro}")
    session["mensaje_ok"] = f"Centro '{nombre_centro}' eliminado correctamente."
    return redirect("/panel_tecnico")


@app.route("/superadmin/api/global")
def superadmin_api_global():
    """API JSON con estadísticas globales para el panel del superadmin."""
    if not es_superadmin():
        return jsonify({"error": "Sin permiso"}), 403

    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        centros_rows = cur.execute("SELECT * FROM centros ORDER BY nombre ASC").fetchall()
    except Exception:
        centros_rows = []

    centros = []
    for c in centros_rows:
        cid = c["id"]
        en_b  = cur.execute("SELECT COUNT(*) AS n FROM en_banio WHERE centro_id=?", (cid,)).fetchone()["n"]
        cola  = cur.execute("SELECT COUNT(*) AS n FROM cola_banio WHERE centro_id=?", (cid,)).fetchone()["n"]
        hoy   = cur.execute(
            "SELECT COUNT(*) AS n FROM historial_global WHERE centro_id=? AND DATE(hora_salida)=DATE('now')",
            (cid,)
        ).fetchone()["n"]
        centros.append({
            "id":       cid,
            "nombre":   c["nombre"],
            "en_banio": en_b,
            "cola":     cola,
            "hoy":      hoy,
        })

    total_en_banio = cur.execute("SELECT COUNT(*) AS n FROM en_banio").fetchone()["n"]
    total_hoy      = cur.execute(
        "SELECT COUNT(*) AS n FROM historial_global WHERE DATE(hora_salida)=DATE('now')"
    ).fetchone()["n"]

    conn.close()
    return jsonify({
        "centros":       centros,
        "total_en_banio": total_en_banio,
        "total_hoy":      total_hoy,
    })


# ============================
# SISTEMA
# ============================

@app.route("/sistema")
def sistema():
    if "profesor_id" not in session or "tecnico" not in session.get("roles", []):
        return redirect("/panel")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT, centro_id INTEGER)")
    conn.commit()

    config_rows = cur.execute("SELECT clave, valor FROM config ORDER BY clave").fetchall()
    config_dict = {r["clave"]: r["valor"] for r in config_rows}
    modo_mantenimiento = config_dict.get("modo_mantenimiento", "0") == "1"

    total_mensajes_chat = 0
    mensajes_sin_leer   = 0
    try:
        if centro_id:
            total_mensajes_chat = cur.execute(
                "SELECT COUNT(*) AS c FROM chat_mensajes WHERE centro_id = ?", (centro_id,)
            ).fetchone()["c"]
            mensajes_sin_leer = cur.execute(
                "SELECT COUNT(*) AS c FROM chat_mensajes WHERE leido=0 AND remitente='profesor' AND centro_id = ?",
                (centro_id,)
            ).fetchone()["c"]
        else:
            total_mensajes_chat = cur.execute("SELECT COUNT(*) AS c FROM chat_mensajes").fetchone()["c"]
            mensajes_sin_leer   = cur.execute(
                "SELECT COUNT(*) AS c FROM chat_mensajes WHERE leido=0 AND remitente='profesor'"
            ).fetchone()["c"]
    except Exception:
        pass

    top_chat = []
    try:
        if centro_id:
            top_chat = cur.execute("""
                SELECT profesor_usuario, COUNT(*) AS total
                FROM chat_mensajes WHERE centro_id = ?
                GROUP BY profesor_usuario ORDER BY total DESC LIMIT 5
            """, (centro_id,)).fetchall()
        else:
            top_chat = cur.execute("""
                SELECT profesor_usuario, COUNT(*) AS total
                FROM chat_mensajes
                GROUP BY profesor_usuario ORDER BY total DESC LIMIT 5
            """).fetchall()
    except Exception:
        pass

    if centro_id:
        top_banio = cur.execute("""
            SELECT alumnos.nombre, COUNT(*) AS total
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            WHERE historial_banio.centro_id = ?
            GROUP BY alumnos.nombre ORDER BY total DESC LIMIT 5
        """, (centro_id,)).fetchall()
        top_tiempo = cur.execute("""
            SELECT alumnos.nombre,
                   ROUND(AVG(historial_banio.minutos), 1) AS promedio,
                   MAX(historial_banio.minutos) AS maximo
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            WHERE historial_banio.centro_id = ?
            GROUP BY alumnos.nombre ORDER BY promedio DESC LIMIT 5
        """, (centro_id,)).fetchall()
        salidas_hoy = cur.execute("""
            SELECT COUNT(*) AS c FROM historial_global
            WHERE DATE(hora_salida) = DATE('now') AND centro_id = ?
        """, (centro_id,)).fetchone()["c"]
    else:
        top_banio = cur.execute("""
            SELECT alumnos.nombre, COUNT(*) AS total
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            GROUP BY alumnos.nombre ORDER BY total DESC LIMIT 5
        """).fetchall()
        top_tiempo = cur.execute("""
            SELECT alumnos.nombre,
                   ROUND(AVG(historial_banio.minutos), 1) AS promedio,
                   MAX(historial_banio.minutos) AS maximo
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            GROUP BY alumnos.nombre ORDER BY promedio DESC LIMIT 5
        """).fetchall()
        salidas_hoy = cur.execute("""
            SELECT COUNT(*) AS c FROM historial_global WHERE DATE(hora_salida) = DATE('now')
        """).fetchone()["c"]

    conn.close()

    return render_template(
        "sistema.html",
        usuario=session.get("usuario"),
        modo_mantenimiento=modo_mantenimiento,
        config_dict=config_dict,
        total_mensajes_chat=total_mensajes_chat,
        mensajes_sin_leer=mensajes_sin_leer,
        top_chat=top_chat,
        top_banio=top_banio,
        top_tiempo=top_tiempo,
        salidas_hoy=salidas_hoy,
    )


@app.route("/sistema/limpiar_historial", methods=["POST"])
def sistema_limpiar_historial():
    if "profesor_id" not in session or "tecnico" not in session.get("roles", []):
        return redirect("/panel")

    tabla = request.form.get("tabla", "")
    permitidas = ["historial_banio", "historial_global", "registros", "chat_mensajes"]
    if tabla not in permitidas:
        session["mensaje_error"] = "Tabla no permitida."
        return redirect("/sistema")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    if centro_id:
        conn.execute(f"DELETE FROM {tabla} WHERE centro_id = ?", (centro_id,))
    else:
        conn.execute(f"DELETE FROM {tabla}")
    conn.commit()
    conn.close()

    registrar_accion(session.get("usuario"), f"Limpieza de tabla: {tabla}")
    session["mensaje_ok"] = f"Tabla '{tabla}' vaciada correctamente."
    return redirect("/sistema")


@app.route("/sistema/config", methods=["POST"])
def sistema_config():
    if "profesor_id" not in session or "tecnico" not in session.get("roles", []):
        return redirect("/panel")

    clave = request.form.get("clave", "").strip()
    valor = request.form.get("valor", "").strip()
    if not clave:
        session["mensaje_error"] = "La clave no puede estar vacía."
        return redirect("/sistema")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    if centro_id:
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor, centro_id) VALUES (?, ?, ?)",
            (clave, valor, centro_id)
        )
    else:
        conn.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)", (clave, valor))
    conn.commit()
    conn.close()

    registrar_accion(session.get("usuario"), f"Config actualizada: {clave}={valor}")
    session["mensaje_ok"] = f"Configuración '{clave}' guardada."
    return redirect("/sistema")


@app.route("/sistema/config/borrar", methods=["POST"])
def sistema_config_borrar():
    if "profesor_id" not in session or "tecnico" not in session.get("roles", []):
        return redirect("/panel")

    clave = request.form.get("clave", "")
    if clave == "modo_mantenimiento":
        session["mensaje_error"] = "No puedes borrar la clave del modo mantenimiento desde aquí."
        return redirect("/sistema")

    conn = sqlite3.connect("servicioedu.db")
    conn.execute("DELETE FROM config WHERE clave = ?", (clave,))
    conn.commit()
    conn.close()

    session["mensaje_ok"] = f"Clave '{clave}' eliminada."
    return redirect("/sistema")


@app.route("/toggle_mantenimiento", methods=["POST"])
def toggle_mantenimiento():
    if "profesor_id" not in session or "tecnico" not in session.get("roles", []):
        return redirect("/panel")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT, centro_id INTEGER)")
    valor = "1" if request.form.get("modo") == "activar" else "0"
    if centro_id:
        cur.execute(
            "INSERT OR REPLACE INTO config (clave, valor, centro_id) VALUES ('modo_mantenimiento', ?, ?)",
            (valor, centro_id)
        )
    else:
        cur.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('modo_mantenimiento', ?)",
            (valor,)
        )
    conn.commit()
    conn.close()
    return redirect("/panel_tecnico")


# ============================
# GESTIÓN DE PROFESORES
# ============================

@app.route("/gestion_profesores")
def gestion_profesores():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if centro_id:
        cur.execute("SELECT * FROM profesores WHERE centro_id = ? ORDER BY usuario ASC", (centro_id,))
    else:
        cur.execute("SELECT * FROM profesores ORDER BY usuario ASC")
    profesores = cur.fetchall()
    conn.close()

    return render_template("gestion_profesores.html", profesores=profesores)


@app.route("/add_profesor", methods=["POST"])
def add_profesor():
    if not es_coordinador_o_tde():
        return redirect("/login")

    usuario  = request.form["usuario"]
    password = request.form["password"]
    rol      = request.form.get("rol", "profesor")
    hash_pw  = hashlib.sha256(password.encode("utf-8")).hexdigest()
    centro_id = get_centro_id()

    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if centro_id:
        cur.execute("""
            INSERT INTO profesores (usuario, password, primer_inicio, rol, centro_id)
            VALUES (?, ?, 0, ?, ?)
        """, (usuario, hash_pw, rol, centro_id))
    else:
        cur.execute("""
            INSERT INTO profesores (usuario, password, primer_inicio, rol)
            VALUES (?, ?, 0, ?)
        """, (usuario, hash_pw, rol))
    conn.commit()
    conn.close()

    session["mensaje_ok"] = "Profesor añadido correctamente."
    return redirect("/gestion_profesores")


@app.route("/delete_profesor", methods=["POST"])
def delete_profesor():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if centro_id:
        cur.execute(
            "DELETE FROM profesores WHERE id = ? AND centro_id = ?",
            (request.form["id"], centro_id)
        )
    else:
        cur.execute("DELETE FROM profesores WHERE id = ?", (request.form["id"],))
    conn.commit()
    conn.close()

    session["mensaje_ok"] = "Profesor eliminado correctamente."
    return redirect("/gestion_profesores")


@app.route("/editar_profesor")
def editar_profesor():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if centro_id:
        cur.execute(
            "SELECT * FROM profesores WHERE id = ? AND centro_id = ?",
            (request.args.get("id"), centro_id)
        )
    else:
        cur.execute("SELECT * FROM profesores WHERE id = ?", (request.args.get("id"),))
    profesor = cur.fetchone()
    conn.close()

    return render_template("editar_profesor.html", profesor=profesor)


@app.route("/update_profesor", methods=["POST"])
def update_profesor():
    if not es_coordinador_o_tde():
        return redirect("/login")

    profesor_id = request.form["id"]
    usuario     = request.form["usuario"]
    rol         = request.form.get("rol", "profesor")
    password    = request.form["password"]
    centro_id   = get_centro_id()

    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if password.strip() == "":
        if centro_id:
            cur.execute(
                "UPDATE profesores SET usuario=?, rol=? WHERE id=? AND centro_id=?",
                (usuario, rol, profesor_id, centro_id)
            )
        else:
            cur.execute("UPDATE profesores SET usuario=?, rol=? WHERE id=?", (usuario, rol, profesor_id))
    else:
        hash_pw = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if centro_id:
            cur.execute(
                "UPDATE profesores SET usuario=?, rol=?, password=? WHERE id=? AND centro_id=?",
                (usuario, rol, hash_pw, profesor_id, centro_id)
            )
        else:
            cur.execute(
                "UPDATE profesores SET usuario=?, rol=?, password=? WHERE id=?",
                (usuario, rol, hash_pw, profesor_id)
            )
    conn.commit()
    conn.close()

    session["mensaje_ok"] = "Profesor actualizado correctamente."
    return redirect("/gestion_profesores")


@app.route("/reset_password/<int:profesor_id>", methods=["POST"])
def reset_password(profesor_id):
    temp_pass = secrets.token_hex(3)
    hashed    = hashlib.sha256(temp_pass.encode()).hexdigest()
    centro_id = get_centro_id()

    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if centro_id:
        cur.execute("""
            UPDATE profesores SET password=?, password_temp=?, primer_inicio=1
            WHERE id=? AND centro_id=?
        """, (hashed, temp_pass, profesor_id, centro_id))
    else:
        cur.execute("""
            UPDATE profesores SET password=?, password_temp=?, primer_inicio=1 WHERE id=?
        """, (hashed, temp_pass, profesor_id))
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "temp_password": temp_pass})


# ============================
# GESTIÓN DE ALUMNOS
# ============================

@app.route("/gestion_alumnos")
def gestion_alumnos():
    if not es_coordinador_o_tde():
        return redirect("/login")

    pagina = int(request.args.get("p", 1))
    limite = 20
    offset = (pagina - 1) * limite
    centro_id = get_centro_id()

    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if centro_id:
        cur.execute(
            "SELECT * FROM alumnos WHERE centro_id = ? ORDER BY nombre ASC LIMIT ? OFFSET ?",
            (centro_id, limite, offset)
        )
        alumnos = cur.fetchall()
        total   = cur.execute("SELECT COUNT(*) AS total FROM alumnos WHERE centro_id = ?", (centro_id,)).fetchone()["total"]
    else:
        cur.execute("SELECT * FROM alumnos ORDER BY nombre ASC LIMIT ? OFFSET ?", (limite, offset))
        alumnos = cur.fetchall()
        total   = cur.execute("SELECT COUNT(*) AS total FROM alumnos").fetchone()["total"]

    paginas = (total // limite) + (1 if total % limite else 0)
    conn.close()

    return render_template("gestion_alumnos.html", alumnos=alumnos, pagina=pagina, paginas=paginas)


@app.route("/upload_alumnos_csv", methods=["POST"])
def upload_alumnos_csv():
    if not es_coordinador_o_tde():
        return redirect("/login")

    if "csv_file" not in request.files or request.files["csv_file"].filename == "":
        session["mensaje_error"] = "Archivo CSV no válido."
        return redirect("/gestion_alumnos")

    file   = request.files["csv_file"]
    stream = io.StringIO(file.stream.read().decode("utf-8"))
    reader = csv.reader(stream)
    centro_id = get_centro_id()

    conn = sqlite3.connect("servicioedu.db")
    cur  = conn.cursor()
    for row in reader:
        if len(row) < 2:
            continue
        if centro_id:
            cur.execute(
                "INSERT INTO alumnos (nombre, curso, centro_id) VALUES (?, ?, ?)",
                (row[0], row[1], centro_id)
            )
        else:
            cur.execute("INSERT INTO alumnos (nombre, curso) VALUES (?, ?)", (row[0], row[1]))
    conn.commit()
    conn.close()

    session["mensaje_ok"] = "Alumnos importados correctamente."
    return redirect("/gestion_alumnos")


@app.route("/delete_alumnos_masivo", methods=["POST"])
def delete_alumnos_masivo():
    if not es_coordinador_o_tde():
        return redirect("/login")

    ids = request.form.getlist("ids[]")
    if not ids:
        session["mensaje_error"] = "No se seleccionó ningún alumno."
        return redirect("/gestion_alumnos")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    cur  = conn.cursor()
    for alumno_id in ids:
        if centro_id:
            cur.execute("DELETE FROM alumnos WHERE id = ? AND centro_id = ?", (alumno_id, centro_id))
        else:
            cur.execute("DELETE FROM alumnos WHERE id = ?", (alumno_id,))
    conn.commit()
    conn.close()

    session["mensaje_ok"] = "Alumnos eliminados correctamente."
    return redirect("/gestion_alumnos")


@app.route("/editar_alumno")
def editar_alumno():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if centro_id:
        cur.execute(
            "SELECT * FROM alumnos WHERE id = ? AND centro_id = ?",
            (request.args.get("id"), centro_id)
        )
    else:
        cur.execute("SELECT * FROM alumnos WHERE id = ?", (request.args.get("id"),))
    alumno = cur.fetchone()
    conn.close()

    return render_template("editar_alumno.html", alumno=alumno)


@app.route("/update_alumno", methods=["POST"])
def update_alumno():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if centro_id:
        cur.execute(
            "UPDATE alumnos SET nombre=?, curso=? WHERE id=? AND centro_id=?",
            (request.form["nombre"], request.form["curso"], request.form["id"], centro_id)
        )
    else:
        cur.execute(
            "UPDATE alumnos SET nombre=?, curso=? WHERE id=?",
            (request.form["nombre"], request.form["curso"], request.form["id"])
        )
    conn.commit()
    conn.close()

    session["mensaje_ok"] = "Alumno actualizado correctamente."
    return redirect("/gestion_alumnos")


# ============================
# GESTIÓN DE CURSOS
# ============================

@app.route("/gestion_cursos")
def gestion_cursos():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if centro_id:
        cur.execute("SELECT * FROM cursos WHERE centro_id = ? ORDER BY nombre ASC", (centro_id,))
    else:
        cur.execute("SELECT * FROM cursos ORDER BY nombre ASC")
    cursos = cur.fetchall()
    conn.close()

    return render_template("gestion_cursos.html", cursos=cursos)


@app.route("/nuevo_curso")
def nuevo_curso():
    if not es_coordinador_o_tde():
        return redirect("/login")
    return render_template("nuevo_curso.html")


@app.route("/add_curso", methods=["POST"])
def add_curso():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if centro_id:
        cur.execute(
            "INSERT INTO cursos (nombre, descripcion, centro_id) VALUES (?, ?, ?)",
            (request.form["nombre"], request.form["descripcion"], centro_id)
        )
    else:
        cur.execute(
            "INSERT INTO cursos (nombre, descripcion) VALUES (?, ?)",
            (request.form["nombre"], request.form["descripcion"])
        )
    conn.commit()
    conn.close()

    session["mensaje_ok"] = "Curso creado correctamente."
    return redirect("/gestion_cursos")


@app.route("/editar_curso")
def editar_curso():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if centro_id:
        cur.execute(
            "SELECT * FROM cursos WHERE id = ? AND centro_id = ?",
            (request.args.get("id"), centro_id)
        )
    else:
        cur.execute("SELECT * FROM cursos WHERE id = ?", (request.args.get("id"),))
    curso = cur.fetchone()
    conn.close()

    return render_template("editar_curso.html", curso=curso)


@app.route("/update_curso", methods=["POST"])
def update_curso():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if centro_id:
        cur.execute(
            "UPDATE cursos SET nombre=?, descripcion=? WHERE id=? AND centro_id=?",
            (request.form["nombre"], request.form["descripcion"], request.form["id"], centro_id)
        )
    else:
        cur.execute(
            "UPDATE cursos SET nombre=?, descripcion=? WHERE id=?",
            (request.form["nombre"], request.form["descripcion"], request.form["id"])
        )
    conn.commit()
    conn.close()

    session["mensaje_ok"] = "Curso actualizado correctamente."
    return redirect("/gestion_cursos")


@app.route("/delete_curso", methods=["POST"])
def delete_curso():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if centro_id:
        cur.execute("DELETE FROM cursos WHERE id = ? AND centro_id = ?", (request.form["id"], centro_id))
    else:
        cur.execute("DELETE FROM cursos WHERE id = ?", (request.form["id"],))
    conn.commit()
    conn.close()

    session["mensaje_ok"] = "Curso eliminado correctamente."
    return redirect("/gestion_cursos")


# ============================
# REGISTROS DEL SISTEMA
# ============================

@app.route("/registros")
def registros():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if centro_id:
        cur.execute("SELECT * FROM registros WHERE centro_id = ? ORDER BY fecha DESC", (centro_id,))
    else:
        cur.execute("SELECT * FROM registros ORDER BY fecha DESC")
    registros_lista = cur.fetchall()
    conn.close()

    return render_template("registros_sistema.html", registros=registros_lista)


# ============================
# DASHBOARD TDE
# ============================

@app.route("/dashboard")
def dashboard():
    if not es_coordinador_o_tde():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if centro_id:
        total_profesores = cur.execute("SELECT COUNT(*) AS c FROM profesores WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_alumnos    = cur.execute("SELECT COUNT(*) AS c FROM alumnos WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_cursos     = cur.execute("SELECT COUNT(*) AS c FROM cursos WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_registros  = cur.execute("SELECT COUNT(*) AS c FROM historial_global WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        filas = cur.execute("""
            SELECT strftime('%m', hora_salida) AS mes, COUNT(*) AS c
            FROM historial_global
            WHERE strftime('%Y', hora_salida) = strftime('%Y', 'now') AND centro_id = ?
            GROUP BY mes ORDER BY mes
        """, (centro_id,)).fetchall()
        cursos = cur.execute("SELECT nombre FROM cursos WHERE centro_id = ? ORDER BY nombre ASC", (centro_id,)).fetchall()
        nombres_cursos    = [c["nombre"] for c in cursos]
        alumnos_por_curso = [
            cur.execute(
                "SELECT COUNT(*) AS c FROM alumnos WHERE curso = ? AND centro_id = ?",
                (c["nombre"], centro_id)
            ).fetchone()["c"]
            for c in cursos
        ]
    else:
        total_profesores = cur.execute("SELECT COUNT(*) AS c FROM profesores").fetchone()["c"]
        total_alumnos    = cur.execute("SELECT COUNT(*) AS c FROM alumnos").fetchone()["c"]
        total_cursos     = cur.execute("SELECT COUNT(*) AS c FROM cursos").fetchone()["c"]
        total_registros  = cur.execute("SELECT COUNT(*) AS c FROM historial_global").fetchone()["c"]
        filas = cur.execute("""
            SELECT strftime('%m', hora_salida) AS mes, COUNT(*) AS c
            FROM historial_global
            WHERE strftime('%Y', hora_salida) = strftime('%Y', 'now')
            GROUP BY mes ORDER BY mes
        """).fetchall()
        cursos = cur.execute("SELECT nombre FROM cursos ORDER BY nombre ASC").fetchall()
        nombres_cursos    = [c["nombre"] for c in cursos]
        alumnos_por_curso = [
            cur.execute("SELECT COUNT(*) AS c FROM alumnos WHERE curso = ?", (c["nombre"],)).fetchone()["c"]
            for c in cursos
        ]

    meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    actividad_mensual = [0] * 12
    for f in filas:
        actividad_mensual[int(f["mes"]) - 1] = f["c"]

    conn.close()

    return render_template(
        "dashboard_tde.html",
        usuario=session.get("usuario"),
        total_profesores=total_profesores,
        total_alumnos=total_alumnos,
        total_cursos=total_cursos,
        total_registros=total_registros,
        meses=meses,
        actividad_mensual=actividad_mensual,
        nombres_cursos=nombres_cursos,
        cantidad_cursos=[1 for _ in cursos],
        alumnos_por_curso=alumnos_por_curso
    )


# ============================
# RECUPERACIÓN DE CONTRASEÑA
# ============================

@app.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if request.method == "POST":
        usuario    = request.form["usuario"]
        nombre     = request.form["nombre"]
        comentario = request.form["comentario"]

        conn = sqlite3.connect("servicioedu.db")
        cur  = conn.cursor()
        prof = cur.execute("SELECT centro_id FROM profesores WHERE usuario = ?", (usuario,)).fetchone()
        centro_id = prof["centro_id"] if prof and "centro_id" in prof.keys() else get_centro_id()

        cur.execute("""
            INSERT INTO solicitudes_reset (usuario, nombre, comentario, estado, centro_id)
            VALUES (?, ?, ?, 'pendiente', ?)
        """, (usuario, nombre, comentario, centro_id))
        conn.commit()
        conn.close()

        return """
            <script>
                alert('Solicitud enviada. El coordinador revisará tu petición.');
                window.location.href='/login';
            </script>
        """

    return render_template("recuperar.html")


@app.route("/solicitudes_reset")
def ver_solicitudes():
    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if centro_id:
        cur.execute(
            "SELECT * FROM solicitudes_reset WHERE estado='pendiente' AND centro_id = ?",
            (centro_id,)
        )
    else:
        cur.execute("SELECT * FROM solicitudes_reset WHERE estado='pendiente'")
    solicitudes = cur.fetchall()
    conn.close()

    popup_usuario = session.pop("popup_usuario", None)
    popup_pass    = session.pop("popup_pass", None)

    return render_template(
        "solicitudes_reset.html",
        solicitudes=solicitudes,
        popup_usuario=popup_usuario,
        popup_pass=popup_pass
    )


@app.route("/aprobar_reset/<int:id_solicitud>", methods=["POST"])
def aprobar_reset(id_solicitud):
    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if centro_id:
        row = cur.execute(
            "SELECT usuario FROM solicitudes_reset WHERE id=? AND centro_id=?",
            (id_solicitud, centro_id)
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT usuario FROM solicitudes_reset WHERE id=?", (id_solicitud,)
        ).fetchone()

    if not row:
        conn.close()
        return "Solicitud no encontrada"

    if centro_id:
        prof = cur.execute(
            "SELECT id FROM profesores WHERE usuario=? AND centro_id=?",
            (row["usuario"], centro_id)
        ).fetchone()
    else:
        prof = cur.execute("SELECT id FROM profesores WHERE usuario=?", (row["usuario"],)).fetchone()

    if not prof:
        conn.close()
        return "Usuario no encontrado"

    temp_pass = secrets.token_hex(3)
    hashed    = hashlib.sha256(temp_pass.encode()).hexdigest()

    cur.execute("""
        UPDATE profesores SET password=?, password_temp=?, primer_inicio=1 WHERE id=?
    """, (hashed, temp_pass, prof["id"]))
    cur.execute("UPDATE solicitudes_reset SET estado='resuelto' WHERE id=?", (id_solicitud,))
    conn.commit()
    conn.close()

    session["popup_usuario"] = row["usuario"]
    session["popup_pass"]    = temp_pass

    return redirect("/solicitudes_reset")


# ============================
# PERFIL DEL PROFESOR
# ============================

@app.route("/perfil_datos")
def perfil_datos():
    if "profesor_id" not in session:
        return jsonify({"error": "No autenticado"}), 401

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if centro_id:
        profesor = cur.execute(
            "SELECT * FROM profesores WHERE id = ? AND centro_id = ?",
            (session["profesor_id"], centro_id)
        ).fetchone()
    else:
        profesor = cur.execute(
            "SELECT * FROM profesores WHERE id = ?", (session["profesor_id"],)
        ).fetchone()
    conn.close()

    if not profesor:
        return jsonify({"error": "Profesor no encontrado"}), 404

    datos = {
        "usuario":         profesor["usuario"],
        "nombre_completo": profesor["nombre"] if "nombre" in profesor.keys() else profesor["usuario"],
        "email":           profesor["email"]   if "email"  in profesor.keys() else None,
        "rol":             profesor["rol"],
        "centro":          profesor["centro"]  if "centro" in profesor.keys() else None,
        "ultimo_acceso":   profesor["ultimo_acceso"] if "ultimo_acceso" in profesor.keys() else None,
    }
    return jsonify(datos)


@app.route("/cambiar_password_perfil", methods=["POST"])
def cambiar_password_perfil():
    if "profesor_id" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401

    data      = request.get_json()
    actual    = data.get("actual", "")
    nueva     = data.get("nueva", "")
    confirmar = data.get("confirmar", "")

    if not actual or not nueva or not confirmar:
        return jsonify({"ok": False, "error": "Rellena todos los campos."})
    if nueva != confirmar:
        return jsonify({"ok": False, "error": "Las contraseñas nuevas no coinciden."})
    if len(nueva) < 6:
        return jsonify({"ok": False, "error": "La contraseña debe tener al menos 6 caracteres."})

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if centro_id:
        profesor = cur.execute(
            "SELECT password FROM profesores WHERE id = ? AND centro_id = ?",
            (session["profesor_id"], centro_id)
        ).fetchone()
    else:
        profesor = cur.execute(
            "SELECT password FROM profesores WHERE id = ?", (session["profesor_id"],)
        ).fetchone()

    if not profesor:
        conn.close()
        return jsonify({"ok": False, "error": "Profesor no encontrado."})

    hash_actual = hashlib.sha256(actual.encode("utf-8")).hexdigest()
    if hash_actual != profesor["password"]:
        conn.close()
        return jsonify({"ok": False, "error": "La contraseña actual no es correcta."})

    hash_nueva = hashlib.sha256(nueva.encode("utf-8")).hexdigest()
    cur.execute("UPDATE profesores SET password = ? WHERE id = ?", (hash_nueva, session["profesor_id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ============================
# CHAT TÉCNICO ↔ PROFESOR
# ============================

@app.route("/chat/mensajes")
def chat_mensajes():
    if "profesor_id" not in session:
        return jsonify({"error": "No autenticado"}), 401

    usuario   = session["usuario"]
    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    _init_chat_table(conn)

    if centro_id:
        conn.execute("""
            UPDATE chat_mensajes SET leido = 1
            WHERE profesor_usuario = ? AND remitente = 'tecnico' AND leido = 0 AND centro_id = ?
        """, (usuario, centro_id))
    else:
        conn.execute("""
            UPDATE chat_mensajes SET leido = 1
            WHERE profesor_usuario = ? AND remitente = 'tecnico' AND leido = 0
        """, (usuario,))
    conn.commit()

    if centro_id:
        rows = conn.execute("""
            SELECT id, remitente, mensaje, fecha FROM chat_mensajes
            WHERE profesor_usuario = ? AND centro_id = ? ORDER BY id ASC
        """, (usuario, centro_id)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, remitente, mensaje, fecha FROM chat_mensajes
            WHERE profesor_usuario = ? ORDER BY id ASC
        """, (usuario,)).fetchall()
    conn.close()

    return jsonify({"mensajes": [dict(r) for r in rows]})


@app.route("/chat/enviar", methods=["POST"])
def chat_enviar():
    if "profesor_id" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401

    data    = request.get_json(silent=True) or {}
    mensaje = data.get("mensaje", "").strip()

    if not mensaje:
        return jsonify({"ok": False, "error": "Mensaje vacío."})
    if len(mensaje) > 1000:
        return jsonify({"ok": False, "error": "Mensaje demasiado largo."})

    usuario   = session["usuario"]
    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    _init_chat_table(conn)
    conn.execute("""
        INSERT INTO chat_mensajes (profesor_usuario, remitente, mensaje, centro_id)
        VALUES (?, 'profesor', ?, ?)
    """, (usuario, mensaje, centro_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/chat/sin_leer")
def chat_sin_leer():
    if "profesor_id" not in session:
        return jsonify({"count": 0})

    usuario   = session["usuario"]
    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    _init_chat_table(conn)
    if centro_id:
        row = conn.execute("""
            SELECT COUNT(*) AS c FROM chat_mensajes
            WHERE profesor_usuario = ? AND remitente = 'tecnico' AND leido = 0 AND centro_id = ?
        """, (usuario, centro_id)).fetchone()
    else:
        row = conn.execute("""
            SELECT COUNT(*) AS c FROM chat_mensajes
            WHERE profesor_usuario = ? AND remitente = 'tecnico' AND leido = 0
        """, (usuario,)).fetchone()
    conn.close()
    return jsonify({"count": row[0]})


@app.route("/chat/tecnico/conversaciones")
def chat_tecnico_conversaciones():
    if "profesor_id" not in session and "coordinador_id" not in session:
        return jsonify({"error": "No autenticado"}), 401
    if "profesor_id" in session and "tecnico" not in session.get("roles", []):
        return jsonify({"error": "Sin permiso"}), 403

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    _init_chat_table(conn)

    if centro_id:
        rows = conn.execute("""
            SELECT profesor_usuario, MAX(fecha) AS ultimo_mensaje_fecha,
                (SELECT mensaje FROM chat_mensajes m2
                 WHERE m2.profesor_usuario = m1.profesor_usuario AND m2.centro_id = m1.centro_id
                 ORDER BY m2.id DESC LIMIT 1) AS ultimo_mensaje,
                SUM(CASE WHEN remitente = 'profesor' AND leido = 0 THEN 1 ELSE 0 END) AS sin_leer
            FROM chat_mensajes m1
            WHERE centro_id = ?
            GROUP BY profesor_usuario
            ORDER BY ultimo_mensaje_fecha DESC
        """, (centro_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT profesor_usuario, MAX(fecha) AS ultimo_mensaje_fecha,
                (SELECT mensaje FROM chat_mensajes m2
                 WHERE m2.profesor_usuario = m1.profesor_usuario
                 ORDER BY m2.id DESC LIMIT 1) AS ultimo_mensaje,
                SUM(CASE WHEN remitente = 'profesor' AND leido = 0 THEN 1 ELSE 0 END) AS sin_leer
            FROM chat_mensajes m1
            GROUP BY profesor_usuario
            ORDER BY ultimo_mensaje_fecha DESC
        """).fetchall()
    conn.close()

    return jsonify({"conversaciones": [dict(r) for r in rows]})


@app.route("/chat/tecnico/mensajes/<string:profesor_usuario>")
def chat_tecnico_mensajes(profesor_usuario):
    if "profesor_id" not in session and "coordinador_id" not in session:
        return jsonify({"error": "No autenticado"}), 401
    if "profesor_id" in session and "tecnico" not in session.get("roles", []):
        return jsonify({"error": "Sin permiso"}), 403

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    _init_chat_table(conn)

    if centro_id:
        conn.execute("""
            UPDATE chat_mensajes SET leido = 1
            WHERE profesor_usuario = ? AND remitente = 'profesor' AND leido = 0 AND centro_id = ?
        """, (profesor_usuario, centro_id))
        conn.commit()
        rows = conn.execute("""
            SELECT id, remitente, mensaje, fecha FROM chat_mensajes
            WHERE profesor_usuario = ? AND centro_id = ? ORDER BY id ASC
        """, (profesor_usuario, centro_id)).fetchall()
    else:
        conn.execute("""
            UPDATE chat_mensajes SET leido = 1
            WHERE profesor_usuario = ? AND remitente = 'profesor' AND leido = 0
        """, (profesor_usuario,))
        conn.commit()
        rows = conn.execute("""
            SELECT id, remitente, mensaje, fecha FROM chat_mensajes
            WHERE profesor_usuario = ? ORDER BY id ASC
        """, (profesor_usuario,)).fetchall()
    conn.close()

    return jsonify({"mensajes": [dict(r) for r in rows]})


@app.route("/chat/tecnico/responder", methods=["POST"])
def chat_tecnico_responder():
    if "profesor_id" not in session and "coordinador_id" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401
    if "profesor_id" in session and "tecnico" not in session.get("roles", []):
        return jsonify({"ok": False, "error": "Sin permiso"}), 403

    data             = request.get_json(silent=True) or {}
    profesor_usuario = data.get("profesor_usuario", "").strip()
    mensaje          = data.get("mensaje", "").strip()

    if not profesor_usuario:
        return jsonify({"ok": False, "error": "Falta el profesor destinatario."})
    if not mensaje:
        return jsonify({"ok": False, "error": "Mensaje vacío."})
    if len(mensaje) > 1000:
        return jsonify({"ok": False, "error": "Mensaje demasiado largo."})

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    _init_chat_table(conn)
    conn.execute("""
        INSERT INTO chat_mensajes (profesor_usuario, remitente, mensaje, centro_id)
        VALUES (?, 'tecnico', ?, ?)
    """, (profesor_usuario, mensaje, centro_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ============================
# DIAGNÓSTICO DEL SISTEMA
# ============================

import platform
import time

@app.route("/diagnostico")
def diagnostico():
    if "profesor_id" not in session or "tecnico" not in session.get("roles", []):
        return redirect("/panel")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        t0 = time.perf_counter()
        cur.execute("SELECT COUNT(*) AS c FROM historial_global")
        cur.fetchone()
        latencia_bd = round((time.perf_counter() - t0) * 1000, 2)
        bd_ok = True
    except Exception:
        latencia_bd = -1
        bd_ok = False

    if centro_id:
        total_profesores  = cur.execute("SELECT COUNT(*) AS c FROM profesores WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_alumnos     = cur.execute("SELECT COUNT(*) AS c FROM alumnos WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_cursos      = cur.execute("SELECT COUNT(*) AS c FROM cursos WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_historial   = cur.execute("SELECT COUNT(*) AS c FROM historial_global WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_solicitudes = cur.execute("SELECT COUNT(*) AS c FROM solicitudes_reset WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        en_banio_ahora = cur.execute("SELECT COUNT(*) AS c FROM en_banio WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        cola_ahora     = cur.execute("SELECT COUNT(*) AS c FROM cola_banio WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        salud_ahora    = cur.execute("SELECT COUNT(*) AS c FROM salud WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        mant_row = cur.execute(
            "SELECT valor FROM config WHERE clave='modo_mantenimiento' AND centro_id = ?", (centro_id,)
        ).fetchone()
        ultimas_acciones = cur.execute("""
            SELECT historial_global.id, alumnos.nombre AS alumno,
                   historial_global.hora_salida, historial_global.estado
            FROM historial_global JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE historial_global.centro_id = ?
            ORDER BY historial_global.id DESC LIMIT 5
        """, (centro_id,)).fetchall()
    else:
        total_profesores  = cur.execute("SELECT COUNT(*) AS c FROM profesores").fetchone()["c"]
        total_alumnos     = cur.execute("SELECT COUNT(*) AS c FROM alumnos").fetchone()["c"]
        total_cursos      = cur.execute("SELECT COUNT(*) AS c FROM cursos").fetchone()["c"]
        total_historial   = cur.execute("SELECT COUNT(*) AS c FROM historial_global").fetchone()["c"]
        total_solicitudes = cur.execute("SELECT COUNT(*) AS c FROM solicitudes_reset").fetchone()["c"]
        en_banio_ahora = cur.execute("SELECT COUNT(*) AS c FROM en_banio").fetchone()["c"]
        cola_ahora     = cur.execute("SELECT COUNT(*) AS c FROM cola_banio").fetchone()["c"]
        salud_ahora    = cur.execute("SELECT COUNT(*) AS c FROM salud").fetchone()["c"]
        mant_row = cur.execute("SELECT valor FROM config WHERE clave='modo_mantenimiento'").fetchone()
        ultimas_acciones = cur.execute("""
            SELECT historial_global.id, alumnos.nombre AS alumno,
                   historial_global.hora_salida, historial_global.estado
            FROM historial_global JOIN alumnos ON alumnos.id = historial_global.alumno_id
            ORDER BY historial_global.id DESC LIMIT 5
        """).fetchall()

    try:
        bd_size_kb = round(os.path.getsize("servicioedu.db") / 1024, 1)
    except Exception:
        bd_size_kb = "N/A"

    tablas = [r["name"] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]

    modo_mantenimiento = (mant_row["valor"] == "1") if mant_row else False
    conn.close()

    servidor_info = {
        "python":   platform.python_version(),
        "os":       f"{platform.system()} {platform.release()}",
        "hostname": platform.node(),
        "arch":     platform.machine(),
    }

    tablas_requeridas = [
        "profesores", "alumnos", "cursos", "en_banio", "cola_banio",
        "salud", "historial", "historial_banio", "historial_global",
        "registros", "solicitudes_reset", "config", "chat_mensajes"
    ]
    tests_tablas = [{"tabla": t, "ok": t in tablas} for t in tablas_requeridas]

    return render_template(
        "diagnostico.html",
        latencia_bd=latencia_bd,
        bd_ok=bd_ok,
        bd_size_kb=bd_size_kb,
        total_profesores=total_profesores,
        total_alumnos=total_alumnos,
        total_cursos=total_cursos,
        total_historial=total_historial,
        total_solicitudes=total_solicitudes,
        en_banio_ahora=en_banio_ahora,
        cola_ahora=cola_ahora,
        salud_ahora=salud_ahora,
        modo_mantenimiento=modo_mantenimiento,
        servidor_info=servidor_info,
        tests_tablas=tests_tablas,
        tablas=tablas,
        ultimas_acciones=ultimas_acciones,
        usuario=session.get("usuario")
    )


# ============================
# REPORTES TÉCNICO
# ============================

@app.route("/reportes")
def reportes():
    if "profesor_id" not in session or "tecnico" not in session.get("roles", []):
        return redirect("/panel")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if centro_id:
        salidas_por_dia = cur.execute("""
            SELECT DATE(hora_salida) AS dia, COUNT(*) AS total FROM historial_global
            WHERE DATE(hora_salida) >= DATE('now', '-7 days') AND centro_id = ?
            GROUP BY dia ORDER BY dia ASC
        """, (centro_id,)).fetchall()
        top_alumnos = cur.execute("""
            SELECT alumnos.nombre, alumnos.curso, COUNT(*) AS total
            FROM historial_global JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE historial_global.centro_id = ?
            GROUP BY alumnos.id ORDER BY total DESC LIMIT 10
        """, (centro_id,)).fetchall()
        top_tiempo = cur.execute("""
            SELECT alumnos.nombre,
                   ROUND(AVG(historial_banio.minutos), 1) AS promedio,
                   MAX(historial_banio.minutos) AS maximo, COUNT(*) AS total
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            WHERE historial_banio.centro_id = ?
            GROUP BY alumnos.id ORDER BY promedio DESC LIMIT 10
        """, (centro_id,)).fetchall()
        salidas_por_curso = cur.execute("""
            SELECT alumnos.curso, COUNT(*) AS total
            FROM historial_global JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE historial_global.centro_id = ?
            GROUP BY alumnos.curso ORDER BY total DESC
        """, (centro_id,)).fetchall()
        solicitudes = cur.execute("""
            SELECT usuario, nombre, comentario, estado, created_at
            FROM solicitudes_reset WHERE centro_id = ? ORDER BY id DESC LIMIT 20
        """, (centro_id,)).fetchall()
        total_salidas = cur.execute("SELECT COUNT(*) AS c FROM historial_global WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_banio   = cur.execute("SELECT COUNT(*) AS c FROM historial_banio WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        salidas_hoy   = cur.execute(
            "SELECT COUNT(*) AS c FROM historial_global WHERE DATE(hora_salida)=DATE('now') AND centro_id = ?",
            (centro_id,)
        ).fetchone()["c"]
        pendientes    = cur.execute(
            "SELECT COUNT(*) AS c FROM solicitudes_reset WHERE estado='pendiente' AND centro_id = ?",
            (centro_id,)
        ).fetchone()["c"]
    else:
        salidas_por_dia = cur.execute("""
            SELECT DATE(hora_salida) AS dia, COUNT(*) AS total FROM historial_global
            WHERE DATE(hora_salida) >= DATE('now', '-7 days')
            GROUP BY dia ORDER BY dia ASC
        """).fetchall()
        top_alumnos = cur.execute("""
            SELECT alumnos.nombre, alumnos.curso, COUNT(*) AS total
            FROM historial_global JOIN alumnos ON alumnos.id = historial_global.alumno_id
            GROUP BY alumnos.id ORDER BY total DESC LIMIT 10
        """).fetchall()
        top_tiempo = cur.execute("""
            SELECT alumnos.nombre,
                   ROUND(AVG(historial_banio.minutos), 1) AS promedio,
                   MAX(historial_banio.minutos) AS maximo, COUNT(*) AS total
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            GROUP BY alumnos.id ORDER BY promedio DESC LIMIT 10
        """).fetchall()
        salidas_por_curso = cur.execute("""
            SELECT alumnos.curso, COUNT(*) AS total
            FROM historial_global JOIN alumnos ON alumnos.id = historial_global.alumno_id
            GROUP BY alumnos.curso ORDER BY total DESC
        """).fetchall()
        solicitudes = cur.execute("""
            SELECT usuario, nombre, comentario, estado, created_at
            FROM solicitudes_reset ORDER BY id DESC LIMIT 20
        """).fetchall()
        total_salidas = cur.execute("SELECT COUNT(*) AS c FROM historial_global").fetchone()["c"]
        total_banio   = cur.execute("SELECT COUNT(*) AS c FROM historial_banio").fetchone()["c"]
        salidas_hoy   = cur.execute(
            "SELECT COUNT(*) AS c FROM historial_global WHERE DATE(hora_salida)=DATE('now')"
        ).fetchone()["c"]
        pendientes    = cur.execute(
            "SELECT COUNT(*) AS c FROM solicitudes_reset WHERE estado='pendiente'"
        ).fetchone()["c"]

    conn.close()

    return render_template(
        "reportes.html",
        usuario=session.get("usuario"),
        salidas_por_dia=[dict(r) for r in salidas_por_dia],
        top_alumnos=top_alumnos,
        top_tiempo=top_tiempo,
        salidas_por_curso=salidas_por_curso,
        solicitudes=solicitudes,
        total_salidas=total_salidas,
        total_banio=total_banio,
        salidas_hoy=salidas_hoy,
        pendientes=pendientes,
    )


# ============================
# PANEL DE CONSERJERÍA
# ============================

@app.route("/conserjeria")
def panel_conserjeria():
    if session.get("rol") != "conserjeria":
        return redirect("/login")
    return render_template("panel_conserjeria.html")


@app.route("/conserjeria/alumno")
def conserjeria_alumno():
    if session.get("rol") != "conserjeria":
        return jsonify({"ok": False, "error": "Acceso denegado"})

    query = request.args.get("query", "").strip().lower()
    if not query:
        return jsonify({"ok": False, "error": "No se envió ningún nombre o ID"})

    centro_id = get_centro_id()
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if centro_id:
        alumno = cur.execute("""
            SELECT * FROM alumnos
            WHERE (lower(nombre) LIKE ? OR id = ?) AND centro_id = ? LIMIT 1
        """, (f"%{query}%", query, centro_id)).fetchone()
    else:
        alumno = cur.execute("""
            SELECT * FROM alumnos WHERE lower(nombre) LIKE ? OR id = ? LIMIT 1
        """, (f"%{query}%", query)).fetchone()
    conn.close()

    if not alumno:
        return jsonify({"ok": False, "error": "Alumno no encontrado"})

    return jsonify({
        "ok": True,
        "alumno": {
            "id":         alumno["id"],
            "nombre":     alumno["nombre"],
            "curso":      alumno["curso"],
            "genero":     alumno["genero"],
            "autorizado": alumno["autorizado"],
            "foto_url":   alumno["foto_url"]
        }
    })


@app.route("/conserjeria/autorizados")
def conserjeria_autorizados():
    if session.get("rol") != "conserjeria":
        return jsonify({"ok": False, "error": "Acceso denegado"})

    centro_id = get_centro_id()
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if centro_id:
        alumnos = cur.execute("""
            SELECT id, nombre, curso, genero, autorizado FROM alumnos
            WHERE autorizado = 1 AND centro_id = ? ORDER BY nombre ASC
        """, (centro_id,)).fetchall()
    else:
        alumnos = cur.execute("""
            SELECT id, nombre, curso, genero, autorizado FROM alumnos
            WHERE autorizado = 1 ORDER BY nombre ASC
        """).fetchall()
    conn.close()

    return jsonify({"ok": True, "alumnos": [dict(a) for a in alumnos]})


# ============================
# HALL OF FAME DEL BAÑO
# ============================

@app.route("/hall_of_fame")
def hall_of_fame():
    if not puede_ver_hall_of_fame():
        return redirect("/login")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if centro_id:
        en_banio_rows = cur.execute("""
            SELECT alumnos.nombre AS alumno, alumnos.curso, en_banio.hora_entrada,
                   CAST((strftime('%s','now') - strftime('%s', en_banio.hora_entrada)) / 60 AS INT) AS minutos
            FROM en_banio JOIN alumnos ON alumnos.id = en_banio.alumno_id
            WHERE en_banio.centro_id = ? ORDER BY en_banio.hora_entrada ASC
        """, (centro_id,)).fetchall()
    else:
        en_banio_rows = cur.execute("""
            SELECT alumnos.nombre AS alumno, alumnos.curso, en_banio.hora_entrada,
                   CAST((strftime('%s','now') - strftime('%s', en_banio.hora_entrada)) / 60 AS INT) AS minutos
            FROM en_banio JOIN alumnos ON alumnos.id = en_banio.alumno_id
            ORDER BY en_banio.hora_entrada ASC
        """).fetchall()

    en_banio_json = json.dumps([
        {"alumno": r["alumno"], "curso": r["curso"], "hora_entrada": r["hora_entrada"], "minutos": r["minutos"] or 0}
        for r in en_banio_rows
    ])

    if centro_id:
        top_viajes = cur.execute("""
            SELECT alumnos.nombre, alumnos.curso, alumnos.genero, COUNT(*) AS total
            FROM historial_global JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE historial_global.centro_id = ?
            GROUP BY alumnos.id ORDER BY total DESC LIMIT 10
        """, (centro_id,)).fetchall()
        top_tiempo = cur.execute("""
            SELECT alumnos.nombre, alumnos.curso,
                   ROUND(AVG(historial_banio.minutos), 1) AS promedio,
                   MAX(historial_banio.minutos) AS maximo, COUNT(*) AS total
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            WHERE historial_banio.centro_id = ?
            GROUP BY alumnos.id ORDER BY promedio DESC LIMIT 10
        """, (centro_id,)).fetchall()
        total_salidas        = cur.execute("SELECT COUNT(*) AS c FROM historial_global WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        total_alumnos_unicos = cur.execute("SELECT COUNT(DISTINCT alumno_id) AS c FROM historial_global WHERE centro_id = ?", (centro_id,)).fetchone()["c"]
        record_row           = cur.execute("SELECT MAX(minutos) AS m FROM historial_banio WHERE centro_id = ?", (centro_id,)).fetchone()
        logro_mas_viajes     = top_viajes[0] if top_viajes else None
        logro_maraton_row    = cur.execute("""
            SELECT alumnos.nombre, ROUND(AVG(historial_banio.minutos), 1) AS promedio
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            WHERE historial_banio.centro_id = ?
            GROUP BY alumnos.id ORDER BY promedio DESC LIMIT 1
        """, (centro_id,)).fetchone()
        logro_maximo_row = cur.execute("""
            SELECT alumnos.nombre, historial_banio.minutos
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            WHERE historial_banio.centro_id = ?
            ORDER BY historial_banio.minutos DESC LIMIT 1
        """, (centro_id,)).fetchone()
        dia_mas_activo_row = cur.execute("""
            SELECT DATE(hora_salida) AS dia, COUNT(*) AS c FROM historial_global
            WHERE centro_id = ? GROUP BY dia ORDER BY c DESC LIMIT 1
        """, (centro_id,)).fetchone()
        hora_pico_row = cur.execute("""
            SELECT strftime('%H:00', hora_salida) AS hora, COUNT(*) AS c FROM historial_global
            WHERE centro_id = ? GROUP BY hora ORDER BY c DESC LIMIT 1
        """, (centro_id,)).fetchone()
        total_chicos = cur.execute("""
            SELECT COUNT(*) AS c FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE alumnos.genero = 'M' AND historial_global.centro_id = ?
        """, (centro_id,)).fetchone()["c"]
        total_chicas = cur.execute("""
            SELECT COUNT(*) AS c FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE alumnos.genero = 'F' AND historial_global.centro_id = ?
        """, (centro_id,)).fetchone()["c"]
        tiempo_medio_row = cur.execute(
            "SELECT ROUND(AVG(minutos), 1) AS m FROM historial_banio WHERE centro_id = ?", (centro_id,)
        ).fetchone()
        curso_mas_activo_row = cur.execute("""
            SELECT alumnos.curso, COUNT(*) AS c FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id
            WHERE historial_global.centro_id = ?
            GROUP BY alumnos.curso ORDER BY c DESC LIMIT 1
        """, (centro_id,)).fetchone()
    else:
        top_viajes = cur.execute("""
            SELECT alumnos.nombre, alumnos.curso, alumnos.genero, COUNT(*) AS total
            FROM historial_global JOIN alumnos ON alumnos.id = historial_global.alumno_id
            GROUP BY alumnos.id ORDER BY total DESC LIMIT 10
        """).fetchall()
        top_tiempo = cur.execute("""
            SELECT alumnos.nombre, alumnos.curso,
                   ROUND(AVG(historial_banio.minutos), 1) AS promedio,
                   MAX(historial_banio.minutos) AS maximo, COUNT(*) AS total
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            GROUP BY alumnos.id ORDER BY promedio DESC LIMIT 10
        """).fetchall()
        total_salidas        = cur.execute("SELECT COUNT(*) AS c FROM historial_global").fetchone()["c"]
        total_alumnos_unicos = cur.execute("SELECT COUNT(DISTINCT alumno_id) AS c FROM historial_global").fetchone()["c"]
        record_row           = cur.execute("SELECT MAX(minutos) AS m FROM historial_banio").fetchone()
        logro_mas_viajes     = top_viajes[0] if top_viajes else None
        logro_maraton_row    = cur.execute("""
            SELECT alumnos.nombre, ROUND(AVG(historial_banio.minutos), 1) AS promedio
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            GROUP BY alumnos.id ORDER BY promedio DESC LIMIT 1
        """).fetchone()
        logro_maximo_row = cur.execute("""
            SELECT alumnos.nombre, historial_banio.minutos
            FROM historial_banio JOIN alumnos ON alumnos.id = historial_banio.alumno_id
            ORDER BY historial_banio.minutos DESC LIMIT 1
        """).fetchone()
        dia_mas_activo_row = cur.execute("""
            SELECT DATE(hora_salida) AS dia, COUNT(*) AS c FROM historial_global
            GROUP BY dia ORDER BY c DESC LIMIT 1
        """).fetchone()
        hora_pico_row = cur.execute("""
            SELECT strftime('%H:00', hora_salida) AS hora, COUNT(*) AS c FROM historial_global
            GROUP BY hora ORDER BY c DESC LIMIT 1
        """).fetchone()
        total_chicos = cur.execute("""
            SELECT COUNT(*) AS c FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id WHERE alumnos.genero = 'M'
        """).fetchone()["c"]
        total_chicas = cur.execute("""
            SELECT COUNT(*) AS c FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id WHERE alumnos.genero = 'F'
        """).fetchone()["c"]
        tiempo_medio_row = cur.execute("SELECT ROUND(AVG(minutos), 1) AS m FROM historial_banio").fetchone()
        curso_mas_activo_row = cur.execute("""
            SELECT alumnos.curso, COUNT(*) AS c FROM historial_global
            JOIN alumnos ON alumnos.id = historial_global.alumno_id
            GROUP BY alumnos.curso ORDER BY c DESC LIMIT 1
        """).fetchone()

    record_minutos      = record_row["m"] or 0
    podio               = list(top_viajes[:3]) if top_viajes else []
    logro_maraton       = logro_maraton_row if logro_maraton_row else None
    logro_maximo        = logro_maximo_row  if logro_maximo_row  else None
    dia_mas_activo      = dia_mas_activo_row["dia"]  if dia_mas_activo_row  else None
    hora_pico           = hora_pico_row["hora"]       if hora_pico_row       else None
    tiempo_medio_global = tiempo_medio_row["m"]       if tiempo_medio_row    else None
    curso_mas_activo    = curso_mas_activo_row["curso"] if curso_mas_activo_row else None

    conn.close()

    colores = [
        "linear-gradient(135deg,#f4c430,#e07b00)",
        "linear-gradient(135deg,#a8b8c8,#7a8fa0)",
        "linear-gradient(135deg,#cd7f32,#8b4e1a)",
        "linear-gradient(135deg,#00b4d8,#0077b6)",
        "linear-gradient(135deg,#2dd4a0,#0f9070)",
        "linear-gradient(135deg,#f25c5c,#b02020)",
        "linear-gradient(135deg,#8b5cf6,#5b21b6)",
        "linear-gradient(135deg,#f4a942,#c07010)",
        "linear-gradient(135deg,#ec4899,#9d1760)",
        "linear-gradient(135deg,#3b82f6,#1d4ed8)",
    ]

    return render_template(
        "hall_of_fame.html",
        usuario=session.get("usuario"),
        anio_actual=datetime.now().year,
        top_viajes=[dict(r) for r in top_viajes],
        top_tiempo=[dict(r) for r in top_tiempo],
        podio=[dict(r) for r in podio],
        total_salidas=total_salidas,
        total_alumnos_unicos=total_alumnos_unicos,
        record_minutos=record_minutos,
        logro_mas_viajes=dict(logro_mas_viajes) if logro_mas_viajes else None,
        logro_maraton=dict(logro_maraton) if logro_maraton else None,
        logro_maximo=dict(logro_maximo) if logro_maximo else None,
        dia_mas_activo=dia_mas_activo,
        hora_pico=hora_pico,
        total_chicos=total_chicos,
        total_chicas=total_chicas,
        tiempo_medio_global=tiempo_medio_global,
        curso_mas_activo=curso_mas_activo,
        colores=colores,
        en_banio_json=en_banio_json,
    )


# ============================
# NOTIFICACIONES
# ============================

@app.route("/notificaciones_profesor")
def notificaciones_profesor():
    profesor_id = session.get("profesor_id")
    centro_id   = get_centro_id()

    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if centro_id:
        cur.execute("""
            SELECT id, titulo, mensaje, fecha, leida FROM notificaciones
            WHERE profesor_id = ? AND centro_id = ? ORDER BY fecha DESC
        """, (profesor_id, centro_id))
    else:
        cur.execute("""
            SELECT id, titulo, mensaje, fecha, leida FROM notificaciones
            WHERE profesor_id = ? ORDER BY fecha DESC
        """, (profesor_id,))
    filas = cur.fetchall()
    conn.close()

    return jsonify([
        {"id": i, "titulo": t, "mensaje": m, "fecha": f, "leida": l}
        for (i, t, m, f, l) in filas
    ])


@app.route("/notificaciones/eliminar", methods=["POST"])
def eliminar_notificacion():
    data     = request.get_json()
    notif_id = data.get("id")

    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM notificaciones WHERE id = ?", (notif_id,))
    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/notificaciones/eliminar_todas", methods=["POST"])
def eliminar_todas():
    profesor_id = session.get("profesor_id")
    centro_id   = get_centro_id()

    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if centro_id:
        cur.execute(
            "DELETE FROM notificaciones WHERE profesor_id = ? AND centro_id = ?",
            (profesor_id, centro_id)
        )
    else:
        cur.execute("DELETE FROM notificaciones WHERE profesor_id = ?", (profesor_id,))
    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/estado_mantenimiento")
def estado_mantenimiento():
    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    cur = conn.cursor()
    if centro_id:
        cur.execute(
            "SELECT valor FROM config WHERE clave = 'hora_mantenimiento' AND centro_id = ?",
            (centro_id,)
        )
    else:
        cur.execute("SELECT valor FROM config WHERE clave = 'hora_mantenimiento'")
    fila = cur.fetchone()
    conn.close()

    if fila and fila[0]:
        return jsonify({"programado": True, "hora": fila[0]})
    return jsonify({"programado": False})


# ============================
# API LIVE — DASHBOARD TIEMPO REAL
# ============================

@app.route("/api/live")
def api_live():
    if not es_coordinador_o_tde():
        return jsonify({"error": "No autenticado"}), 401

    centro_id = get_centro_id()
    filtro_curso  = request.args.get("curso", "").strip()
    filtro_alumno = request.args.get("alumno", "").strip()
    filtro_fecha  = request.args.get("fecha", "").strip()

    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    conditions = []
    params = []

    if centro_id:
        conditions.append("hg.centro_id = ?")
        params.append(centro_id)
    if filtro_curso:
        conditions.append("a.curso = ?")
        params.append(filtro_curso)
    if filtro_alumno:
        conditions.append("lower(a.nombre) LIKE ?")
        params.append(f"%{filtro_alumno.lower()}%")
    if filtro_fecha:
        conditions.append("DATE(hg.hora_salida) = ?")
        params.append(filtro_fecha)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    cur.execute(f"""
        SELECT a.nombre AS alumno, p.usuario AS profesor, a.curso,
               hg.hora_salida, hg.hora_regreso,
               CASE WHEN hg.hora_regreso IS NULL THEN 'En el baño' ELSE 'Regresó' END AS estado
        FROM historial_global hg
        JOIN alumnos a ON a.id = hg.alumno_id
        LEFT JOIN profesores p ON p.centro_id = hg.centro_id
        {where}
        ORDER BY hg.id DESC LIMIT 100
    """, params)
    historial = [dict(r) for r in cur.fetchall()]

    total_params = [centro_id] if centro_id else []
    total_where  = "WHERE centro_id = ?" if centro_id else ""
    total = cur.execute(
        f"SELECT COUNT(*) AS c FROM historial_global {total_where}", total_params
    ).fetchone()["c"]

    if centro_id:
        en_banio = cur.execute("""
            SELECT a.nombre, a.curso, eb.hora_entrada,
                   CAST((strftime('%s','now') - strftime('%s', eb.hora_entrada)) / 60 AS INT) AS minutos
            FROM en_banio eb JOIN alumnos a ON a.id = eb.alumno_id
            WHERE eb.centro_id = ? ORDER BY eb.hora_entrada ASC
        """, (centro_id,)).fetchall()
    else:
        en_banio = cur.execute("""
            SELECT a.nombre, a.curso, eb.hora_entrada,
                   CAST((strftime('%s','now') - strftime('%s', eb.hora_entrada)) / 60 AS INT) AS minutos
            FROM en_banio eb JOIN alumnos a ON a.id = eb.alumno_id
            ORDER BY eb.hora_entrada ASC
        """).fetchall()

    if centro_id:
        horas_rows = cur.execute("""
            SELECT strftime('%H:00', hora_salida) AS hora, COUNT(*) AS c FROM historial_global
            WHERE hora_salida >= datetime('now', '-24 hours') AND centro_id = ?
            GROUP BY hora ORDER BY hora ASC
        """, (centro_id,)).fetchall()
    else:
        horas_rows = cur.execute("""
            SELECT strftime('%H:00', hora_salida) AS hora, COUNT(*) AS c FROM historial_global
            WHERE hora_salida >= datetime('now', '-24 hours')
            GROUP BY hora ORDER BY hora ASC
        """).fetchall()

    conn.close()

    return jsonify({
        "historial": historial,
        "total":     total,
        "en_banio":  [dict(r) for r in en_banio],
        "horas": {
            "labels": [r["hora"] for r in horas_rows],
            "values": [r["c"]    for r in horas_rows]
        }
    })

# ================================================================
# PASO 1: Añadir esta ruta a app.py
# Pegar JUSTO ANTES del bloque "if __name__ == '__main__':" al final
# ================================================================

@app.route("/panel_superadmin")
def panel_superadmin():
    """Panel exclusivo superadmin."""
    if not es_superadmin():
        return redirect("/panel_tecnico")

    centro_id = get_centro_id()
    conn = sqlite3.connect("servicioedu.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS centros (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre  TEXT NOT NULL UNIQUE,
            creado  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()

    centros_rows = cur.execute("SELECT * FROM centros ORDER BY nombre ASC").fetchall()
    centros_global = []
    for c in centros_rows:
        cid = c["id"]
        mant_row = cur.execute("SELECT valor FROM config WHERE clave='modo_mantenimiento' AND centro_id=?", (cid,)).fetchone()
        centros_global.append({
            "id":          cid,
            "nombre":      c["nombre"],
            "creado":      c["creado"],
            "profesores":  cur.execute("SELECT COUNT(*) AS n FROM profesores WHERE centro_id=?", (cid,)).fetchone()["n"],
            "alumnos":     cur.execute("SELECT COUNT(*) AS n FROM alumnos WHERE centro_id=?", (cid,)).fetchone()["n"],
            "cursos":      cur.execute("SELECT COUNT(*) AS n FROM cursos WHERE centro_id=?", (cid,)).fetchone()["n"],
            "historial":   cur.execute("SELECT COUNT(*) AS n FROM historial_global WHERE centro_id=?", (cid,)).fetchone()["n"],
            "en_banio":    cur.execute("SELECT COUNT(*) AS n FROM en_banio WHERE centro_id=?", (cid,)).fetchone()["n"],
            "cola":        cur.execute("SELECT COUNT(*) AS n FROM cola_banio WHERE centro_id=?", (cid,)).fetchone()["n"],
            "hoy":         cur.execute("SELECT COUNT(*) AS n FROM historial_global WHERE centro_id=? AND DATE(hora_salida)=DATE('now')", (cid,)).fetchone()["n"],
            "mantenimiento": mant_row["valor"] == "1" if mant_row else False,
        })

    stats_global = {
        "total_centros":    len(centros_global),
        "total_profesores": cur.execute("SELECT COUNT(*) AS n FROM profesores").fetchone()["n"],
        "total_alumnos":    cur.execute("SELECT COUNT(*) AS n FROM alumnos").fetchone()["n"],
        "total_en_banio":   cur.execute("SELECT COUNT(*) AS n FROM en_banio").fetchone()["n"],
        "total_hoy":        cur.execute("SELECT COUNT(*) AS n FROM historial_global WHERE DATE(hora_salida)=DATE('now')").fetchone()["n"],
    }
    conn.close()

    return render_template(
        "panel_superadmin.html",
        usuario=session.get("usuario"),
        centro_activo=centro_id,
        centros_global=centros_global,
        stats_global=stats_global,
    )


# ================================================================
# PASO 2: En la función login(), cambiar el redirect del superadmin
# Busca la línea:  return redirect("/panel_tecnico")
# dentro del bloque elif "tecnico" in roles_profesor:
# Y cámbiala por:
# ================================================================

          # <-- técnico normal va aquí


# ================================================================
# PASO 3: En superadmin_cambiar_centro(), ya tienes esto bien:
#   session["centro_nombre"] = centro["nombre"]
# Pero asegúrate de que panel_superadmin.html está en /templates/
# ================================================================
# ============================
# ARRANQUE
# ============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)