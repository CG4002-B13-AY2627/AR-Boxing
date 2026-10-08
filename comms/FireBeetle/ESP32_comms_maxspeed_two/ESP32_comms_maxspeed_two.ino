/*
  ESP32 firmware implementing the design report's packet protocol (Section 4.2).
  Pair with comms_server.py on the Ultra96 (protocol.py holds the byte layouts).

  Life of a connection:
    1. TCP connect (through the laptop's SSH tunnel)
    2. send HANDSHAKE, and send NOTHING ELSE until HANDSHAKE_ACK arrives.
       The tunnel accepts connections even when nothing is behind it, so the
       ACK is the only proof the Ultra96 is really there.
    3. HANDSHAKE_ACK carries the server time; we align our clock to it
       (Section 4.7) and stamp every SENSOR_DATA with that aligned time.
    4. stream SENSOR_DATA every SAMPLE_PERIOD_MS.
       If nothing has been sent for a second (idle / lobby), send HEARTBEAT
       instead. Three heartbeats in a row with no HEARTBEAT_ACK = link dead.
    5. any failure: drop the connection, back off 250 ms -> 5 s, reconnect,
       handshake again.

  Serial Monitor commands (115200):
    i   idle: stop streaming, heartbeats only (to demo the heartbeat)
    s   streaming again (normal 100 Hz)
    m   MAX SPEED: batches of packets, as fast as the link allows ('s' to stop)
    w   simulate a 15 s WiFi outage without walking anywhere

  TLS (see TLS_MODE below): the same packets, wrapped in an encrypted channel.
  Run comms_server.py with --tls when TLS_MODE is 1 or 2, without it for 0.

  Sensor values are FAKE (no MPU6050 needed). Replace the random() block in
  sendSensorData() with real readings.
*/

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <string.h>

// TLS_MODE:
//   0 = plain TCP.                   Server WITHOUT --tls.
//   1 = TLS, certificate NOT checked. Encrypted, but the server is not authenticated
//       (anyone could impersonate it). Use this FIRST to test the TLS plumbing.
//   2 = TLS + only the certificate pinned below is trusted. The intended final setting.
//       Server WITH --tls, using the matching server.crt / server.key.
// If mode 2 fails but mode 1 works, the problem is the certificate check, not the encryption.
#define TLS_MODE 2

const char* WIFI_SSID = "LYS8700";
const char* WIFI_PASSWORD = "20031123";

const char* SERVER_IP = "192.168.137.1";
const uint16_t SERVER_PORT = 8888;

const uint8_t PLAYER_ID  = 1;
const uint8_t NODE_ID    = 0x02;   // 0x01 = left hand, 0x02 = right hand
const uint8_t FW_VERSION = 1;

const uint32_t SAMPLE_PERIOD_MS       = 10;    // 100 Hz (Section 5.3.1)
const uint32_t HEARTBEAT_INTERVAL_MS  = 1000;  // Section 4.2.5
const uint8_t  MAX_UNACKED_HEARTBEATS = 3;
const uint32_t HANDSHAKE_TIMEOUT_MS   = 8000;  // the tunnel can take seconds to open a new channel
const uint32_t BACKOFF_MIN_MS         = 250;   // Section 4.3
const uint32_t BACKOFF_MAX_MS         = 5000;

const uint8_t ACTUATOR_PIN = 25;               // IO25 -> MOSFET gate -> vibration motor (Section 3.3)

// Packet constants (see protocol.py)
const uint8_t PKT_START         = 0xAA;
const uint8_t PKT_END           = 0x55;
const uint8_t PKT_HANDSHAKE     = 0x00;
const uint8_t PKT_HANDSHAKE_ACK = 0x01;
const uint8_t PKT_SENSOR_DATA   = 0x02;
const uint8_t PKT_HEARTBEAT     = 0x03;
const uint8_t PKT_HEARTBEAT_ACK = 0x04;
const uint8_t PKT_ACTUATE       = 0x10;
const uint8_t PKT_DISCONNECT    = 0x1F;

#if TLS_MODE == 0
WiFiClient client;
#else
WiFiClientSecure client;
#endif

