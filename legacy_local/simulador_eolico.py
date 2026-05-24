import os
import csv
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pymodbus.client import ModbusSerialClient, ModbusTcpClient

# --- CONFIGURACIÓN DE RED SERIAL (RTU) ---
PUERTO_COM = '/dev/ttyUSB0'
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

        self.cliente_modbus = None
        self.cliente_scada = ModbusTcpClient(IP_SCADA, port=PUERTO_SCADA)
        
        self.app_corriendo = True
        self.modo_actual = "DETENIDO" 
        self.frecuencia_objetivo = 0.0  
        self.comando_objetivo = 1
        
        self.modbus_lock = threading.Lock()
        
        self.construir_interfaz()
        self.conectar_modbus()
        self.iniciar_hilos_maestros()

    # =========================================================================
    # ADAPTADORES UNIVERSALES MODBUS (Evasión de errores de versión de librería)
    # =========================================================================
    def _write_register_universal(self, cliente, direccion, valor, id_nodo):
        try: cliente.write_register(direccion, valor, slave=id_nodo)
        except TypeError:
            try: cliente.write_register(direccion, valor, unit=id_nodo)
            except TypeError:
                try: cliente.write_register(direccion, valor, id_nodo) # Posicional puro
                except TypeError: cliente.write_register(direccion, valor) # Broadcast/Default

    def _write_registers_universal(self, cliente, direccion, valores, id_nodo):
        try: cliente.write_registers(direccion, values=valores, slave=id_nodo)
        except TypeError:
            try: cliente.write_registers(direccion, values=valores, unit=id_nodo)
            except TypeError:
                try: cliente.write_registers(direccion, valores, id_nodo)
                except TypeError: cliente.write_registers(direccion, values=valores)

    def _read_holding_universal(self, cliente, direccion, cantidad, id_nodo):
        try: return cliente.read_holding_registers(direccion, count=cantidad, slave=id_nodo)
        except TypeError:
            try: return cliente.read_holding_registers(direccion, count=cantidad, unit=id_nodo)
            except TypeError:
                try: return cliente.read_holding_registers(direccion, cantidad, id_nodo)
                except TypeError: return cliente.read_holding_registers(direccion, count=cantidad)
    # =========================================================================

    def construir_interfaz(self):
        style = ttk.Style()
        style.configure("TButton", font=("Arial", 10))

        frame_scada = ttk.LabelFrame(self.root, text=" Telemetría SCADA (TCP/IP) ", padding=10)
        frame_scada.pack(fill="x", padx=10, pady=5)
        self.lbl_estado_scada = ttk.Label(frame_scada, text="Buscando SCADA...", foreground="orange", font=("Arial", 9, "bold"))
        self.lbl_estado_scada.pack()
        self.btn_recuperar = ttk.Button(frame_scada, text="RECUPERAR CONTROL LOCAL", command=self.recuperar_control_local, state="disabled")
        self.btn_recuperar.pack(pady=5)

        frame_estado = ttk.LabelFrame(self.root, text=" Estado del Generador ", padding=10)
        frame_estado.pack(fill="x", padx=10, pady=5)
        self.lbl_estado = ttk.Label(frame_estado, text="Desconectado", foreground="red", font=("Arial", 10, "bold"))
        self.lbl_estado.pack()

        self.frame_manual = ttk.LabelFrame(self.root, text=" Control Manual ", padding=10)
        self.frame_manual.pack(fill="x", padx=10, pady=5)
        ttk.Label(self.frame_manual, text="Frecuencia (Hz):").grid(row=0, column=0, padx=5, pady=5)
        self.entry_hz = ttk.Entry(self.frame_manual, width=10)
        self.entry_hz.insert(0, "60.0")
        self.entry_hz.grid(row=0, column=1, padx=5, pady=5)
        self.btn_arranque_manual = ttk.Button(self.frame_manual, text="Arrancar Manual", command=self.arranque_manual)
        self.btn_arranque_manual.grid(row=0, column=2, padx=10, pady=5)

        self.frame_auto = ttk.LabelFrame(self.root, text=" Emulación por Perfil (CSV) ", padding=10)
        self.frame_auto.pack(fill="x", padx=10, pady=5)
        self.lbl_csv = ttk.Label(self.frame_auto, text=f"Archivo: {NOMBRE_ARCHIVO}")
        self.lbl_csv.pack(pady=5)
        self.btn_perfil = ttk.Button(self.frame_auto, text="Iniciar Perfil de Viento", command=self.iniciar_perfil)
        self.btn_perfil.pack(pady=5)

        frame_stop = ttk.Frame(self.root, padding=10)
        frame_stop.pack(fill="x", padx=10, pady=5)
        btn_stop = tk.Button(frame_stop, text="PARADA DE EMERGENCIA / STOP", font=("Arial", 14, "bold"), bg="#ff4c4c", fg="white", height=2, command=self.parada_segura)
        btn_stop.pack(fill="x")

    def conectar_modbus(self):
        self.cliente_modbus = ModbusSerialClient(
            port=PUERTO_COM, 
            baudrate=BAUDRATE, 
            bytesize=8, 
            parity='N', 
            stopbits=1, 
            timeout=1.5
        )
        if self.cliente_modbus.connect():
            # --- HACK LINUX ---
            # Forzamos la caída de los pines RTS y DTR a nivel del socket (PySerial)
            # Esto obliga al chip del USB-RS485 a apagar el transmisor y entrar en modo "Escucha"
            try:
                if hasattr(self.cliente_modbus, 'socket') and self.cliente_modbus.socket is not None:
                    self.cliente_modbus.socket.setRTS(False)
                    self.cliente_modbus.socket.setDTR(False)
            except Exception:
                pass
            # ------------------
                
            self.lbl_estado.config(text=f"Conectado a {PUERTO_COM} (RTU)", foreground="green")
        else:
            self.lbl_estado.config(text=f"Fallo de conexión en {PUERTO_COM}", foreground="red")

    def iniciar_hilos_maestros(self):
        threading.Thread(target=self._tarea_heartbeat, daemon=True).start()
        threading.Thread(target=self._tarea_comunicacion_scada, daemon=True).start()

    def _tarea_heartbeat(self):
        while self.app_corriendo:
            try:
                ref_velocidad = int(self.frecuencia_objetivo * 100)
                with self.modbus_lock:
                    self._write_register_universal(self.cliente_modbus, 8192, self.comando_objetivo, ID_VARIADOR)
                    self._write_register_universal(self.cliente_modbus, 8193, ref_velocidad, ID_VARIADOR)
            except Exception as e:
                print(f"[RTU Error] Fallo a nivel físico: {e}") 
            time.sleep(1)

    def _tarea_comunicacion_scada(self):
        while self.app_corriendo:
            try:
                if not self.cliente_scada.connect():
                    self.root.after(0, self.lbl_estado_scada.config, {"text": "SCADA Desconectado", "foreground": "red"})
                    time.sleep(1)
                    continue

                self.root.after(0, self.lbl_estado_scada.config, {"text": f"SCADA Conectado ({IP_SCADA}) - Activo", "foreground": "green"})

                estado_motor = 1 if self.comando_objetivo == 18 else 0
                frec_actual_escala = int(self.frecuencia_objetivo * 100)
                
                self._write_registers_universal(self.cliente_scada, 0, [estado_motor, frec_actual_escala], 1)
                respuesta = self._read_holding_universal(self.cliente_scada, 2, 3, 1)
                
                if hasattr(respuesta, 'isError') and not respuesta.isError():
                    peticion_scada = respuesta.registers[0]
                    boton_arranque_scada = respuesta.registers[1]
                    frec_scada = respuesta.registers[2]

                    if peticion_scada == 1 and self.modo_actual != "SCADA":
                        self.modo_actual = "SCADA"
                        self.root.after(0, self.activar_interfaz_scada) 

                    if self.modo_actual == "SCADA":
                        self.comando_objetivo = 18 if boton_arranque_scada == 1 else 1  
                        nueva_frec = min(130.0, max(0.0, frec_scada / 100.0))
                        self.frecuencia_objetivo = nueva_frec
                        
                        estado_texto = 'Run' if self.comando_objetivo == 18 else 'Stop'
                        self.root.after(0, self.lbl_estado.config, {"text": f"CONTROL SCADA | Estado: {estado_texto} | {nueva_frec} Hz", "foreground": "purple"})

            except Exception as e:
                print(f"[TCP Error] Problema de red: {e}")
            time.sleep(INTERVALO_SCADA_MS / 1000.0)

    def activar_interfaz_scada(self):
        self.btn_arranque_manual.config(state="disabled")
        self.btn_perfil.config(state="disabled")
        self.entry_hz.config(state="disabled")
        self.btn_recuperar.config(state="normal") 

    def recuperar_control_local(self):
        self.modo_actual = "DETENIDO"
        self.comando_objetivo = 1
        
        try:
            self._write_register_universal(self.cliente_scada, 2, 0, 1)
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
            if nueva_frecuencia < 0 or nueva_frecuencia > 130: raise ValueError("Frecuencia fuera de límites.")

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
        """Lee el perfil CSV con viento y frecuencia, iterando cada segundo."""
        try:
            perfil = []
            with open(ruta_csv, mode='r', encoding='utf-8') as archivo:
                lector = csv.DictReader(archivo)
                for fila in lector:
                    try:
                        v = float(fila['viento'])
                        f = float(fila['frecuencia'])
                        perfil.append({'viento': v, 'frecuencia': f})
                    except (ValueError, KeyError):
                        pass # Ignora líneas mal formadas o vacías

            for i, dato in enumerate(perfil):
                if self.modo_actual != "PERFIL": break
                
                self.frecuencia_objetivo = dato['frecuencia'] 
                
                # Mostramos en la interfaz ambas variables en tiempo real
                self.root.after(0, self.lbl_estado.config, {
                    "text": f"Perfil Auto: {dato['viento']:.2f} m/s -> {dato['frecuencia']:.2f} Hz (Punto {i+1}/{len(perfil)})", 
                    "foreground": "blue"
                })
                time.sleep(1) 

            if self.modo_actual == "PERFIL":
                self.comando_objetivo = 1
                self.modo_actual = "DETENIDO"
                self.root.after(0, self.lbl_estado.config, {"text": "Perfil Finalizado", "foreground": "green"})

        except Exception as e:
            self.root.after(0, self.lbl_estado.config, {"text": f"Error parseando CSV: {e}", "foreground": "red"})
            
    def parada_segura(self):
        self.comando_objetivo = 1
        if self.modo_actual != "SCADA":
            self.modo_actual = "DETENIDO"
            self.lbl_estado.config(text="Motor Detenido (Parada Segura)", foreground="red")
        else:
            self.lbl_estado.config(text="Emergencia - SCADA Mantiene Jerarquía pero Motor Frenado", foreground="red")

    def on_closing(self):
        self.app_corriendo = False 
        self.comando_objetivo = 1
        
        try:
            with self.modbus_lock:
                self._write_register_universal(self.cliente_modbus, 8192, 1, ID_VARIADOR)
        except Exception:
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