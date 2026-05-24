from flask import Flask, render_template_string, jsonify, request
import threading
import time
import csv
import os
from pymodbus.client import ModbusSerialClient, ModbusTcpClient

app = Flask(__name__)

# --- CONFIGURACIÓN ---
PUERTO_COM = '/dev/ttyUSB0'
BAUDRATE = 19200
ID_VARIADOR = 1
NOMBRE_ARCHIVO = 'perfil_viento.csv'
IP_SCADA = '192.168.0.50'

# --- MEMORIA COMPARTIDA ---
estado = {
    "frecuencia": 0.0,
    "viento_ms": 0.0,
    "tiempo_perfil": 0,      # Segundos transcurridos
    "modo": "DETENIDO",      
    "hardware_rtu": False,   
    "hardware_tcp": False,   
    "comando": 1             
}

cliente_modbus = ModbusSerialClient(port=PUERTO_COM, baudrate=BAUDRATE, bytesize=8, parity='N', stopbits=1, timeout=1.5)
cliente_scada = ModbusTcpClient(IP_SCADA, port=502)
modbus_lock = threading.Lock()

# =========================================================================
# ADAPTADORES UNIVERSALES MODBUS
# =========================================================================
def _write_register_universal(cliente, direccion, valor, id_nodo):
    try: cliente.write_register(direccion, valor, slave=id_nodo)
    except TypeError:
        try: cliente.write_register(direccion, valor, unit=id_nodo)
        except TypeError:
            try: cliente.write_register(direccion, valor, id_nodo)
            except TypeError: cliente.write_register(direccion, valor)

def _write_registers_universal(cliente, direccion, valores, id_nodo):
    try: cliente.write_registers(direccion, values=valores, slave=id_nodo)
    except TypeError:
        try: cliente.write_registers(direccion, values=valores, unit=id_nodo)
        except TypeError:
            try: cliente.write_registers(direccion, valores, id_nodo)
            except TypeError: cliente.write_registers(direccion, values=valores)

def _read_holding_universal(cliente, direccion, cantidad, id_nodo):
    try: return cliente.read_holding_registers(direccion, count=cantidad, slave=id_nodo)
    except TypeError:
        try: return cliente.read_holding_registers(direccion, count=cantidad, unit=id_nodo)
        except TypeError:
            try: return cliente.read_holding_registers(direccion, cantidad, id_nodo)
            except TypeError: return cliente.read_holding_registers(direccion, count=cantidad)
# =========================================================================

# --- HILO 1: CONTROL POWERFLEX (RTU) ---
def hilo_powerflex():
    while True:
        try:
            if cliente_modbus.connect():
                try:
                    if hasattr(cliente_modbus, 'socket') and cliente_modbus.socket is not None:
                        cliente_modbus.socket.setRTS(False)
                        cliente_modbus.socket.setDTR(False)
                except Exception: pass

                estado["hardware_rtu"] = True
                ref = int(estado["frecuencia"] * 100)
                
                with modbus_lock:
                    _write_register_universal(cliente_modbus, 8192, estado["comando"], ID_VARIADOR)
                    _write_register_universal(cliente_modbus, 8193, ref, ID_VARIADOR)
            else:
                estado["hardware_rtu"] = False
        except Exception as e:
            estado["hardware_rtu"] = False
            print(f"[RTU Error] {e}")
        time.sleep(1)

# --- HILO 2: COMUNICACIÓN SCADA (TCP) ---
def hilo_scada():
    while True:
        try:
            if cliente_scada.connect():
                estado_motor = 1 if estado["comando"] == 18 else 0
                frec_actual_escala = int(estado["frecuencia"] * 100)
                
                # Si esto falla, saltará directo al except inferior rompiendo la "conexión zombi"
                _write_registers_universal(cliente_scada, 0, [estado_motor, frec_actual_escala], 1)
                respuesta = _read_holding_universal(cliente_scada, 2, 3, 1)
                
                if hasattr(respuesta, 'isError') and respuesta.isError():
                    raise Exception("Respuesta de error Modbus del SCADA")
                    
                # Si llegamos aquí, la comunicación TCP es 100% exitosa
                estado["hardware_tcp"] = True
                peticion_scada = respuesta.registers[0]
                boton_arranque_scada = respuesta.registers[1]
                frec_scada = respuesta.registers[2]

                if peticion_scada == 1:
                    estado["modo"] = "SCADA"
                    estado["comando"] = 18 if boton_arranque_scada == 1 else 1
                    estado["frecuencia"] = min(130.0, max(0.0, frec_scada / 100.0))
            else:
                estado["hardware_tcp"] = False
        except Exception as e:
            estado["hardware_tcp"] = False
            cliente_scada.close() # <-- Esto obliga a reiniciar el socket, matando conexiones fantasma
            print(f"[TCP SCADA Error] Desconectado: {e}")
        time.sleep(0.5)

