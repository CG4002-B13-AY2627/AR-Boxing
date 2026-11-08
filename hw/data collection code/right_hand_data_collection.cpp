#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>

// ============================================================
// RIGHT-HAND DATA-COLLECTION ESP32
//
// - Reads RIGHT MPU6050 raw registers at ~100 Hz.
// - Receives LEFT raw MPU6050 data over ESP-NOW.
// - Prints both hands as CSV over Serial for the Python collector.
// ============================================================

static const uint8_t MPU_ADDR = 0x68;

const int BUZZER_PIN = 25;
const int BUTTON_PIN = 26;

const unsigned long SAMPLE_INTERVAL = 10; // ~100 Hz
const unsigned long LEFT_DATA_TIMEOUT_MS = 100;

unsigned long lastSampleTime = 0;
uint32_t sampleIndex = 0;

// IMPORTANT:
// The LEFT-HAND transmitter must use this exact same packet layout/types.
// Raw MPU6050 readings are signed 16-bit values.
struct __attribute__((packed)) ImuPacket {
  uint32_t sampleIndex;
  uint32_t timestampMs;

  int16_t ax;
  int16_t ay;
  int16_t az;

  int16_t gx;
  int16_t gy;
  int16_t gz;

  uint8_t buttonPressed;
};

volatile bool leftPacketReceived = false;
volatile unsigned long lastLeftReceiveTime = 0;
ImuPacket latestLeft;

// ============================================================
// MPU6050 RAW REGISTER ACCESS
// ============================================================

bool mpuWrite(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool initMPU6050() {
  // Wake MPU6050.
  if (!mpuWrite(0x6B, 0x00)) return false;

  // Gyroscope full scale: +/-2000 deg/s (16.4 LSB per deg/s).
  if (!mpuWrite(0x1B, 0x18)) return false;

  // Accelerometer full scale: +/-16 g (2048 LSB per g).
  if (!mpuWrite(0x1C, 0x18)) return false;

  // Digital low-pass filter enabled.
  // DLPF_CFG = 3: ~44 Hz accel / ~42 Hz gyro bandwidth.
  if (!mpuWrite(0x1A, 0x03)) return false;

  // With DLPF enabled, internal gyro sample rate = 1 kHz.
  // 1 kHz / (1 + 9) = 100 Hz.
  if (!mpuWrite(0x19, 0x09)) return false;

  delay(100);
  return true;
}

bool readRawMPU6050(
  int16_t &ax,
  int16_t &ay,
  int16_t &az,
  int16_t &gx,
  int16_t &gy,
  int16_t &gz
) {
  // ACCEL_XOUT_H starts at register 0x3B.
  // Read 14 consecutive bytes:
  // AX, AY, AZ, TEMP, GX, GY, GZ.
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);

  if (Wire.endTransmission(false) != 0) {
    return false;
  }

  const uint8_t bytesWanted = 14;

  if (Wire.requestFrom(
        (uint8_t)MPU_ADDR,
        bytesWanted,
        (uint8_t)true
      ) != bytesWanted) {
    return false;
  }

  ax = (int16_t)((Wire.read() << 8) | Wire.read());
  ay = (int16_t)((Wire.read() << 8) | Wire.read());
  az = (int16_t)((Wire.read() << 8) | Wire.read());

  // Skip temperature.
  Wire.read();
  Wire.read();

  gx = (int16_t)((Wire.read() << 8) | Wire.read());
  gy = (int16_t)((Wire.read() << 8) | Wire.read());
  gz = (int16_t)((Wire.read() << 8) | Wire.read());

  return true;
}

// ============================================================
// ESP-NOW RECEIVE CALLBACK
// ============================================================

// Arduino-ESP32 2.x ESP-NOW receive callback.
void onDataRecv(
  const uint8_t *mac,
  const uint8_t *incomingData,
  int len
) {
  if (len == sizeof(ImuPacket)) {
    memcpy(&latestLeft, incomingData, sizeof(ImuPacket));

    lastLeftReceiveTime = millis();
    leftPacketReceived = true;
  }
}

