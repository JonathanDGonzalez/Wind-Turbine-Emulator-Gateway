# Wind Turbine Emulator Gateway

Source code, documentation, and deployment files for the 300W Wind Turbine Emulator developed for the course **Taller de Potencia (IELE3108)** at Universidad de los Andes. This repository implements an Industrial IoT Gateway on a Raspberry Pi 4 to bridge edge control, local web supervision, and external supervisory systems (SCADA).

The system handles real-time wind profile simulations using a Variable Frequency Drive (VFD), a three-phase motor, and a generator embedded into a DC Microgrid environment.

---

## Key Features

* **Dual Modbus Architecture:** Simultaneously acts as a Modbus RTU Master (controlling the VFD) and a Modbus TCP Server/Slave (reporting to and receiving commands from an external SCADA system).
* **Multi-threaded Edge Core:** Built with Python `threading` to manage hardware communication, SCADA data mapping, and user interfaces asynchronously.
* **Hybrid Interface:** Features a legacy local configuration tool (`tkinter`) and a modern web dashboard (`Flask` + `Bootstrap`) responsive for smartphones and remote monitoring.
* **Autonomous Profile Execution:** Executes precise wind speed profiles loaded from standard `.csv` datasets, translating them dynamically into mechanical frequency references.
* **Hardware Telemetry Integration:** Includes ESP32-based firmware for real-time monitoring of voltage, current, and temperature directly from a custom PCB sensor instrumentation layer.

---

## System Topology & Networks

The Raspberry Pi 4 manages three concurrent network/communication layers:
1. **Control Layer (Modbus RTU):** Physical connection via USB-to-RS485 converter to the PowerFlex 525 drive (`/dev/ttyUSB0` at 19200 bps).
2. **Supervision Layer (Modbus TCP Server):** Listening on Port `502` over the Ethernet interface (`eth0`, Static IP: `192.168.0.10`) for the SCADA Master Client (`192.168.0.50`).
3. **Management Layer (HTTP Web Server):** Serving a web-app on Port `80` over Wi-Fi (`wlan0`) for mobile/local browser interaction.

---

## Repository Structure

├── legacy_local/
│   └── emulador_local.py         # Original Tkinter interface for local testing
├── data/                         # Raw experimental datasets and cross-validation logs
│   └── caract_motor.xlsx         # Unified spreadsheet containing team characterization (Sin carga, Con carga) and Espitia's reference sheets (Mediciones, Compilado, EjemplosCapturaDatos)
├── sensors/
│   └── sensores.ino              # ESP32 firmware for PCB-mounted voltage, current, and temperature sensors
├── templates/
│   └── index.html                # Responsive web dashboard frontend (Bootstrap)
├── wind_profile_emulator/        # Elicit wind profile generation and synthesis environment
│   ├── generador_perfil.py       # Python script using Global Wind Atlas data to synthesize a 3-day profile
│   ├── heatmapData.csv           # Hourly/monthly wind distribution matrix from Global Wind Atlas (La Guajira)
│   ├── heatmapData.json          # JSON representation of the hourly/monthly wind speed matrix
│   ├── windSpeed.csv             # Wind speed percentile probability density data for turbulence modeling
│   ├── windSpeed.json            # JSON representation of the wind speed percentile dataset
│   ├── perfil_viento.csv         # Resulting time-series dataset (Wind speed vs. VFD Frequency) loaded by the gateway
│   └── perfil_viento_grafico.png # Visual plot of the synthesized wind profile time-series
├── servidor_web.py               # Main production script (Flask + Dual Modbus Server/Client)
├── docs/
│   ├── final_paper.pdf           # Final course research paper written by the team
│   ├── mathematical_model.pdf    # Theoretical physical equations and modeling (Savonius model - Reference for future real-blade execution)
│   └── schematic.pdf             # Electrical schematic diagram utilized for custom data acquisition and PCB instrumentation
└── README.md                     # Project documentation

---

## Hardware Parametrization (PowerFlex 525)

To replicate the project, the Allen-Bradley PowerFlex 525 VFD must be configured with the following parameters:

| Group | Parameter | Name | Value | Technical Purpose |
| :---: | :---: | :--- | :---: | :--- |
| **Control** | **P046** | Start Source 1 | **3** (Serial/DSI) | Grants start/stop control to Modbus RTU. |
| | **P047** | Speed Reference 1 | **3** (Serial/DSI) | Syncs target frequency to Modbus register `8193`. |
| **Dynamics** | **P040** | Autotune | **1** or **2** | Models internal motor variables to match exact RPMs. |
| | **P045** | Stop Mode 1 | **0** (Ramp, CF) | Controlled deceleration to avoid DC bus overvoltage. |
| **Serial RTU**| **C123** | RS485 Data Rate | **3** (19.2K) | Matches Python's `BAUDRATE` (19200 bps). |
| | **C124** | RS485 Node Addr | **1** | Target Slave ID for the Raspberry Pi script. |
| | **C125** | RS485 Format | **0** (8-N-1) | 8 data bits, No parity, 1 stop bit structure. |
| | **C127** | RS485 Protocol | **0** (Modbus RTU) | Enables standard Modbus RTU over control terminals. |
| **IP Network**| **C128** | Net Addr Sel | **1** (Static) | Enforces manual static IP mapping. |
| | **C129-C132**| IP Addr Cfg 1-4 | **192.168.0.50** | VFD static IP for network-wide visibility. |
| | **C133-C136**| Subnet Mask 1-4 | **255.255.255.0**| Standard Class C mask. |
| | **C137-C140**| Gateway Cfg 1-4 | **192.168.0.1** | Target router gateway configuration. |

---

## Getting Started & Deployment

### Prerequisites
Ensure your Raspberry Pi OS has the correct package dependencies installed. Due to recent updates in PyModbus API naming conventions, version `3.5.2` is strictly required to prevent runtime environment errors.

<pre>
# Install core dependencies globally (requires root privileges for port 80/502 allocation)
sudo pip install pymodbus==3.5.2 flask --break-system-packages
</pre>

### Running the Gateway
1. Connect the USB-to-RS485 converter and verify the port assignment (`ls /dev/ttyUSB*`).
2. Navigate to the project directory and execute the web server core:
<pre>
cd /home/pi/Documents/emulador_eolico
sudo python3 servidor_web.py
</pre>
3. Access the web dashboard by navigating to the Raspberry Pi's WLAN IP on any browser connected to the same local hotspot network.

---

## Deliverables & Media

* 📄 **Final Research Paper:** Available in the `/docs/final_paper.pdf` file, detailing the control loops, and experimental validation results within the DC Microgrid.
* 🧮 **Mathematical Modeling:** Found in `/docs/mathematical_model.pdf`, presenting the system's dynamic and aerodynamic equations.
* 🔌 **Hardware Design:** Found in `/docs/schematic.pdf`, detailing the signal conditioning and PCB connections for sensor telemetry.
* 🎥 **System Demonstration Video:** Watch the full system walkthrough, hardware commissioning, and real-time SCADA integration on YouTube: [Watch the Project Video Here](https://www.youtube.com/watch?v=j9mVfkG3Zqc).

---

## Authors & Credits

Project developed as part of the course **Taller de Potencia (IELE3108)**, Department of Electrical and Electronic Engineering, Universidad de los Andes, Bogotá, Colombia (2026).

* **Primary Author:** Jonathan David González Cubides
* **Secondary Author:** Juan David Roa Ballén
* **Additional Authors:** Cristian David González Mayorga