// The server's certificate, pinned as the only trusted one (TLS_MODE 2).
// make_cert.py writes this block; it is valid 1960-2049 because the ESP32 has no
// real-time clock and thinks it is 1970 at boot.
// BEGIN SERVER_CERT (written by make_cert.py, do not edit by hand)
const char* SERVER_CERT = R"EOF(
-----BEGIN CERTIFICATE-----
MIIDXzCCAkegAwIBAgIUH3ypu1xG9RQhbajRKSmYMPtgj6cwDQYJKoZIhvcNAQEL
BQAwLTETMBEGA1UECgwKQ0c0MDAyLUIxMzEWMBQGA1UEAwwNMTkyLjE2OC4xMzcu
MTAeFw02MDAxMDEwMDAwMDBaFw00OTEyMzEyMzU5NTlaMC0xEzARBgNVBAoMCkNH
NDAwMi1CMTMxFjAUBgNVBAMMDTE5Mi4xNjguMTM3LjEwggEiMA0GCSqGSIb3DQEB
AQUAA4IBDwAwggEKAoIBAQCbGbyTLcF4Ggj6Ry4JH8E1DNUVmnFaVdERUFf4M8hv
hgYR4u4qFkEUB/bPAadfadzS1dU/nGDP4EdWFk6GPmKLsbL196U03MJwXu0vi5J6
n2XtjmlPw5ABZ/HLZF9+Xfv930yWuRjwCOjDECrNOa+XiVpgXBpKpxoyQNZd+ZF4
eGzUZHebfsjbSfMcRIdzIH0nc7SXMxXDYjDmpeqDbT3TrIolGy1U7cU2T/tknd57
wefoW4Pr/ZiUTXts/u+2opN7fFPOwbSZoskY1KzFziNaiIPFTDLtB9/2Q6j9aXD+
TaO03RZ9RqtAifoLi3I2dhfD4ZdFLteULSGBSJbA9ojDAgMBAAGjdzB1MA8GA1Ud
EwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgKkMBMGA1UdJQQMMAoGCCsGAQUFBwMB
MB4GA1UdEQQXMBWCDTE5Mi4xNjguMTM3LjGHBMCoiQEwHQYDVR0OBBYEFLfIc2hH
31o6UxN4IeAZYPqLUWx6MA0GCSqGSIb3DQEBCwUAA4IBAQCOOZwV13mWQbaDHhFg
t/1MfvyP1POiOt5ZMG1DULlae/gWuQS/vbxRMqalTdeOB9Yl7mia8lwWUDxiGijn
Vh/SUXFyGMNd8rPFJIb5lfQpglHlnDG2EztkB9TMWka1BJvnJzudr+aCis+eCtUe
amDzKSlyFEBSzYHFYvSPnjSsdYC8ElPlEpW9nOXB17QIYcYxBLc95RypXAglESZE
memfODgM8rovZgPhIRnC0H7dno4n3oLB8PZ46wFk6VhsI7dDSoJuph44TCmGbrCR
m2Wenp3/olkwwAUEIpkY8SDJ2vt66QcJaXcMz9aWlR/l0hEPYUlpiXoeOaZGl1Wr
pNnl
-----END CERTIFICATE-----
)EOF";
// END SERVER_CERT

// --- connection / session state ---------------------------------------------
bool     sessionActive = false;      // a TCP connection was established and not yet cleaned up
bool     handshakeDone = false;      // HANDSHAKE_ACK received on this connection
uint8_t  sessionId = 0;
int32_t  clockOffset = 0;            // add to millis() to get server-aligned time
uint32_t handshakeSentMs = 0;
uint32_t connectedAtMs = 0;
uint32_t lastPacketSentMs = 0;       // any packet: heartbeat only fires when we've been quiet
uint32_t lastSampleMs = 0;
uint32_t lastStatusMs = 0;
uint8_t  heartbeatsUnacked = 0;
bool     streaming = true;
bool     maxSpeed = true;           // burst mode, see sendSensorBurst()
uint32_t lastStatusFrames = 0;
uint32_t backoffMs = BACKOFF_MIN_MS;
uint32_t framesSent = 0;
bool     recovering = false;         // true from "noticed the link was lost" until re-handshaked
uint32_t linkLostAtMs = 0;
uint32_t outageEndMs = 0;            // debug: end of a simulated WiFi outage

// --- actuator ---------------------------------------------------------------
bool     actuatorOn = false;
uint32_t actuatorOffAtMs = 0;        // 0 = stay on until a stop command