// ============================================================
// SETUP
// ============================================================

void setup() {
  // Python collector must use the same baud rate.
  Serial.begin(115200);

  Wire.begin(); // Typical ESP32: SDA=21, SCL=22
  Wire.setClock(400000);

  pinMode(BUTTON_PIN, INPUT_PULLUP);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  Serial.println("Initializing RIGHT MPU6050 using raw registers...");

  if (!initMPU6050()) {
    Serial.println("ERROR: MPU6050 initialization failed.");

    while (true) {
      delay(1000);
    }
  }

  Serial.println("RIGHT MPU6050 ready.");
  Serial.println("Raw mode: accel=int16_t, gyro=int16_t");

  WiFi.mode(WIFI_STA);

  Serial.print("RIGHT ESP32 MAC: ");
  Serial.println(WiFi.macAddress());

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");

    while (true) {
      delay(1000);
    }
  }

  esp_now_register_recv_cb(onDataRecv);

  lastSampleTime = millis();

  // Output format remains compatible in shape with the existing collector:
  //
  // DATA,index,
  // right_ax,right_ay,right_az,right_gx,right_gy,right_gz,
  // left_ax,left_ay,left_az,left_gx,left_gy,left_gz,
  // right_button,left_button
  //
  // Difference: the 12 IMU values are now RAW SIGNED INTEGERS,
  // not MPU6050_light floating-point physical-unit values.
}

// ============================================================
// LOOP
// ============================================================

void loop() {
  if (millis() - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime += SAMPLE_INTERVAL;

    // Read RIGHT raw MPU6050 data into normal aligned variables.
    int16_t rightAx;
    int16_t rightAy;
    int16_t rightAz;

    int16_t rightGx;
    int16_t rightGy;
    int16_t rightGz;

    bool rightReadOK = readRawMPU6050(
      rightAx,
      rightAy,
      rightAz,
      rightGx,
      rightGy,
      rightGz
    );

    if (!rightReadOK) {
      // Skip this row if the right-hand I2C read failed.
      return;
    }

    // Right-hand button is local.
    // Left-hand button arrives through ESP-NOW.
    int rightButton =
      (digitalRead(BUTTON_PIN) == LOW) ? 1 : 0;

    // Only output a training row when recent LEFT-hand data is available.
    if (
      leftPacketReceived &&
      (millis() - lastLeftReceiveTime <= LEFT_DATA_TIMEOUT_MS)
    ) {

      // Copy the shared packet before printing.
      noInterrupts();

      ImuPacket left = latestLeft;

      interrupts();

      Serial.print("DATA,");
      Serial.print(sampleIndex++);
      Serial.print(",");

      // ------------------------------------------------------
      // RIGHT-HAND RAW MPU6050 VALUES
      // ------------------------------------------------------

      Serial.print(rightAx);
      Serial.print(",");

      Serial.print(rightAy);
      Serial.print(",");

      Serial.print(rightAz);
      Serial.print(",");

      Serial.print(rightGx);
      Serial.print(",");

      Serial.print(rightGy);
      Serial.print(",");

      Serial.print(rightGz);
      Serial.print(",");

      // ------------------------------------------------------
      // LEFT-HAND RAW MPU6050 VALUES RECEIVED VIA ESP-NOW
      // ------------------------------------------------------

      Serial.print(left.ax);
      Serial.print(",");

      Serial.print(left.ay);
      Serial.print(",");

      Serial.print(left.az);
      Serial.print(",");

      Serial.print(left.gx);
      Serial.print(",");

      Serial.print(left.gy);
      Serial.print(",");

      Serial.print(left.gz);
      Serial.print(",");

      // ------------------------------------------------------
      // BUTTONS
      // ------------------------------------------------------

      Serial.print(rightButton);
      Serial.print(",");

      Serial.println(left.buttonPressed);
    }
  }
}
