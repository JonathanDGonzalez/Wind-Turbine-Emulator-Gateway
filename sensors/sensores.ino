/*
  Medición de Voltaje, Corriente (ACS712) y Temperatura (MAX6675) con ESP32
*/

#include <Arduino.h>
#include "max6675.h"

// ========== TERMOCUPLA ==========
int thermoDO = 19;
int thermoCS = 5;
int thermoCLK = 18;

MAX6675 thermocouple(thermoCLK, thermoCS, thermoDO);

// ========== CONFIGURACIÓN ADC ==========
const int ADC_RES = 4095;
const float VREF = 3.3;
const float mV_PER_ADC = (VREF / ADC_RES) * 1000;

// ========== VOLTAJE ==========
const int PIN_VOLTAJE = 34;
const float VOLT_A = 0.04527;
const float VOLT_B = -0.1685;

// ========== CORRIENTE ==========
const int PIN_CORRIENTE = 35;
const float SENSITIVITY_MV_PER_A = 66.0;

const float ADC_OFFSET = 1898;
const float ZERO_CURRENT_MV = ADC_OFFSET * mV_PER_ADC;

const float SIGN_CORRECTION = 1.0;
const int NUM_MUESTRAS = 50;

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  Serial.println("=== SISTEMA DE MEDICIÓN INTEGRADO ===");
  Serial.println("Voltaje | Corriente | Potencia | Temperatura");
  delay(1000);
}

void loop() {

  // ===== VOLTAJE =====
  int adcVolt = analogRead(PIN_VOLTAJE);
  float voltaje = adcVolt * VOLT_A + VOLT_B + 5;
  if (voltaje < 5) voltaje = 0;

  // ===== CORRIENTE =====
  float sumaADC = 0;
  for (int i = 0; i < NUM_MUESTRAS; i++) {
    sumaADC += analogRead(PIN_CORRIENTE);
    delay(2);
  }
  float adcCorr = sumaADC / NUM_MUESTRAS;
  float voltajeSensor_mV = adcCorr * mV_PER_ADC;
  float corriente = (voltajeSensor_mV - ZERO_CURRENT_MV) / SENSITIVITY_MV_PER_A;
  corriente *= SIGN_CORRECTION;

  // ===== POTENCIA =====
  float potencia = voltaje * corriente;

  // ===== TEMPERATURA =====
  float temperatura = thermocouple.readCelsius();

  // ===== SERIAL OUTPUT =====
  Serial.println("------ MEDICIONES ------");

  Serial.print("Voltaje: ");
  Serial.print(voltaje, 2);
  Serial.println(" V");

  Serial.print("Corriente: ");
  Serial.print(corriente, 3);
  Serial.println(" A");

  Serial.print("Potencia: ");
  Serial.print(potencia, 3);
  Serial.println(" W");

  Serial.print("Temperatura: ");
  Serial.print(temperatura);
  Serial.println(" °C");

  Serial.println();

  delay(1000);
}