// ---------------------------------------------------------------------------
void markLinkLost() {
  if (!recovering) {
    recovering = true;
    linkLostAtMs = millis();
  }
}

// Server-aligned time, as used in every SENSOR_DATA timestamp (Section 4.7).
uint32_t syncedTimeMs() {
  return millis() + (uint32_t)clockOffset;
}

void writeU32LE(uint8_t* buf, int offset, uint32_t value) {
  buf[offset]     = value & 0xFF;
  buf[offset + 1] = (value >> 8) & 0xFF;
  buf[offset + 2] = (value >> 16) & 0xFF;
  buf[offset + 3] = (value >> 24) & 0xFF;
}

void writeI16LE(uint8_t* buf, int offset, int16_t value) {
  buf[offset]     = value & 0xFF;
  buf[offset + 1] = (value >> 8) & 0xFF;
}

uint8_t xorChecksum(const uint8_t* data, size_t len) {
  uint8_t c = 0;
  for (size_t i = 0; i < len; i++) c ^= data[i];
  return c;
}

// Writes ALL bytes even if write() accepts only part of them: abandoning a
// half-written packet would corrupt the byte stream. False = connection dead.
bool writeAll(const uint8_t* buf, size_t len) {
  size_t done = 0;
  uint32_t start = millis();
  while (done < len) {
    size_t n = client.write(buf + done, len - done);
    if (n > 0) { done += n; continue; }
    if (!client.connected() || millis() - start > 1000) return false;
    delay(1);
  }
  return true;
}

// Builds [START][type][payload][checksum][END] into out and returns its length.
size_t buildPacket(uint8_t* out, uint8_t type, const uint8_t* payload, size_t payloadLen) {
  out[0] = PKT_START;
  out[1] = type;
  memcpy(out + 2, payload, payloadLen);
  out[2 + payloadLen] = xorChecksum(out + 1, 1 + payloadLen);   // Type through end of payload
  out[3 + payloadLen] = PKT_END;
  return payloadLen + 4;
}

bool sendPacket(uint8_t type, const uint8_t* payload, size_t payloadLen) {
  uint8_t pkt[32];
  size_t n = buildPacket(pkt, type, payload, payloadLen);
  bool ok = writeAll(pkt, n);
  if (ok) lastPacketSentMs = millis();
  return ok;
}

bool sendHandshake() {
  uint8_t p[3] = { PLAYER_ID, NODE_ID, FW_VERSION };
  handshakeSentMs = millis();
  return sendPacket(PKT_HANDSHAKE, p, 3);
}

bool sendHeartbeat() {
  uint8_t p[2] = { PLAYER_ID, NODE_ID };
  return sendPacket(PKT_HEARTBEAT, p, 2);
}

// Fills the 18-byte SENSOR_DATA payload. FAKE readings: replace with the MPU6050 here.
void fillSensorPayload(uint8_t* p) {
  int16_t ax = random(-2000, 2000);
  int16_t ay = random(-2000, 2000);
  int16_t az = random(6000, 10000);
  int16_t gx = random(-50, 50);
  int16_t gy = random(-50, 50);
  int16_t gz = random(-50, 50);
  p[0] = PLAYER_ID;
  p[1] = NODE_ID;
  writeU32LE(p, 2, syncedTimeMs());
  writeI16LE(p, 6, ax);
  writeI16LE(p, 8, ay);
  writeI16LE(p, 10, az);
  writeI16LE(p, 12, gx);
  writeI16LE(p, 14, gy);
  writeI16LE(p, 16, gz);
}

bool sendSensorData() {
  uint8_t p[18];
  fillSensorPayload(p);
  return sendPacket(PKT_SENSOR_DATA, p, 18);
}

// Max-speed mode: BURST_PACKETS SENSOR_DATA packets in ONE write(). Every write has
// a fixed cost (TCP/TLS headers, WiFi airtime), so batching raises throughput a lot.
// The price is latency: the first packet of a batch waits for the rest to be built.
const uint8_t BURST_PACKETS = 10;

