import os
import csv
import io
from flask import Flask, render_template, request, redirect, url_for, session, Response
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_secreta_cecytej_energia_2026')

# Configuración de conexión compatible con Local (XAMPP) y Nube (Aiven / Render)
db_config = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': int(os.environ.get('DB_PORT', 3306)),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'database': os.environ.get('DB_NAME', 'calculadora_energetica')
}

def obtener_conexion():
    return mysql.connector.connect(**db_config)

def obtener_tarifa_actual(cursor):
    cursor.execute("SELECT * FROM tarifas ORDER BY id_tarifa DESC LIMIT 1")
    tarifa = cursor.fetchone()
    if not tarifa:
        tarifa = {
            'costo_basico': 1.015,
            'costo_intermedio': 1.239,
            'costo_excedente': 3.620,
            'incremento_mensual_pct': 0.35
        }
    return tarifa

def calcular_costo_escalonado(kwh_mensual, tarifa):
    kwh = float(kwh_mensual)
    p_basico = float(tarifa['costo_basico'])
    p_intermedio = float(tarifa['costo_intermedio'])
    p_excedente = float(tarifa['costo_excedente'])

    if kwh <= 75:
        costo = kwh * p_basico
    elif kwh <= 140:
        costo = (75 * p_basico) + ((kwh - 75) * p_intermedio)
    else:
        costo = (75 * p_basico) + (65 * p_intermedio) + ((kwh - 140) * p_excedente)
    return round(costo, 2)

def calcular_desglose_recibo_bimestral(kwh_mensual, tarifa):
    kwh_bim = round(float(kwh_mensual) * 2, 2)
    p_basico = float(tarifa['costo_basico'])
    p_intermedio = float(tarifa['costo_intermedio'])
    p_excedente = float(tarifa['costo_excedente'])

    kwh_basico = min(kwh_bim, 150.0)
    kwh_intermedio = min(max(kwh_bim - 150.0, 0.0), 130.0)
    kwh_excedente = max(kwh_bim - 280.0, 0.0)

    sub_basico = round(kwh_basico * p_basico, 2)
    sub_intermedio = round(kwh_intermedio * p_intermedio, 2)
    sub_excedente = round(kwh_excedente * p_excedente, 2)
    subtotal_energia = round(sub_basico + sub_intermedio + sub_excedente, 2)

    porcentaje_barra = min(max((kwh_bim / 400.0) * 100.0, 2.0), 98.0)

    return {
        'kwh_total': round(kwh_bim, 1),
        'kwh_basico': round(kwh_basico, 1),
        'kwh_intermedio': round(kwh_intermedio, 1),
        'kwh_excedente': round(kwh_excedente, 1),
        'precio_basico': f"{p_basico:.3f}",
        'precio_intermedio': f"{p_intermedio:.3f}",
        'precio_excedente': f"{p_excedente:.3f}",
        'sub_basico': f"{sub_basico:.2f}",
        'sub_intermedio': f"{sub_intermedio:.2f}",
        'sub_excedente': f"{sub_excedente:.2f}",
        'subtotal_energia': f"{subtotal_energia:.2f}",
        'porcentaje_barra': round(porcentaje_barra, 1)
    }

def clasificar_nivel_consumo(kwh_mensual):
    kwh = float(kwh_mensual)
    if kwh <= 75:
        return {'texto': 'Consumo Básico (Subsidio Alto)', 'clase': 'bg-success text-white'}
    elif kwh <= 140:
        return {'texto': 'Consumo Intermedio (Moderado)', 'clase': 'bg-warning text-dark'}
    else:
        return {'texto': 'Consumo Excedente (Sin Subsidio)', 'clase': 'bg-danger text-white'}

# --- MANEJADOR GLOBAL DE ERRORES (EVITA PANTALLAS 404 NOT FOUND) ---

@app.errorhandler(404)
def pagina_no_encontrada(e):
    if 'usuario_id' in session:
        return redirect(url_for('index'))
    return redirect(url_for('login'))

