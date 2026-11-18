// Bare-board/MPU gateway: left ESP-NOW + right local samples -> Ultra96 TLS.
// Keep test_config.h and server_cert.h beside this sketch.
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_now.h>
#include <esp_arduino_version.h>
#if __has_include(<esp_mac.h>)
#include <esp_mac.h>
#else
#include <esp_system.h>
#endif
#include "test_config.h"
#include "server_cert.h"

struct __attribute__((packed)) SensorMsg {
  uint8_t type, nodeID;
  uint32_t timestamp;
  int16_t ax, ay, az, gx, gy, gz;
};

// Millisecond four-timestamp exchange; all subtraction is modulo uint32.
struct __attribute__((packed)) SyncPing { uint8_t type; uint32_t t0; };
struct __attribute__((packed)) SyncReply {
  uint8_t type; uint32_t t0, t1, t2, boot;
};
static_assert(sizeof(SyncPing) == 5 && sizeof(SyncReply) == 17, "sync wire layout");

struct __attribute__((packed)) ActuateMsg {
  uint8_t type, nodeID, command, duration;
};
static_assert(sizeof(SensorMsg) == 18, "ESP-NOW sensor layout changed");
static_assert(sizeof(ActuateMsg) == 4, "ESP-NOW command layout changed");

WiFiClientSecure gatewayTls;
portMUX_TYPE queueMux = portMUX_INITIALIZER_UNLOCKED;
const uint8_t QUEUE_SIZE = 64;
uint8_t qHead = 0, qTail = 0, qCount = 0;
struct Queued { SensorMsg sample; uint32_t epoch; };
Queued leftQueue[QUEUE_SIZE], rightQueue[QUEUE_SIZE];
uint8_t rHead = 0, rTail = 0, rCount = 0;
uint32_t rightDrops = 0, syncEpoch = 1, leftBoot = 0, syncAt = 0;
uint32_t pendingPing = 0, syncRtt = 0;
int32_t leftOffset = 0;
bool clockSynced = false, pingPending = false;
// Caller holds queueMux. Epoch changes invalidate every AI window.
void newEpochLocked() {
  syncEpoch++;
  rHead = rTail = rCount = 0;
  qHead = qTail = qCount = 0;
}

bool readRight(SensorMsg &s);
bool sendSensor(const SensorMsg &s, uint32_t epoch);
bool takeLeft(Queued &s);
bool takeRight(Queued &s);

uint32_t leftReceived = 0, queueDrops = 0;
uint32_t leftSent = 0, rightSent = 0, badPackets = 0;
uint8_t rx[32], rxCount = 0, sessionID = 0, missingHeartbeats = 0;
bool handshakeDone = false, awaitingHandshake = false;
uint32_t handshakeAt = 0, heartbeatAt = 0, reconnectAt = 0;
uint32_t reconnectDelay = 500, nextSampleUs = 0;
bool motorActive = false;
uint32_t motorAt = 0;
uint8_t motorDuration = 0;