bool sendSensorBurst() {
  uint8_t buf[22 * BURST_PACKETS];
  uint8_t p[18];
  for (uint8_t i = 0; i < BURST_PACKETS; i++) {
    fillSensorPayload(p);
    buildPacket(buf + 22 * i, PKT_SENSOR_DATA, p, 18);
  }
  bool ok = writeAll(buf, sizeof buf);
  if (ok) lastPacketSentMs = millis();
  return ok;
}

// --- incoming (server -> ESP32) ---------------------------------------------
uint8_t rxBuf[16];
uint8_t rxLen = 0;

// Total length of the packet types the server may send us; 0 = unknown type.
uint8_t incomingLength(uint8_t type) {
  switch (type) {
    case PKT_HANDSHAKE_ACK: return 9;
    case PKT_HEARTBEAT_ACK: return 5;
    case PKT_ACTUATE:       return 7;
    case PKT_DISCONNECT:    return 6;
    default:                return 0;
  }
}

void onPacket(uint8_t type, const uint8_t* p) {
  if (type == PKT_HANDSHAKE_ACK) {
    sessionId = p[0];
    uint32_t serverTime = (uint32_t)p[1] | ((uint32_t)p[2] << 8) | ((uint32_t)p[3] << 16) | ((uint32_t)p[4] << 24);
    uint32_t now = millis();
    uint32_t rtt = now - handshakeSentMs;
    // NTP-style: assume the server stamped its time halfway through the round trip.
    // Caveat: the first packet through the tunnel can wait a long time before the
    // server sees it, which makes the trip lopsided and this estimate off by up to
    // about rtt/2. Good enough to order events; not a precision clock.
    clockOffset = (int32_t)((serverTime + rtt / 2) - now);
    handshakeDone = true;
    heartbeatsUnacked = 0;
    backoffMs = BACKOFF_MIN_MS;
    lastSampleMs = now;
    // serverTime = ms since the server STARTED. Right after a server restart, the first
    // handshake's serverTime is exactly how long the ESP32 took to come back once the
    // server was available again (the part the ESP32 controls: backoff + connect + handshake).
    Serial.printf("HANDSHAKE_ACK: session %u, server time %lu ms, %lu ms after connect, RTT %lu ms, clock offset %ld ms\n",
                  (unsigned)sessionId, (unsigned long)serverTime, (unsigned long)(now - connectedAtMs),
                  (unsigned long)rtt, (long)clockOffset);
    if (recovering) {
      Serial.printf("Link recovered: %lu ms since the loss was noticed (includes any time the server was down)\n",
                    (unsigned long)(now - linkLostAtMs));
      recovering = false;
    }
    if (outageEndMs != 0) {
      Serial.printf("[DEBUG] Total recovery time since WiFi was restored: %lu ms\n", (unsigned long)(now - outageEndMs));
      outageEndMs = 0;
    }
  } else if (type == PKT_HEARTBEAT_ACK) {
    heartbeatsUnacked = 0;
  } else if (type == PKT_ACTUATE) {
    uint8_t node = p[0], command = p[1], duration = p[2];
    if (node != NODE_ID) {
      Serial.printf("ACTUATE for node %u ignored (we are node %u)\n", (unsigned)node, (unsigned)NODE_ID);
    } else if (command == 0x01) {
      digitalWrite(ACTUATOR_PIN, HIGH);
      actuatorOn = true;
      actuatorOffAtMs = duration ? millis() + duration : 0;   // 0 ms = stay on until stopped
      Serial.printf("ACTUATE: vibrate for %u ms\n", (unsigned)duration);
    } else {
      digitalWrite(ACTUATOR_PIN, LOW);
      actuatorOn = false;
      Serial.println("ACTUATE: stop");
    }
  } else if (type == PKT_DISCONNECT) {
    Serial.println("Server sent DISCONNECT");
    client.stop();
  }
}

// Reassembles packets from the byte stream one byte at a time: a packet can
// arrive split across reads or glued to the next one.
void feedByte(uint8_t b) {
  if (rxLen == 0) {
    if (b == PKT_START) rxBuf[rxLen++] = b;
    return;
  }
  if (rxLen == 1) {
    if (incomingLength(b) != 0) {
      rxBuf[rxLen++] = b;
    } else if (b == PKT_START) {
      rxBuf[0] = PKT_START; rxLen = 1;     // that was really a new start byte
    } else {
      rxLen = 0;
    }
    return;
  }
  rxBuf[rxLen++] = b;
  uint8_t total = incomingLength(rxBuf[1]);
  if (rxLen == total) {
    bool good = (b == PKT_END) && (xorChecksum(rxBuf + 1, total - 3) == rxBuf[total - 2]);
    if (good) onPacket(rxBuf[1], rxBuf + 2);
    else Serial.println("Dropped a corrupt packet from the server");
    rxLen = 0;
  }
}