# --- RUTAS DE AUTENTICACIÓN ---

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'GET':
        return render_template('login.html', abrir_registro=True)

    nombre = request.form.get('nombre', '').strip()
    correo = request.form.get('correo', '').strip()
    password = request.form.get('password', '')

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id_usuario FROM usuarios WHERE correo = %s", (correo,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return render_template(
            'login.html',
            error="Este correo ya está registrado. Intenta iniciar sesión.",
            abrir_registro=True
        )

    hashed_pw = generate_password_hash(password)
    cursor.execute(
        "INSERT INTO usuarios (nombre, correo, password) VALUES (%s, %s, %s)",
        (nombre, correo, hashed_pw)
    )
    conn.commit()
    nuevo_id = cursor.lastrowid
    cursor.close()
    conn.close()

    session['usuario_id'] = nuevo_id
    session['usuario_nombre'] = nombre
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    exito = None
    if request.method == 'POST':
        correo = request.form.get('correo', '').strip()
        password = request.form.get('password', '')

        conn = obtener_conexion()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios WHERE correo = %s", (correo,))
        usuario = cursor.fetchone()
        cursor.close()
        conn.close()

        if usuario and check_password_hash(usuario['password'], password):
            session['usuario_id'] = usuario['id_usuario']
            session['usuario_nombre'] = usuario['nombre']
            return redirect(url_for('index'))
        else:
            error = "Correo electrónico o contraseña incorrectos."

    return render_template('login.html', error=error, exito=exito, abrir_registro=False)

@app.route('/logout')
def logout():
    if 'usuario_id' in session:
        try:
            conn = obtener_conexion()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM electrodomesticos WHERE id_usuario = %s", (session['usuario_id'],))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception:
            pass
    session.clear()
    return redirect(url_for('login'))

@app.route('/limpiar_al_salir', methods=['POST'])
def limpiar_al_salir():
    if 'usuario_id' in session:
        try:
            conn = obtener_conexion()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM electrodomesticos WHERE id_usuario = %s", (session['usuario_id'],))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception:
            pass
    return ('', 204)

# --- RUTA PRINCIPAL DEL DASHBOARD ---

@app.route('/')
def index():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    usuario_id = session['usuario_id']
    simulacion = session.pop('simulacion', None)
    comentario_enviado = session.pop('comentario_enviado', False)

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    tarifa = obtener_tarifa_actual(cursor)
    cursor.execute(
        "SELECT * FROM electrodomesticos WHERE id_usuario = %s ORDER BY id_electrodomestico DESC",
        (usuario_id,)
    )
    aparatos = cursor.fetchall()

    total_kwh = 0.0
    nombres_aparatos = []
    consumos_aparatos = []

    for ap in aparatos:
        kwh_ap = float(ap['consumo_kwh_mes'])
        total_kwh += kwh_ap
        ap['costo_estimado_pesos'] = calcular_costo_escalonado(kwh_ap, tarifa)
        nombres_aparatos.append(ap['nombre'])
        consumos_aparatos.append(round(kwh_ap, 2))

    total_kwh = round(total_kwh, 2)
    total_costo = calcular_costo_escalonado(total_kwh, tarifa)
    pct_inc = float(tarifa.get('incremento_mensual_pct', 0.35))
    proximo_mes = round(total_costo * (1 + (pct_inc / 100.0)), 2)

    totales = {
        'total_kwh': total_kwh,
        'total_costo': f"{total_costo:.2f}",
        'proximo_mes': f"{proximo_mes:.2f}",
        'pct_incremento': pct_inc,
        'nivel': clasificar_nivel_consumo(total_kwh)
    }

    desglose_recibo = calcular_desglose_recibo_bimestral(total_kwh, tarifa)

    cursor.close()
    conn.close()

    return render_template(
        'index.html',
        aparatos=aparatos,
        totales=totales,
        tarifa=tarifa,
        desglose_recibo=desglose_recibo,
        nombres_aparatos=nombres_aparatos,
        consumos_aparatos=consumos_aparatos,
        simulacion=simulacion,
        comentario_enviado=comentario_enviado
    )

# --- OPERACIONES CRUD DE ELECTRODOMÉSTICOS ---