# --- HILO 3: EJECUCIÓN DE PERFIL (CSV) ---
def ejecutar_perfil():
    ruta_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), NOMBRE_ARCHIVO)
    if not os.path.exists(ruta_csv): return
    
    try:
        perfil = []
        with open(ruta_csv, mode='r', encoding='utf-8') as archivo:
            lector = csv.DictReader(archivo)
            for fila in lector:
                try:
                    perfil.append({'viento': float(fila['viento']), 'frecuencia': float(fila['frecuencia'])})
                except: pass

        estado["tiempo_perfil"] = 0
        
        for i, dato in enumerate(perfil):
            if estado["modo"] != "PERFIL": break
            
            estado["frecuencia"] = dato['frecuencia']
            estado["viento_ms"] = dato['viento']
            estado["tiempo_perfil"] = i # Segundos
            time.sleep(1)

        if estado["modo"] == "PERFIL":
            estado["modo"] = "DETENIDO"
            estado["comando"] = 1
            estado["viento_ms"] = 0.0
            estado["tiempo_perfil"] = 0
            
    except Exception as e:
        print(f"Error parseando el archivo de viento: {e}")

# --- RUTAS WEB ---
# Usamos render_template_string para no tener que crear archivos extra en la Raspberry.
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Gateway Eólico - Uniandes</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .led { width: 15px; height: 15px; border-radius: 50%; display: inline-block; vertical-align: middle;}
        .bg-on { background-color: #2ecc71; box-shadow: 0 0 10px #2ecc71; }
        .bg-off { background-color: #e74c3c; }
        .display-frec { font-size: 3rem; font-weight: bold; color: #2c3e50; }
    </style>
</head>
<body class="bg-light">
    <div class="container py-3">
        <div class="card shadow-sm mb-3">
            <div class="card-body text-center">
                <h5 class="text-muted">EMULADOR EÓLICO 300W</h5>
                <div class="display-frec"><span id="frec">0.0</span> <small class="h4">Hz</small></div>
                <div class="text-primary fw-bold mb-2">Viento: <span id="viento_actual">0.0</span> m/s</div>
                <div class="badge bg-primary h5 p-2" id="modo_txt">CARGANDO...</div>
            </div>
        </div>

        <div class="card shadow-sm mb-3">
            <div class="card-body">
                <h6 class="card-title text-center text-muted">Perfil Dinámico de Viento</h6>
                <canvas id="graficaViento" height="100"></canvas>
            </div>
        </div>

        <div class="card shadow-sm mb-3">
            <div class="card-body">
                <div class="input-group mb-3">
                    <span class="input-group-text">Frec. Manual (Hz)</span>
                    <input type="number" id="input_frec" class="form-control text-center" value="60.0" step="0.1" min="0" max="130">
                    <button class="btn btn-primary" id="btn_fijar" onclick="fijarFrecuencia()">Aplicar</button>
                </div>
                <div class="row g-2 mb-2">
                    <div class="col-6"><button id="btn_start" onclick="cmd('start')" class="btn btn-success w-100 py-2">ARRANCAR</button></div>
                    <div class="col-6"><button id="btn_stop" onclick="cmd('stop')" class="btn btn-danger w-100 py-2">PARADA</button></div>
                </div>
                <button id="btn_perfil" onclick="cmd('perfil')" class="btn btn-dark w-100 py-2 mb-2">Cargar Perfil de Viento (.CSV)</button>
                <button id="btn_recuperar" onclick="cmd('recuperar')" class="btn btn-warning w-100 py-2" style="display:none;">Recuperar Control de SCADA</button>
            </div>
        </div>

        <div class="card border-0 bg-transparent">
            <div class="card-body p-0">
                <div class="d-flex justify-content-between mb-1">
                    <small class="text-muted fw-bold">PowerFlex (RTU):</small> <span id="led_rtu" class="led bg-off"></span>
                </div>
                <div class="d-flex justify-content-between">
                    <small class="text-muted fw-bold">SCADA (TCP):</small> <span id="led_tcp" class="led bg-off"></span>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Configuración de Chart.js
        const ctx = document.getElementById('graficaViento').getContext('2d');
        const chart = new Chart(ctx, {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Viento (m/s)', data: [], borderColor: '#3498db', borderWidth: 2, pointRadius: 0, tension: 0.2 }] },
            options: {
                responsive: true, animation: false,
                scales: {
                    x: { title: { display: true, text: 'Tiempo (s)' }, grid: { display: false } },
                    y: { title: { display: true, text: 'm/s' }, suggestedMin: 0 } // Se ajustará solo hacia arriba
                },
                plugins: { legend: { display: false } }
            }
        });

        let ultimoTiempo = -1;

        function cmd(accion) { fetch('/api/control/' + accion, {method:'POST'}); }
        
        function fijarFrecuencia() {
            let valorNum = parseFloat(document.getElementById('input_frec').value.replace(',', '.'));
            if(isNaN(valorNum) || valorNum < 0 || valorNum > 130) return alert("Frecuencia inválida.");
            fetch('/api/set_frec', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frecuencia: valorNum }) });
            cmd('start'); 
        }
        
        setInterval(() => {
            fetch('/api/status').then(r => r.json()).then(data => {
                document.getElementById('frec').innerText = data.frecuencia.toFixed(1);
                document.getElementById('viento_actual').innerText = data.viento_ms.toFixed(2);
                document.getElementById('modo_txt').innerText = "MODO: " + data.modo;
                
                document.getElementById('led_rtu').className = 'led ' + (data.hardware_rtu ? 'bg-on' : 'bg-off');
                document.getElementById('led_tcp').className = 'led ' + (data.hardware_tcp ? 'bg-on' : 'bg-off');

                let esScada = (data.modo === "SCADA");
                document.getElementById('btn_start').disabled = esScada;
                document.getElementById('btn_perfil').disabled = esScada;
                document.getElementById('btn_fijar').disabled = esScada;
                document.getElementById('input_frec').disabled = esScada;
                document.getElementById('btn_recuperar').style.display = esScada ? 'block' : 'none';

                // Lógica de Graficación Dinámica
                if (data.modo === "PERFIL") {
                    if (data.tiempo_perfil === 0 && ultimoTiempo !== 0) {
                        // Limpiar gráfica si el perfil acaba de iniciar
                        chart.data.labels = [];
                        chart.data.datasets[0].data = [];
                    }
                    if (data.tiempo_perfil > ultimoTiempo) {
                        chart.data.labels.push(data.tiempo_perfil);
                        chart.data.datasets[0].data.push(data.viento_ms);
                        chart.update();
                        ultimoTiempo = data.tiempo_perfil;
                    }
                } else if (ultimoTiempo > 0) {
                    // Si se detiene manualmente, guardamos estado para no graficar basura
                    ultimoTiempo = -1; 
                }
            });
        }, 1000); // 1 segundo para sincronizar con el perfil
    </script>