void handleServerBytes() {
  while (client.available()) {
    int b = client.read();
    if (b < 0) break;
    feedByte((uint8_t)b);
  }
}

void updateActuator() {
  if (actuatorOn && actuatorOffAtMs != 0 && (int32_t)(millis() - actuatorOffAtMs) >= 0) {
    digitalWrite(ACTUATOR_PIN, LOW);
    actuatorOn = false;
  }
}

// Debug helper: type 'w' to simulate the ESP32 leaving WiFi range for a while.
void simulateWifiOutage(uint32_t durationMs) {
  Serial.printf("[DEBUG] Simulating WiFi outage for %lu ms...\n", (unsigned long)durationMs);
  client.stop();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  delay(durationMs);
  WiFi.mode(WIFI_STA);
  outageEndMs = millis();
  Serial.println("[DEBUG] Outage over - normal recovery takes it from here.");
}

void handleSerialCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'w' || c == 'W') {
      simulateWifiOutage(15000);
    } else if (c == 'i' || c == 'I') {
      streaming = false;
      maxSpeed = false;
      Serial.println("[MODE] idle: heartbeats only");
    } else if (c == 's' || c == 'S') {
      streaming = true;
      maxSpeed = false;
      Serial.println("[MODE] streaming at 100 Hz");
    } else if (c == 'm' || c == 'M') {
      streaming = true;
      maxSpeed = true;
      Serial.println("[MODE] MAX SPEED: batches of packets, no pacing ('s' to go back)");
    }
  }
}

// Applies the TLS mode. Called before every connect so nothing depends on state
// surviving a client.stop().
void configureTls() {
#if TLS_MODE == 1
  client.setInsecure();
#elif TLS_MODE == 2
  client.setCACert(SERVER_CERT);
#endif
}