@app.route('/agregar', methods=['POST'])
def agregar():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    usuario_id = session['usuario_id']
    nombre = request.form.get('nombre', '').strip()
    potencia = float(request.form.get('potencia', 0))
    horas = float(request.form.get('horas', 0))
    dias = int(request.form.get('dias', 30))
    imagen_url = request.form.get('imagen_url', '').strip()

    consumo_kwh_mes = round((potencia * horas * dias) / 1000.0, 2)

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)
    tarifa = obtener_tarifa_actual(cursor)
    costo_estimado = calcular_costo_escalonado(consumo_kwh_mes, tarifa)

    cursor.execute(
        """
        INSERT INTO electrodomesticos 
        (id_usuario, nombre, potencia_watts, horas_diarias, dias_mes, consumo_kwh_mes, costo_estimado_pesos, imagen_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (usuario_id, nombre, potencia, horas, dias, consumo_kwh_mes, costo_estimado, imagen_url)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('index'))

@app.route('/editar/<int:id_electrodomestico>', methods=['GET', 'POST'])
@app.route('/actualizar/<int:id_electrodomestico>', methods=['GET', 'POST'])
def editar(id_electrodomestico):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    usuario_id = session['usuario_id']
    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        potencia = float(request.form.get('potencia', 0))
        horas = float(request.form.get('horas', 0))
        dias = int(request.form.get('dias', 30))
        imagen_url = request.form.get('imagen_url', '').strip()

        consumo_kwh_mes = round((potencia * horas * dias) / 1000.0, 2)
        tarifa = obtener_tarifa_actual(cursor)
        costo_estimado = calcular_costo_escalonado(consumo_kwh_mes, tarifa)

        cursor.execute(
            """
            UPDATE electrodomesticos
            SET nombre = %s, potencia_watts = %s, horas_diarias = %s, dias_mes = %s,
                consumo_kwh_mes = %s, costo_estimado_pesos = %s, imagen_url = %s
            WHERE id_electrodomestico = %s AND id_usuario = %s
            """,
            (nombre, potencia, horas, dias, consumo_kwh_mes, costo_estimado, imagen_url, id_electrodomestico, usuario_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('index'))

    cursor.execute(
        "SELECT * FROM electrodomesticos WHERE id_electrodomestico = %s AND id_usuario = %s",
        (id_electrodomestico, usuario_id)
    )
    aparato = cursor.fetchone()
    cursor.close()
    conn.close()

    if not aparato:
        return redirect(url_for('index'))

    return render_template('editar.html', aparato=aparato)

@app.route('/eliminar/<int:id_electrodomestico>', methods=['GET', 'POST'])
def eliminar(id_electrodomestico):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM electrodomesticos WHERE id_electrodomestico = %s AND id_usuario = %s",
        (id_electrodomestico, session['usuario_id'])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('index'))

# --- SIMULADOR, BUZÓN Y EXPORTACIÓN ---

@app.route('/simular', methods=['POST'])
def simular():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    potencia = float(request.form.get('potencia', 0))
    horas = float(request.form.get('horas', 0))
    dias = int(request.form.get('dias', 30))
    kwh = round((potencia * horas * dias) / 1000.0, 2)

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)
    tarifa = obtener_tarifa_actual(cursor)
    cursor.close()
    conn.close()

    costo = calcular_costo_escalonado(kwh, tarifa)
    session['simulacion'] = {'kwh': kwh, 'costo': f"{costo:.2f}"}
    return redirect(url_for('index'))

@app.route('/comentar', methods=['POST'])
def comentar():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    tipo = request.form.get('tipo', 'Comentario General')
    mensaje = request.form.get('mensaje', '').strip()

    if mensaje:
        conn = obtener_conexion()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO comentarios (id_usuario, tipo, mensaje) VALUES (%s, %s, %s)",
            (session['usuario_id'], tipo, mensaje)
        )
        conn.commit()
        cursor.close()
        conn.close()
        session['comentario_enviado'] = True

    return redirect(url_for('index'))

@app.route('/exportar_csv')
def exportar_csv():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)
    tarifa = obtener_tarifa_actual(cursor)
    cursor.execute(
        "SELECT * FROM electrodomesticos WHERE id_usuario = %s ORDER BY id_electrodomestico ASC",
        (session['usuario_id'],)
    )
    aparatos = cursor.fetchall()
    cursor.close()
    conn.close()

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Electrodomestico', 'Potencia (W)', 'Horas/Dia', 'Dias/Mes', 'Consumo Mensual (kWh)', 'Costo Estimado (MXN)'])

    for ap in aparatos:
        costo_ap = calcular_costo_escalonado(ap['consumo_kwh_mes'], tarifa)
        writer.writerow([
            ap['nombre'],
            ap['potencia_watts'],
            ap['horas_diarias'],
            ap['dias_mes'],
            ap['consumo_kwh_mes'],
            costo_ap
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=reporte_consumo_cfe.csv'}
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
