import os
import csv
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pymodbus.client import ModbusSerialClient, ModbusTcpClient

# --- CONFIGURACIÓN DE RED SERIAL (RTU) ---
PUERTO_COM = 'COM6'
BAUDRATE = 19200
ID_VARIADOR = 1
NOMBRE_ARCHIVO = 'perfil_viento.csv'

# --- CONFIGURACIÓN DE RED SCADA (TCP/IP) ---
IP_SCADA = '192.168.0.50'
PUERTO_SCADA = 502
INTERVALO_SCADA_MS = 500

class EmuladorEolicoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Panel de Control y Gateway - Emulador Eólico")
        self.root.geometry("500x550")
        self.root.resizable(False, False)

        # Variables Globales (El mapa de memoria del "PLC")
        self.cliente_modbus = None
        self.cliente_scada = ModbusTcpClient(IP_SCADA, port=PUERTO_SCADA)
        
        self.app_corriendo = True       # Mantiene vivos los hilos maestros
        self.modo_actual = "DETENIDO" 
        self.frecuencia_objetivo = 0.0  
        self.comando_objetivo = 1       # Inicia siempre en 1 (Stop de seguridad)
        
        # MUTEX: Candado para proteger el bus RS-485 físico
        self.modbus_lock = threading.Lock()
        
        self.construir_interfaz()
        self.conectar_modbus()
        
        # Iniciar los dos "Scan Cycles" infinitos
        self.iniciar_hilos_maestros()

    def construir_interfaz(self):
        style = ttk.Style()
        style.configure("TButton", font=("Arial", 10))

        # --- SECCIÓN: COMUNICACIÓN SCADA ---
        frame_scada = ttk.LabelFrame(self.root, text=" Telemetría SCADA (TCP/IP) ", padding=10)
        frame_scada.pack(fill="x", padx=10, pady=5)
        
        self.lbl_estado_scada = ttk.Label(frame_scada, text="Buscando SCADA...", foreground="orange", font=("Arial", 9, "bold"))
        self.lbl_estado_scada.pack()

        self.btn_recuperar = ttk.Button(frame_scada, text="RECUPERAR CONTROL LOCAL", command=self.recuperar_control_local, state="disabled")
        self.btn_recuperar.pack(pady=5)

        # --- SECCIÓN: ESTADO DEL VARIADOR ---
        frame_estado = ttk.LabelFrame(self.root, text=" Estado del Generador ", padding=10)
        frame_estado.pack(fill="x", padx=10, pady=5)
        
        self.lbl_estado = ttk.Label(frame_estado, text="Desconectado", foreground="red", font=("Arial", 10, "bold"))
        self.lbl_estado.pack()

        # --- SECCIÓN: CONTROL MANUAL ---
        self.frame_manual = ttk.LabelFrame(self.root, text=" Control Manual ", padding=10)
        self.frame_manual.pack(fill="x", padx=10, pady=5)

        ttk.Label(self.frame_manual, text="Frecuencia (Hz):").grid(row=0, column=0, padx=5, pady=5)
        self.entry_hz = ttk.Entry(self.frame_manual, width=10)
        self.entry_hz.insert(0, "60.0")
        self.entry_hz.grid(row=0, column=1, padx=5, pady=5)

        self.btn_arranque_manual = ttk.Button(self.frame_manual, text="Arrancar Manual", command=self.arranque_manual)
        self.btn_arranque_manual.grid(row=0, column=2, padx=10, pady=5)

        # --- SECCIÓN: PERFIL DE VIENTO ---
        self.frame_auto = ttk.LabelFrame(self.root, text=" Emulación por Perfil (CSV) ", padding=10)
        self.frame_auto.pack(fill="x", padx=10, pady=5)

        self.lbl_csv = ttk.Label(self.frame_auto, text=f"Archivo: {NOMBRE_ARCHIVO}")
        self.lbl_csv.pack(pady=5)

        self.btn_perfil = ttk.Button(self.frame_auto, text="Iniciar Perfil de Viento", command=self.iniciar_perfil)
        self.btn_perfil.pack(pady=5)

        # --- SECCIÓN: PARADA DE EMERGENCIA ---
        frame_stop = ttk.Frame(self.root, padding=10)
        frame_stop.pack(fill="x", padx=10, pady=5)

        btn_stop = tk.Button(frame_stop, text="PARADA DE EMERGENCIA / STOP", 
                             font=("Arial", 14, "bold"), bg="#ff4c4c", fg="white", 
                             height=2, command=self.parada_segura)
        btn_stop.pack(fill="x")

    def conectar_modbus(self):
        self.cliente_modbus = ModbusSerialClient(
            port=PUERTO_COM, baudrate=BAUDRATE, bytesize=8, 
            parity='N', stopbits=1, timeout=0.5
        )
        if self.cliente_modbus.connect():
            self.lbl_estado.config(text=f"Conectado a {PUERTO_COM} (RTU)", foreground="green")
        else:
            self.lbl_estado.config(text=f"Fallo de conexión en {PUERTO_COM}", foreground="red")

    def iniciar_hilos_maestros(self):
        """Lanza los procesos de fondo indestructibles (Heartbeat y SCADA)"""
        threading.Thread(target=self._tarea_heartbeat, daemon=True).start()
        threading.Thread(target=self._tarea_comunicacion_scada, daemon=True).start()

    def _tarea_heartbeat(self):
        """ESTE ES EL NÚCLEO: Jamás muere. Lee las variables y las inyecta al bus físico constantemente."""
        while self.app_corriendo:
            try:
                ref_velocidad = int(self.frecuencia_objetivo * 100)
                with self.modbus_lock:
                    # Siempre manda el comando actual (sea 1 para Stop, o 18 para Start)
                    self.cliente_modbus.write_register(8192, self.comando_objetivo, device_id=ID_VARIADOR)
                    self.cliente_modbus.write_register(8193, ref_velocidad, device_id=ID_VARIADOR)
            except Exception as e:
                pass # Ignora ruido electromagnético
            time.sleep(1) # El latido acaricia el Watchdog Timer cada segundo de forma infinita

    def _tarea_comunicacion_scada(self):
        """Actualiza y lee variables del SCADA constantemente"""
        while self.app_corriendo:
            try:
                if not self.cliente_scada.connect():
                    self.root.after(0, self.lbl_estado_scada.config, {"text": "SCADA Desconectado", "foreground": "red"})
                    time.sleep(1)
                    continue

                self.root.after(0, self.lbl_estado_scada.config, {"text": f"SCADA Conectado ({IP_SCADA}) - Activo", "foreground": "green"})

                # 1. REPORTAR ESTADO LOCAL AL SCADA 
                estado_motor = 1 if self.comando_objetivo == 18 else 0
                frec_actual_escala = int(self.frecuencia_objetivo * 100)
                self.cliente_scada.write_registers(address=0, values=[estado_motor, frec_actual_escala], device_id=1)

                # 2. LEER COMANDOS DEL SCADA 
                respuesta = self.cliente_scada.read_holding_registers(address=2, count=3, device_id=1)
                
                if not respuesta.isError():
                    peticion_scada = respuesta.registers[0]       # Celda +2
                    boton_arranque_scada = respuesta.registers[1] # Celda +3 (0 = Stop, 1 = Start)
                    frec_scada = respuesta.registers[2]           # Celda +4

                    # Transición a SCADA
                    if peticion_scada == 1 and self.modo_actual != "SCADA":
                        self.modo_actual = "SCADA"
                        self.root.after(0, self.activar_interfaz_scada) 

                    # Mantenimiento de valores SCADA
                    if self.modo_actual == "SCADA":
                        
                        # --- EL TRADUCTOR DEL GATEWAY ---
                        # Si el SCADA envía un 1 (Botón ON), Python inyecta el 18 físico al variador
                        # Si el SCADA envía un 0 o cualquier otra cosa (Botón OFF), Python inyecta el 1 físico
                        if boton_arranque_scada == 1:
                            self.comando_objetivo = 18 
                        else:
                            self.comando_objetivo = 1  
                            
                        nueva_frec = min(130.0, max(0.0, frec_scada / 100.0))
                        self.frecuencia_objetivo = nueva_frec
                        
                        estado_texto = 'Run' if self.comando_objetivo == 18 else 'Stop'
                        self.root.after(0, self.lbl_estado.config, {"text": f"CONTROL SCADA | Estado: {estado_texto} | {nueva_frec} Hz", "foreground": "purple"})

            except Exception:
                pass 
            time.sleep(INTERVALO_SCADA_MS / 1000.0)

    def activar_interfaz_scada(self):
        self.btn_arranque_manual.config(state="disabled")
        self.btn_perfil.config(state="disabled")
        self.entry_hz.config(state="disabled")
        self.btn_recuperar.config(state="normal") 

    def recuperar_control_local(self):
        """Devuelve el control sin matar los hilos"""
        self.modo_actual = "DETENIDO"
        self.comando_objetivo = 1 # Frena el motor por seguridad, pero el heartbeat sigue inyectando este "1"
        
        try:
            self.cliente_scada.write_register(address=2, value=0, device_id=1)
        except Exception:
            pass
        
        self.btn_arranque_manual.config(state="normal")
        self.btn_perfil.config(state="normal")
        self.entry_hz.config(state="normal")
        self.btn_recuperar.config(state="disabled")
        
        self.lbl_estado.config(text="Control Recuperado (Motor Detenido)", foreground="blue")

    def arranque_manual(self):
        try:
            hz_str = self.entry_hz.get().replace(',', '.')
            nueva_frecuencia = float(hz_str)
            if nueva_frecuencia < 0 or nueva_frecuencia > 130:
                raise ValueError("Frecuencia fuera de límites.")

            # Simplemente actualizamos las variables globales. El heartbeat las tomará en su próximo ciclo.
            self.frecuencia_objetivo = nueva_frecuencia
            self.comando_objetivo = 18
            self.modo_actual = "MANUAL"
            
            self.lbl_estado.config(text=f"Modo Manual: Operando a {nueva_frecuencia} Hz", foreground="blue")
            
        except ValueError:
            messagebox.showwarning("Dato Inválido", "Ingresa un número válido.")

    def iniciar_perfil(self):
        ruta_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), NOMBRE_ARCHIVO)
        if not os.path.exists(ruta_csv):
            messagebox.showerror("Error", f"No se encontró {NOMBRE_ARCHIVO}")
            return

        self.modo_actual = "PERFIL"
        self.comando_objetivo = 18
        
        threading.Thread(target=self._tarea_perfil_viento, args=(ruta_csv,), daemon=True).start()

    def _tarea_perfil_viento(self, ruta_csv):
        """Ya no inyecta Modbus directo. Solo actualiza variables."""
        try:
            perfil = []
            with open(ruta_csv, mode='r', encoding='utf-8') as archivo:
                lector = csv.DictReader(archivo)
                for fila in lector:
                    perfil.append(float(fila.get('frecuencia', 0)))

            for i, frec_hz in enumerate(perfil):
                # Si se oprimió Stop o SCADA tomó control, rompemos el perfil
                if self.modo_actual != "PERFIL":
                    break
                
                # Actualizamos la variable global, el heartbeat la inyecta por nosotros
                self.frecuencia_objetivo = frec_hz 
                
                self.root.after(0, self.lbl_estado.config, {"text": f"Perfil Auto: Punto {i+1}/{len(perfil)} -> {frec_hz} Hz", "foreground": "blue"})
                time.sleep(1) 

            if self.modo_actual == "PERFIL":
                self.comando_objetivo = 1
                self.modo_actual = "DETENIDO"
                self.root.after(0, self.lbl_estado.config, {"text": "Perfil Finalizado", "foreground": "green"})

        except Exception as e:
            self.root.after(0, self.lbl_estado.config, {"text": f"Error en perfil: {e}", "foreground": "red"})

    def parada_segura(self):
        """Parada por software limpia"""
        self.comando_objetivo = 1
        if self.modo_actual != "SCADA":
            self.modo_actual = "DETENIDO"
            self.lbl_estado.config(text="Motor Detenido (Parada Segura)", foreground="red")
        else:
            self.lbl_estado.config(text="Emergencia - SCADA Mantiene Jerarquía pero Motor Frenado", foreground="red")

    def on_closing(self):
        self.app_corriendo = False # Esto sí mata todos los hilos limpiamente
        self.comando_objetivo = 1
        
        # Último aliento para detener el motor
        try:
            with self.modbus_lock:
                self.cliente_modbus.write_register(8192, 1, device_id=ID_VARIADOR)
        except:
            pass
            
        time.sleep(0.5)
        if self.cliente_modbus: self.cliente_modbus.close()
        if self.cliente_scada: self.cliente_scada.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = EmuladorEolicoApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()