// Brings up WiFi if needed, then a TCP connection, then sends the HANDSHAKE.
void ensureConnected() {
  if (WiFi.status() != WL_CONNECTED) {
    if (sessionActive) markLinkLost();
    client.stop();
    handshakeDone = false;
    uint32_t wifiStart = millis();
    Serial.println("WiFi link is down, reconnecting WiFi...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED && millis() - wifiStart < 8000) {
      delay(100);
    }
    Serial.printf("WiFi reconnect took %lu ms, status=%d\n",
                  (unsigned long)(millis() - wifiStart), (int)WiFi.status());
    WiFi.setSleep(false);   // may not survive a disconnect
    if (WiFi.status() != WL_CONNECTED) return;
  }

  while (!client.connected()) {
    client.stop();

    // A connection just ended. If it never completed the handshake it was only the
    // tunnel accepting us with nothing behind it, so back off instead of hammering.
    if (sessionActive) {
      markLinkLost();
      if (!handshakeDone) {
        Serial.printf("Previous connection never got a HANDSHAKE_ACK - backing off %lu ms\n", (unsigned long)backoffMs);
        delay(backoffMs);
        backoffMs = (backoffMs * 2 > BACKOFF_MAX_MS) ? BACKOFF_MAX_MS : backoffMs * 2;
      } else {
        backoffMs = BACKOFF_MIN_MS;
      }
      sessionActive = false;
    }
    handshakeDone = false;

    configureTls();
    uint32_t attemptStart = millis();
    bool ok = client.connect(SERVER_IP, SERVER_PORT);
#if TLS_MODE == 0
    Serial.printf("TCP connect took %lu ms, success=%d\n", (unsigned long)(millis() - attemptStart), (int)ok);
#else
    Serial.printf("TCP+TLS connect took %lu ms (includes the TLS handshake), success=%d\n",
                  (unsigned long)(millis() - attemptStart), (int)ok);
    if (!ok) {
      char why[100];
      why[0] = 0;
      client.lastError(why, sizeof why);      // the actual mbedTLS reason, if any
      Serial.printf("TLS connect failed: %s\n", why[0] ? why : "(no detail)");
    }
#endif
    if (ok) {
      client.setNoDelay(true);
      sessionActive = true;
      rxLen = 0;
      heartbeatsUnacked = 0;
      connectedAtMs = millis();
      Serial.println("TCP connected, sending HANDSHAKE");
      if (!sendHandshake()) {
        Serial.println("HANDSHAKE write failed");
        client.stop();
        continue;
      }
      return;
    }
    delay(backoffMs);
    backoffMs = (backoffMs * 2 > BACKOFF_MAX_MS) ? BACKOFF_MAX_MS : backoffMs * 2;
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  // State the TLS mode in the log itself: a working mode-1 and mode-2 session look identical otherwise.
#if TLS_MODE == 0
  Serial.println("[TLS] mode 0: plain TCP, NOT encrypted");
#elif TLS_MODE == 1
  Serial.println("[TLS] mode 1: encrypted, server certificate NOT verified");
#else
  Serial.println("[TLS] mode 2: encrypted, only the pinned server certificate is trusted");
#endif
  pinMode(ACTUATOR_PIN, OUTPUT);
  digitalWrite(ACTUATOR_PIN, LOW);

  Serial.println("Connecting to WiFi...");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected!");
  WiFi.setSleep(false);   // WiFi power-save can stall the connection
  Serial.print("ESP32 IP address: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  handleSerialCommands();

  ensureConnected();
  if (!client.connected()) return;

  handleServerBytes();     // MUST keep reading: unread bytes pile up and stall the connection
  if (!client.connected()) return;   // e.g. the server just sent DISCONNECT and we closed: don't write to it
  updateActuator();

  uint32_t now = millis();

  // Until the server has acknowledged the handshake, send nothing else.
  if (!handshakeDone) {
    if (now - connectedAtMs > HANDSHAKE_TIMEOUT_MS) {
      Serial.println("No HANDSHAKE_ACK in time - dropping this connection");
      markLinkLost();
      client.stop();
    }
    delay(2);
    return;
  }

  if (maxSpeed) {
    if (!sendSensorBurst()) {
      Serial.println("SENSOR_DATA burst write failed - link is dead");
      markLinkLost();
      client.stop();
      return;
    }
    framesSent += BURST_PACKETS;
  } else if (streaming && now - lastSampleMs >= SAMPLE_PERIOD_MS) {
    lastSampleMs += SAMPLE_PERIOD_MS;
    if (now - lastSampleMs > 5 * SAMPLE_PERIOD_MS) lastSampleMs = now;   // fell behind: don't burst
    if (!sendSensorData()) {
      Serial.println("SENSOR_DATA write failed - link is dead");
      markLinkLost();
      client.stop();
      return;
    }
    framesSent++;
  }

  // Heartbeat only when we've been quiet for a second (idle / lobby).
  // Signed difference on purpose: lastPacketSentMs may be a moment LATER than `now`
  // (we may just have sent a frame above). With unsigned arithmetic that "negative"
  // gap wraps to a huge number and would fire a spurious heartbeat after every frame.
  if ((int32_t)(now - lastPacketSentMs) >= (int32_t)HEARTBEAT_INTERVAL_MS) {
    if (heartbeatsUnacked >= MAX_UNACKED_HEARTBEATS) {
      Serial.printf("%u heartbeats in a row unanswered - link is dead\n", (unsigned)heartbeatsUnacked);
      markLinkLost();
      client.stop();
      return;
    }
    if (!sendHeartbeat()) {
      Serial.println("HEARTBEAT write failed - link is dead");
      markLinkLost();
      client.stop();
      return;
    }
    heartbeatsUnacked++;
  }

  if (now - lastStatusMs >= 5000) {
    float fps = (framesSent - lastStatusFrames) * 1000.0f / (float)(now - lastStatusMs);
    lastStatusMs = now;
    lastStatusFrames = framesSent;
    Serial.printf("[status] session %u, %s, %lu frames sent (%.0f fps), %u heartbeat(s) unanswered\n",
                  (unsigned)sessionId, maxSpeed ? "MAX SPEED" : (streaming ? "streaming" : "idle"),
                  (unsigned long)framesSent, fps, (unsigned)heartbeatsUnacked);
  }

  if (maxSpeed) yield(); else delay(1);
}