uint8_t xorBytes(const uint8_t *p, size_t n) {
  uint8_t x = 0; while (n--) x ^= *p++; return x;
}
void put16(uint8_t *p, int16_t v) {
  uint16_t u = (uint16_t)v; p[0] = u & 255; p[1] = u >> 8;
}
void put32(uint8_t *p, uint32_t v) {
  for (int i = 0; i < 4; i++) p[i] = (v >> (8 * i)) & 255;
}
void clearQueue() {
  portENTER_CRITICAL(&queueMux);
  qHead = qTail = qCount = 0;
  rHead = rTail = rCount = 0;
  portEXIT_CRITICAL(&queueMux);
}
void loseLink(const char *reason) {
  Serial.print("[LINK] "); Serial.println(reason);
  gatewayTls.stop(); handshakeDone = awaitingHandshake = false;
  rxCount = 0; missingHeartbeats = 0; clearQueue();
  reconnectAt = millis() + reconnectDelay;
  reconnectDelay = reconnectDelay < 2500 ? reconnectDelay * 2 : 5000;
}
bool writeAll(const uint8_t *p, size_t n) {
  uint32_t began = millis(); size_t offset = 0;
  while (offset < n && gatewayTls.connected() && millis() - began < 1500) {
    size_t sent = gatewayTls.write(p + offset, n - offset);
    if (sent > n - offset) break;
    offset += sent;
    if (!sent) delay(1);
  }
  if (offset != n) { loseLink("incomplete TLS write"); return false; }
  return true;
}
bool sendFrame(uint8_t type, const uint8_t *payload, uint8_t length) {
  uint8_t packet[32];
  packet[0] = 0xAA; packet[1] = type;
  memcpy(packet + 2, payload, length);
  packet[2 + length] = xorBytes(packet + 1, length + 1);
  packet[3 + length] = 0x55;
  return writeAll(packet, length + 4);
}
bool sendSensor(const SensorMsg &s, uint32_t epoch) {
  uint8_t data[22];
  data[0] = PLAYER_ID; data[1] = s.nodeID;
  put32(data + 2, s.timestamp);
  put16(data + 6, s.ax); put16(data + 8, s.ay); put16(data + 10, s.az);
  put16(data + 12, s.gx); put16(data + 14, s.gy); put16(data + 16, s.gz);
  put32(data + 18, epoch);
  return sendFrame(0x05, data, sizeof(data));
}
bool mpuWrite(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(0x68); Wire.write(reg); Wire.write(value);
  return Wire.endTransmission() == 0;
}
bool initializeMPU() {
  if (SIMULATED_SENSORS) return true;
  Wire.begin(); Wire.setClock(400000);
  return mpuWrite(0x6B, 0) && mpuWrite(0x1B, 0x18) &&
         mpuWrite(0x1C, 0x18) && mpuWrite(0x1A, 3) && mpuWrite(0x19, 9);
}
bool readRight(SensorMsg &s) {
  s.type = 1; s.nodeID = 2; s.timestamp = millis();
  if (SIMULATED_SENSORS) {
    s.ax = 200; s.ay = 0; s.az = 2048; s.gx = s.gy = s.gz = 0;
    return true;
  }
  Wire.beginTransmission(0x68); Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom((uint8_t)0x68, (uint8_t)14, (uint8_t)true) != 14)
    return false;
  uint8_t b[14]; for (int i = 0; i < 14; i++) b[i] = Wire.read();
  s.ax = (int16_t)((b[0] << 8) | b[1]);
  s.ay = (int16_t)((b[2] << 8) | b[3]);
  s.az = (int16_t)((b[4] << 8) | b[5]);
  s.gx = (int16_t)((b[8] << 8) | b[9]);
  s.gy = (int16_t)((b[10] << 8) | b[11]);
  s.gz = (int16_t)((b[12] << 8) | b[13]);
  return true;
}
void receiveLeft(const uint8_t *mac, const uint8_t *data, int length) {
  if (memcmp(mac, LEFT_MAC, 6) != 0) return;
  uint32_t now = millis();
  if (length == sizeof(SyncReply) && data[0] == 0x21) {
    SyncReply reply; memcpy(&reply, data, sizeof(reply));
    portENTER_CRITICAL(&queueMux);
    int32_t elapsed = (int32_t)(now - reply.t0);
    int32_t processing = (int32_t)(reply.t2 - reply.t1);
    int32_t rtt = elapsed - processing;
    if (pingPending && reply.t0 == pendingPing && elapsed >= 0 && elapsed < 30 &&
        processing >= 0 && rtt >= 0 && rtt <= 6) {
      pingPending = false;
      int32_t offset = (int32_t)(((int64_t)(int32_t)(reply.t0 - reply.t1) +
                                (int32_t)(now - reply.t2)) / 2);
      int64_t correction = (int64_t)offset - leftOffset;
      if (!clockSynced || reply.boot != leftBoot || correction > 3 || correction < -3) {
        newEpochLocked();
        leftOffset = offset;
      } else {
        leftOffset += (int32_t)(correction / 2);
      }
      clockSynced = true; leftBoot = reply.boot; syncAt = now; syncRtt = rtt;
    }
    portEXIT_CRITICAL(&queueMux);
    return;
  }
  if (length != sizeof(SensorMsg)) return;
  SensorMsg s; memcpy(&s, data, sizeof(s));
  if (s.type != 1 || s.nodeID != 1) return;
  portENTER_CRITICAL(&queueMux);
  leftReceived++;
  if (clockSynced && now - syncAt < 3000) {
    s.timestamp += (uint32_t)leftOffset;
    int32_t age = (int32_t)(now - s.timestamp);
    if (age >= -5 && age <= 100) {
      if (qCount == QUEUE_SIZE) queueDrops++;
      else { leftQueue[qTail] = {s, syncEpoch}; qTail = (qTail + 1) % QUEUE_SIZE; qCount++; }
    }
  }
  portEXIT_CRITICAL(&queueMux);
}
#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int length) {
  receiveLeft(info->src_addr, data, length);
}
#else
void onReceive(const uint8_t *mac, const uint8_t *data, int length) {
  receiveLeft(mac, data, length);
}
#endif
bool takeLeft(Queued &s) {
  portENTER_CRITICAL(&queueMux);
  bool available = qCount != 0;
  if (available) { s = leftQueue[qHead]; qHead = (qHead + 1) % QUEUE_SIZE; qCount--; }
  portEXIT_CRITICAL(&queueMux);
  return available;
}
bool takeRight(Queued &s) {
  portENTER_CRITICAL(&queueMux);
  bool available = rCount != 0;
  if (available) { s = rightQueue[rHead]; rHead = (rHead + 1) % QUEUE_SIZE; rCount--; }
  portEXIT_CRITICAL(&queueMux);
  return available;
}
void sampleTask(void *) {
  TickType_t wake = xTaskGetTickCount();
  uint32_t pingAt = 0;
  for (;;) {
    uint32_t now = millis(); bool synced;
    portENTER_CRITICAL(&queueMux);
    if (clockSynced && now - syncAt >= 3000) { clockSynced = false; newEpochLocked(); }
    synced = clockSynced;
    portEXIT_CRITICAL(&queueMux);
    if (WiFi.status() == WL_CONNECTED && now - pingAt >= (synced ? 1000U : 100U)) {
      SyncPing ping{0x20, now};
      portENTER_CRITICAL(&queueMux);
      pendingPing = now; pingPending = true;
      portEXIT_CRITICAL(&queueMux);
      esp_now_send(LEFT_MAC, (uint8_t *)&ping, sizeof(ping)); pingAt = now;
    }
    SensorMsg s;
    if (readRight(s)) {
      portENTER_CRITICAL(&queueMux);
      if (rCount == QUEUE_SIZE) rightDrops++;
      else { rightQueue[rTail] = {s, syncEpoch}; rTail = (rTail + 1) % QUEUE_SIZE; rCount++; }
      portEXIT_CRITICAL(&queueMux);
    }
    if ((int32_t)(xTaskGetTickCount() - wake) > (int32_t)pdMS_TO_TICKS(10)) wake = xTaskGetTickCount();
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(10));
  }
}

