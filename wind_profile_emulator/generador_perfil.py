import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ========== CONFIGURACIÓN ==========
DURACION_SEGUNDOS = 3600 * 24 * 3   # 3 días
PASO_SEG = 1.0
VEL_MEDIA_ANUAL = 10.0             # m/s (La Guajira)

# Parámetros de conversión viento → frecuencia (lineal)
CUT_IN = 3.0       
NOMINAL = 11.0      
F_MAX = 25.5        
CUT_OUT = 25.0    

# ========== CARGAR DATOS DE GLOBAL WIND ATLAS ==========
heatmap = pd.read_csv('heatmapData.csv', index_col=0)
wind_speed_perc = pd.read_csv('windSpeed.csv')
vel_percentiles = wind_speed_perc['val'].values
factor_escala = VEL_MEDIA_ANUAL / np.mean(vel_percentiles[::2])
vel_percentiles = vel_percentiles * factor_escala

# ========== GENERAR PERFIL DE VIENTO ==========
t = np.arange(0, DURACION_SEGUNDOS, PASO_SEG)
horas = (t / 3600) % 24
meses = (t / (3600 * 24 * 30)) % 12

def get_base_factor(hora, mes):
    h = int(hora % 24)
    m = int(mes % 12) + 1
    if m < 1: m = 1
    if m > 12: m = 12
    return heatmap.iloc[h, m-1]

base_factor = np.array([get_base_factor(h, m) for h, m in zip(horas, meses)])
v_base = VEL_MEDIA_ANUAL * base_factor
vel_dist = np.random.choice(vel_percentiles, size=len(t), replace=True)
v_final = 0.7 * v_base + 0.3 * vel_dist
v_final = pd.Series(v_final).rolling(window=10, center=True).mean().fillna(method='bfill').fillna(method='ffill').values

# ========== CONVERSIÓN VIENTO → FRECUENCIA (lineal) ==========
def viento_a_frecuencia(v):
    if v < CUT_IN or v > CUT_OUT:
        return 0.0
    elif v >= NOMINAL:
        return F_MAX
    else:
        return F_MAX * (v - CUT_IN) / (NOMINAL - CUT_IN)

frecuencia = np.array([viento_a_frecuencia(v) for v in v_final])

# ========== GUARDAR CSV ==========
df = pd.DataFrame({
    'viento': v_final,       
    'frecuencia': frecuencia   
})
df.to_csv('perfil_viento.csv', index=False)

print(f"✅ Archivo perfil_viento.csv generado con {len(df)} puntos")
print("   Columnas: 'viento' (m/s) y 'frecuencia' (Hz)")

# ========== GRÁFICA ==========
plt.figure(figsize=(12,4))
plt.plot(t/3600, v_final, label='Velocidad viento (m/s)', alpha=0.7)
plt.plot(t/3600, frecuencia, label='Frecuencia de referencia (Hz)', alpha=0.7)
plt.xlabel('Tiempo (horas)')
plt.ylabel('Magnitud')
plt.legend()
plt.title('Perfil de viento y frecuencia de referencia asociada')
plt.grid(True)
plt.tight_layout()
plt.savefig('perfil_viento_grafico.png')
plt.show()