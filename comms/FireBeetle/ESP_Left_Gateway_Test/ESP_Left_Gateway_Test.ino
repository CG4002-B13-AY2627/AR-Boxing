// Left board: simulated or MPU samples -> right ESP-NOW gateway.
// Both boards join the SAME hotspot to follow its Wi-Fi channel automatically.
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_arduino_version.h>
#if __has_include(<esp_mac.h>)
#include <esp_mac.h>
#else
#include <esp_system.h>
#endif
#include "test_config.h"

struct __attribute__((packed)) SensorMsg {
  uint8_t type, nodeID; uint32_t timestamp;
  int16_t ax, ay, az, gx, gy, gz;
};
struct __attribute__((packed)) ActuateMsg { uint8_t type, nodeID, command, duration; };
static_assert(sizeof(SensorMsg) == 18, "ESP-NOW layout changed");
portMUX_TYPE commandMux = portMUX_INITIALIZER_UNLOCKED;
ActuateMsg pending{}; bool commandReady = false;
uint32_t submitted = 0, submitErrors = 0, nextSampleUs = 0;
bool motorActive = false; uint32_t motorAt = 0; uint8_t motorDuration = 0;

bool mpuWrite(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(0x68); Wire.write(reg); Wire.write(value);
  return Wire.endTransmission() == 0;
}
bool initializeMPU() {
  if (SIMULATED_SENSORS) return true;
  Wire.begin(); Wire.setClock(400000);
  return mpuWrite(0x6B, 0) && mpuWrite(0x1B, 0) && mpuWrite(0x1C, 0) && mpuWrite(0x1A, 3) && mpuWrite(0x19, 9);
}
bool readSample(SensorMsg &s) {
  s.type = 1; s.nodeID = 1; s.timestamp = millis();
  if (SIMULATED_SENSORS) {
    s.ax = 100; s.ay = 0; s.az = 16384; s.gx = s.gy = s.gz = 0; return true;
  }
  Wire.beginTransmission(0x68); Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom((uint8_t)0x68, (uint8_t)14, (uint8_t)true) != 14) return false;
  uint8_t b[14]; for (int i = 0; i < 14; i++) b[i] = Wire.read();
  s.ax = (int16_t)((b[0] << 8) | b[1]); s.ay = (int16_t)((b[2] << 8) | b[3]);
  s.az = (int16_t)((b[4] << 8) | b[5]); s.gx = (int16_t)((b[8] << 8) | b[9]);
  s.gy = (int16_t)((b[10] << 8) | b[11]); s.gz = (int16_t)((b[12] << 8) | b[13]); return true;
}
void receiveCommand(const uint8_t *mac, const uint8_t *data, int length) {
  if (memcmp(mac, RIGHT_MAC, 6) != 0 || length != sizeof(ActuateMsg)) return;
  ActuateMsg msg; memcpy(&msg, data, sizeof(msg));
  if (msg.type != 0x10 || msg.nodeID != 1 || msg.command > 1) return;
  portENTER_CRITICAL(&commandMux); pending = msg; commandReady = true; portEXIT_CRITICAL(&commandMux);
}
#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int length) { receiveCommand(info->src_addr, data, length); }
#else
void onReceive(const uint8_t *mac, const uint8_t *data, int length) { receiveCommand(mac, data, length); }
#endif
void printBoardMac() {
  uint8_t mac[6] = {};
  esp_err_t result = esp_read_mac(mac, ESP_MAC_WIFI_STA);
  if (result != ESP_OK) {
    Serial.printf("[MAC] read failed, error=%d\n", (int)result);
    return;
  }
  Serial.printf("LEFT STA MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

void setup() {
  Serial.begin(115200); delay(1500);
  printBoardMac();
  if (!SIMULATED_SENSORS) { pinMode(25, OUTPUT); analogWrite(25, 0); }
  if (!initializeMPU()) { Serial.println("MPU initialization failed"); while (true) delay(1000); }
  WiFi.mode(WIFI_STA); WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  if (esp_now_init() != ESP_OK) { Serial.println("ESP-NOW init failed"); while (true) delay(1000); }
  esp_now_register_recv_cb(onReceive);
  esp_now_peer_info_t peer{}; memcpy(peer.peer_addr, RIGHT_MAC, 6);
  peer.channel = 0; peer.ifidx = WIFI_IF_STA; peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) Serial.println("[CONFIG] RIGHT peer not added; set RIGHT_MAC and upload again");
  nextSampleUs = micros();
}
void loop() {
  static uint32_t lastMacPrint = 0;
  if (millis() - lastMacPrint >= 10000) {
    lastMacPrint = millis(); printBoardMac();
  }
  static uint32_t wifiAttempt = 0;
  if (WiFi.status() != WL_CONNECTED && millis() - wifiAttempt >= 10000) {
    wifiAttempt = millis(); WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
  ActuateMsg cmd{}; bool got;
  portENTER_CRITICAL(&commandMux); got = commandReady;
  if (got) { cmd = pending; commandReady = false; } portEXIT_CRITICAL(&commandMux);
  if (got) {
    Serial.printf("[ACTUATE] LEFT received command=%u duration=%u ms%s\n", cmd.command, cmd.duration,
                  SIMULATED_SENSORS ? " (simulation: no motor driven)" : "");
    if (!SIMULATED_SENSORS) {
      analogWrite(25, cmd.command == 1 && cmd.duration ? 165 : 0);
      motorActive = cmd.command == 1 && cmd.duration; motorAt = millis(); motorDuration = cmd.duration;
    }
  }
  if (motorActive && millis() - motorAt >= motorDuration) { analogWrite(25, 0); motorActive = false; }
  uint32_t nowUs = micros();
  if ((int32_t)(nowUs - nextSampleUs) >= 0) {
    nextSampleUs += 10000;
    if ((int32_t)(nowUs - nextSampleUs) >= 10000) nextSampleUs = nowUs + 10000;
    if (WiFi.status() == WL_CONNECTED) {
      SensorMsg sample;
      if (readSample(sample)) {
        if (esp_now_send(RIGHT_MAC, (uint8_t *)&sample, sizeof(sample)) == ESP_OK) submitted++;
        else submitErrors++;
      }
    }
  }
  static uint32_t reportAt = 0;
  if (millis() - reportAt >= 1000) {
    reportAt = millis();
    Serial.printf("[LEFT] Wi-Fi=%s channel=%d submitted_total=%lu submit_errors=%lu (not delivery ACKs)\n",
      WiFi.status() == WL_CONNECTED ? "connected" : "joining", WiFi.channel(),
      (unsigned long)submitted, (unsigned long)submitErrors);
  }
  delay(1);
}