void actuate(uint8_t node, uint8_t command, uint8_t duration) {
  if (command > 1) {
    Serial.println("[ACTUATE] demo command 2 is not implemented by this hardware gateway");
    return;
  }
  if (node == 1) {
    ActuateMsg msg{0x10, 1, command, duration};
    esp_err_t result = esp_now_send(LEFT_MAC, (uint8_t *)&msg, sizeof(msg));
    Serial.printf("[ACTUATE] LEFT submitted, result=%d (not application ACK)\n", (int)result);
  } else if (node == 2) {
    Serial.printf("[ACTUATE] RIGHT command=%u duration=%u ms%s\n", command, duration,
                  SIMULATED_SENSORS ? " (simulation: no motor driven)" : "");
    if (!SIMULATED_SENSORS) {
      analogWrite(25, command == 1 && duration ? 165 : 0);
      motorActive = command == 1 && duration; motorAt = millis(); motorDuration = duration;
    }
  }
}
uint8_t packetLength(uint8_t type) {
  switch (type) {
    case 0x01: return 9; case 0x04: return 5;
    case 0x10: return 7; case 0x1F: return 6;
    default: return 0;
  }
}
void consumeRx(uint8_t n) {
  memmove(rx, rx + n, rxCount - n); rxCount -= n;
}
void readServer() {
  while (gatewayTls.connected() && gatewayTls.available()) {
    if (rxCount == sizeof(rx)) consumeRx(1);
    rx[rxCount++] = (uint8_t)gatewayTls.read();
    while (rxCount) {
      if (rx[0] != 0xAA) { consumeRx(1); continue; }
      if (rxCount < 2) break;
      uint8_t n = packetLength(rx[1]);
      if (!n) { consumeRx(1); continue; }
      if (rxCount < n) break;  // Keep partial TCP frames for the next read.
      if (rx[n - 1] != 0x55 || xorBytes(rx + 1, n - 3) != rx[n - 2]) {
        badPackets++; consumeRx(1); continue;
      }
      uint8_t type = rx[1];
      if (type == 0x01 && awaitingHandshake) {
        sessionID = rx[2]; handshakeDone = true; awaitingHandshake = false;
        reconnectDelay = 500; missingHeartbeats = 0; heartbeatAt = millis();
        clearQueue(); nextSampleUs = micros() + 10000;
        Serial.printf("[HANDSHAKE] OK player=%u gateway_node=2 session=%u\n", PLAYER_ID, sessionID);
      } else if (type == 0x04 && handshakeDone && rx[2] == sessionID) {
        missingHeartbeats = 0;
      } else if (type == 0x10 && handshakeDone) {
        actuate(rx[2], rx[3], rx[4]);
      } else if (type == 0x1F) {
        loseLink("server DISCONNECT"); return;
      }
      consumeRx(n);
    }
  }
}
void maintainConnections() {
  static uint32_t wifiAttempt = 0;
  uint32_t now = millis();
  if (WiFi.status() != WL_CONNECTED) {
    if (gatewayTls.connected() || handshakeDone || awaitingHandshake) loseLink("Wi-Fi lost");
    if (now - wifiAttempt >= 10000) {
      wifiAttempt = now;
      Serial.println("[WIFI] joining hotspot"); WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
    return;
  }
  if (!gatewayTls.connected()) {
    if (handshakeDone || awaitingHandshake) { loseLink("TLS connection lost"); return; }
    if ((int32_t)(now - reconnectAt) < 0) return;
    Serial.printf("[TLS] connecting to %s:%u, Wi-Fi channel=%d\n", ULTRA96_TUNNEL_HOST, ULTRA96_TUNNEL_PORT, WiFi.channel());
    gatewayTls.stop(); rxCount = 0;
    gatewayTls.setHandshakeTimeout(5); gatewayTls.setTimeout(2);
    if (!gatewayTls.connect(ULTRA96_TUNNEL_HOST, ULTRA96_TUNNEL_PORT)) {
      loseLink("TLS connect failed; check hotspot, tunnel, server and certificate"); return;
    }
    awaitingHandshake = true; handshakeAt = millis();
    uint8_t hello[] = {PLAYER_ID, 2, 4};
    if (sendFrame(0x00, hello, sizeof(hello))) Serial.println("[HANDSHAKE] sent, waiting for ACK");
  }
  if (awaitingHandshake && millis() - handshakeAt > 8000) loseLink("HANDSHAKE_ACK timeout");
}
void printBoardMac() {
  uint8_t mac[6] = {};
  esp_err_t result = esp_read_mac(mac, ESP_MAC_WIFI_STA);
  if (result != ESP_OK) {
    Serial.printf("[MAC] read failed, error=%d\n", (int)result);
    return;
  }
  Serial.printf("RIGHT STA MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
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
  esp_now_peer_info_t peer{};
  memcpy(peer.peer_addr, LEFT_MAC, 6); peer.channel = 0; peer.ifidx = WIFI_IF_STA; peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) Serial.println("[CONFIG] LEFT peer not added; set LEFT_MAC and upload again");
  gatewayTls.setCACert(SERVER_CERT);  // No setInsecure(): pin/trust the supplied server certificate.
  gatewayTls.setHandshakeTimeout(5); gatewayTls.setTimeout(2); // Secure client timeout is in seconds.
  reconnectAt = millis(); nextSampleUs = micros();
  Serial.println("[LIVE] fw4: synchronized type 0x05; right clock is the common time base");
  if (xTaskCreate(sampleTask, "rightSampleSync", 4096, nullptr, 2, nullptr) != pdPASS) {
    Serial.println("sample task failed"); while (true) delay(1000);
  }
}
void loop() {
  static uint32_t lastMacPrint = 0;
  if (millis() - lastMacPrint >= 10000) {
    lastMacPrint = millis(); printBoardMac();
  }
  if (motorActive && millis() - motorAt >= motorDuration) { analogWrite(25, 0); motorActive = false; }
  maintainConnections();
  if (gatewayTls.connected()) readServer();
  if (handshakeDone && gatewayTls.connected()) {
    Queued q;
    for (int i = 0; i < 8 && handshakeDone; i++) {
      if (takeLeft(q) && (int32_t)(millis() - q.sample.timestamp) <= 100) {
        if (!sendSensor(q.sample, q.epoch)) break;
        leftSent++;
      }
      if (takeRight(q) && (int32_t)(millis() - q.sample.timestamp) <= 100) {
        if (!sendSensor(q.sample, q.epoch)) break;
        rightSent++;
      }
    }
    if (handshakeDone && millis() - heartbeatAt >= 1000) {
      if (missingHeartbeats >= 3) loseLink("3 heartbeat ACKs missing");
      else {
        uint8_t payload[] = {PLAYER_ID, 2};
        if (sendFrame(0x03, payload, sizeof(payload))) { missingHeartbeats++; heartbeatAt = millis(); }
      }
    }
  } else clearQueue();  // No outage replay of old left samples.
  static uint32_t reportAt = 0, lastLeft = 0, lastRight = 0;
  if (millis() - reportAt >= 1000) {
    uint32_t now = millis(), received, drops;
    portENTER_CRITICAL(&queueMux); received = leftReceived; drops = queueDrops; portEXIT_CRITICAL(&queueMux);
    Serial.printf("[RATE] left_tx=%.1f/s right_tx=%.1f/s left_rx_total=%lu queue_drops=%lu bad_downlink=%lu\n",
      (leftSent - lastLeft) * 1000.0f / (now - reportAt),
      (rightSent - lastRight) * 1000.0f / (now - reportAt),
      (unsigned long)received, (unsigned long)drops, (unsigned long)badPackets);
    bool synced; uint32_t epoch, rtt, rd; int32_t offset;
    portENTER_CRITICAL(&queueMux);
    synced = clockSynced; epoch = syncEpoch; rtt = syncRtt; rd = rightDrops; offset = leftOffset;
    portEXIT_CRITICAL(&queueMux);
    Serial.printf("[SYNC] valid=%u epoch=%lu RTT=%lu ms right_minus_left=%ld ms right_drops=%lu\n",
      synced, (unsigned long)epoch, (unsigned long)rtt, (long)offset, (unsigned long)rd);
    lastLeft = leftSent; lastRight = rightSent; reportAt = now;
  }
  delay(1);
}
