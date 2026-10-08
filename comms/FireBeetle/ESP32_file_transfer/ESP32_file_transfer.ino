/* Standalone TLS file-upload demo. Uses the existing SSH-forwarded port 8888.
 * Flash this sketch, unplug USB from the relay laptop, and power from a bank.
 * It automatically sends the real file embedded by embed_file.py. Reset to
 * repeat. No Serial Monitor commands are needed during the demonstration.
 *
 * Extension envelope: [AA][type][fixed payload][XOR(type+payload)][55].
 * BEGIN 0x20: uint32 id, uint32 size, SHA256[32], filename[32].
 * DATA  0x21: uint32 id, uint32 offset, uint16 validLen, data[256], uint32 CRC32.
 * FINISH 0x22: uint32 id. ACK 0x23: uint32 id, uint32 nextOffset, uint8 status.
 * Integers are little-endian. ACK every chunk; no use of TCP read boundaries.
 * Errors restart the entire file on a fresh connection (no resume support).
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_system.h>
#include <string.h>
#include "server_cert.h"
#include "file_payload.h"

const char* WIFI_SSID = "LYS8700";
const char* WIFI_PASSWORD = "20031123";
const char* SERVER_HOST = "192.168.137.1";
const uint16_t SERVER_PORT = 8888;
const uint32_t IO_TIMEOUT_MS = 15000;
const size_t CHUNK_SIZE = 256;
const uint8_t PKT_BEGIN = 0x20, PKT_DATA = 0x21, PKT_FINISH = 0x22, PKT_ACK = 0x23;
const uint8_t STATUS_OK = 0, STATUS_COMPLETE = 1;
WiFiClientSecure client;
bool uploadDone = false;
uint32_t nextAttemptAt = 0;
uint32_t retryDelayMs = 1000;

void put16(uint8_t* p, uint16_t v) {
  p[0] = v; p[1] = v >> 8;
}
void put32(uint8_t* p, uint32_t v) {
  for (int i = 0; i < 4; ++i) p[i] = v >> (8 * i);
}
uint32_t get32(const uint8_t* p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
         ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
uint8_t xorChecksum(const uint8_t* p, size_t n) {
  uint8_t result = 0;
  for (size_t i = 0; i < n; ++i) result ^= p[i];
  return result;
}
// Standard CRC32/IEEE, matches Python zlib.crc32().
uint32_t crc32(const uint8_t* p, size_t n) {
  uint32_t value = 0xFFFFFFFFu;
  for (size_t i = 0; i < n; ++i) {
    value ^= p[i];
    for (int j = 0; j < 8; ++j)
      value = (value >> 1) ^ ((value & 1u) ? 0xEDB88320u : 0u);
  }
  return value ^ 0xFFFFFFFFu;
}
bool writeAll(const uint8_t* p, size_t n) {
  size_t done = 0;
  uint32_t started = millis();
  while (done < n) {
    if (!client.connected() || millis() - started >= IO_TIMEOUT_MS) return false;
    size_t count = client.write(p + done, n - done);
    done += count;
    if (count == 0) delay(1);
  }
  return true;
}
bool readExact(uint8_t* p, size_t n) {
  size_t done = 0;
  uint32_t started = millis();
  while (done < n) {
    if (millis() - started >= IO_TIMEOUT_MS) return false;
    int available = client.available();
    if (available > 0) {
      size_t remaining = n - done;
      size_t count = (size_t)available < remaining ? (size_t)available : remaining;
      int got = client.read(p + done, count);
      if (got > 0) done += (size_t)got;
      else if (got < 0) return false;
    } else {
      if (!client.connected()) return false;
      delay(1);
    }
  }
  return true;
}
bool sendPacket(uint8_t kind, const uint8_t* payload, size_t length) {
  uint8_t packet[274]; // largest payload = 270 bytes; envelope = 4.
  if (length > sizeof(packet) - 4) return false;
  packet[0] = 0xAA;
  packet[1] = kind;
  memcpy(packet + 2, payload, length);
  packet[2 + length] = xorChecksum(packet + 1, length + 1);
  packet[3 + length] = 0x55;
  return writeAll(packet, length + 4);
}
bool awaitAck(uint32_t id, uint32_t nextOffset, uint8_t status) {
  uint8_t ack[13];
  if (!readExact(ack, sizeof(ack))) {
    Serial.println("ACK timeout or connection lost");
    return false;
  }
  if (ack[0] != 0xAA || ack[1] != PKT_ACK || ack[12] != 0x55 ||
      xorChecksum(ack + 1, 10) != ack[11]) {
    Serial.println("Invalid ACK frame");
    return false;
  }
  if (get32(ack + 2) != id || get32(ack + 6) != nextOffset || ack[10] != status) {
    Serial.println("ACK rejected: transfer id, offset, or status mismatch");
    return false;
  }
  return true;
}
bool connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 15000) delay(100);
  if (WiFi.status() != WL_CONNECTED) return false;
  WiFi.setSleep(false);
  return true;
}
bool uploadFile() {
  if (!connectWifi()) return false;
  client.stop();
  client.setCACert(SERVER_CERT); // same public certificate as the existing demo.
  if (!client.connect(SERVER_HOST, SERVER_PORT)) {
    char why[120] = {0};
    client.lastError(why, sizeof(why));
    Serial.printf("TLS connect failed: %s\n", why);
    return false;
  }
  client.setNoDelay(true);
  uint32_t id = esp_random();
  uint8_t begin[72] = {0};
  put32(begin, id);
  put32(begin + 4, FILE_SIZE);
  memcpy(begin + 8, FILE_SHA256, 32);
  memcpy(begin + 40, FILE_NAME, strlen(FILE_NAME));
  Serial.printf("Uploading %s (%lu bytes), id=%lu\n", FILE_NAME,
                (unsigned long)FILE_SIZE, (unsigned long)id);
  if (!sendPacket(PKT_BEGIN, begin, sizeof(begin)) || !awaitAck(id, 0, STATUS_OK))
    return false;
  for (uint32_t offset = 0; offset < FILE_SIZE;) {
    uint32_t remaining = FILE_SIZE - offset;
    uint16_t length = (uint16_t)(remaining < CHUNK_SIZE ? remaining : CHUNK_SIZE);
    uint8_t data[270] = {0};
    put32(data, id);
    put32(data + 4, offset);
    put16(data + 8, length);
    for (uint16_t i = 0; i < length; ++i)
      data[10 + i] = pgm_read_byte(FILE_BYTES + offset + i);
    put32(data + 266, crc32(data + 10, length));
    if (!sendPacket(PKT_DATA, data, sizeof(data)) ||
        !awaitAck(id, offset + length, STATUS_OK)) return false;
    offset += length;
  }
  uint8_t finish[4];
  put32(finish, id);
  if (!sendPacket(PKT_FINISH, finish, sizeof(finish)) ||
      !awaitAck(id, FILE_SIZE, STATUS_COMPLETE)) return false;
  Serial.println("FILE VERIFIED by Ultra96: length and SHA256 match");
  return true;
}
void setup() {
  Serial.begin(115200);
  delay(1000);
  WiFi.mode(WIFI_STA);
  nextAttemptAt = millis() + 2000;
}
void loop() {
  if (uploadDone) { delay(100); return; }
  if ((int32_t)(millis() - nextAttemptAt) < 0) { delay(10); return; }
  uploadDone = uploadFile();
  client.stop();
  if (!uploadDone) {
    Serial.println("Upload failed; retrying the whole file on a new connection");
    nextAttemptAt = millis() + retryDelayMs;
    retryDelayMs = retryDelayMs < 8000 ? retryDelayMs * 2 : 8000;
  }
}
