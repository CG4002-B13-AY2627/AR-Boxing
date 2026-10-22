#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>

// ============================================================
// LEFT-HAND DATA-COLLECTION ESP32
//
// - Reads LEFT MPU6050 raw registers at ~100 Hz.
// - Sends raw MPU6050 data + button state to RIGHT ESP32 via ESP-NOW.
// - Packet layout matches the raw-data RIGHT-hand collector.
// ============================================================

static const uint8_t MPU_ADDR = 0x68;

const int BUTTON_PIN = 26;
const int BUZZER_PIN = 25;

// RIGHT-HAND ESP32 Wi-Fi STA MAC address.
uint8_t RIGHT_HAND_MAC[] = {0x6C, 0xC8, 0x40, 0x7C, 0xB3, 0x4C};

const unsigned long SAMPLE_INTERVAL = 10; // ~100 Hz
unsigned long lastSampleTime = 0;
uint32_t sampleIndex = 0;

// IMPORTANT:
// This packet layout must exactly match ImuPacket on the RIGHT receiver.
// Raw MPU6050 accel/gyro values are signed 16-bit integers.
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

  // Gyroscope full scale: +/-250 deg/s.
  if (!mpuWrite(0x1B, 0x00)) return false;

  // Accelerometer full scale: +/-2 g.
  if (!mpuWrite(0x1C, 0x00)) return false;

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
  // Read 14 consecutive bytes beginning at ACCEL_XOUT_H (0x3B):
  // AX, AY, AZ, temperature, GX, GY, GZ.
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

  // Skip temperature registers.
  Wire.read();
  Wire.read();

  gx = (int16_t)((Wire.read() << 8) | Wire.read());
  gy = (int16_t)((Wire.read() << 8) | Wire.read());
  gz = (int16_t)((Wire.read() << 8) | Wire.read());

  return true;
}

// ============================================================
// SETUP
// ============================================================

void setup() {
  Serial.begin(115200);

  Wire.begin(); // Typical ESP32: SDA=21, SCL=22
  Wire.setClock(400000);

  pinMode(BUTTON_PIN, INPUT_PULLUP);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  Serial.println("Initializing LEFT MPU6050 using raw registers...");

  if (!initMPU6050()) {
    Serial.println("ERROR: MPU6050 initialization failed.");

    while (true) {
      delay(1000);
    }
  }

  Serial.println("LEFT MPU6050 ready.");
  Serial.println("Raw mode: accel=int16_t, gyro=int16_t");

  WiFi.mode(WIFI_STA);

  Serial.print("LEFT ESP32 MAC: ");
  Serial.println(WiFi.macAddress());

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");

    while (true) {
      delay(1000);
    }
  }

  esp_now_peer_info_t peerInfo = {};

  memcpy(
    peerInfo.peer_addr,
    RIGHT_HAND_MAC,
    6
  );

  peerInfo.channel = 0;
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Failed to add RIGHT-HAND peer");

    while (true) {
      delay(1000);
    }
  }

  lastSampleTime = millis();
}

// ============================================================
// LOOP
// ============================================================

void loop() {
  if (millis() - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime += SAMPLE_INTERVAL;

    // Read raw values into normal aligned variables first.
    // This avoids binding references directly to fields of a packed struct.
    int16_t ax;
    int16_t ay;
    int16_t az;

    int16_t gx;
    int16_t gy;
    int16_t gz;

    if (!readRawMPU6050(
          ax,
          ay,
          az,
          gx,
          gy,
          gz
        )) {
      Serial.println("MPU6050 read error");
      return;
    }

    ImuPacket packet{};

    packet.sampleIndex = sampleIndex++;
    packet.timestampMs = millis();

    packet.ax = ax;
    packet.ay = ay;
    packet.az = az;

    packet.gx = gx;
    packet.gy = gy;
    packet.gz = gz;

    packet.buttonPressed =
      (digitalRead(BUTTON_PIN) == LOW) ? 1 : 0;

    esp_err_t result = esp_now_send(
      RIGHT_HAND_MAC,
      reinterpret_cast<const uint8_t *>(&packet),
      sizeof(packet)
    );

    if (result != ESP_OK) {
      Serial.println("ESP-NOW send error");
    }
  }
}