</body>
</html>
"""

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/api/status')
def get_status(): return jsonify(estado)

@app.route('/api/control/<accion>', methods=['POST'])
def control(accion):
    if accion == 'start': 
        estado["modo"], estado["comando"] = "MANUAL", 18
    elif accion == 'stop': 
        estado["modo"], estado["comando"] = "DETENIDO", 1
    elif accion == 'perfil':
        estado["modo"] = "PERFIL"
        estado["comando"] = 18
        threading.Thread(target=ejecutar_perfil).start()
    elif accion == 'recuperar':
        estado["modo"], estado["comando"] = "DETENIDO", 1
        try: _write_register_universal(cliente_scada, 2, 0, 1)
        except: pass
    return "OK"

@app.route('/api/set_frec', methods=['POST'])
def set_frec():
    datos = request.get_json()
    if datos and 'frecuencia' in datos and estado["modo"] != "SCADA":
        estado["frecuencia"] = float(datos['frecuencia'])
        estado["modo"] = "MANUAL"
    return "OK"

if __name__ == '__main__':
    threading.Thread(target=hilo_powerflex, daemon=True).start()
    threading.Thread(target=hilo_scada, daemon=True).start()
    # Ejecutar siempre con 'sudo python3 servidor_web.py' para acceso al puerto 80 y USB
    app.run(host='0.0.0.0', port=80, debug=False)