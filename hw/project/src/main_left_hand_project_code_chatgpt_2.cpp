#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>

#define LEFT_NODE_ID 0x01
#define SENSOR_MSG 0x01
#define ACTUATE_MSG 0x10

const uint8_t MPU_ADDR = 0x68;
const int MOTOR_PIN = 25;
const uint8_t MOTOR_PWM = 165;          // ~70% vibration motor strength
const uint32_t SAMPLE_PERIOD_US = 10000; // 100 Hz

// change this to right FireBeetle STA MAC.
uint8_t RIGHT_MAC[] = {0x6C, 0xC8, 0x40, 0x7C, 0xB3, 0x4C};

volatile uint32_t sendSuccess = 0;
volatile uint32_t sendFailed = 0;

struct __attribute__((packed)) SensorMsg {
  uint8_t type;
  uint8_t nodeID;
  uint32_t timestamp;
  int16_t ax, ay, az;
  int16_t gx, gy, gz;
};

struct __attribute__((packed)) ActuateMsg {
  uint8_t type;
  uint8_t nodeID;
  uint8_t command;
  uint8_t duration;
};

bool motorActive = false;
uint32_t motorStart = 0;
uint8_t motorDuration = 0;

bool mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg); Wire.write(val);
  return Wire.endTransmission() == 0;
}

bool initMPU() {
  return mpuWrite(0x6B,0x00) && // wake
         mpuWrite(0x1B,0x00) && // gyro +/-250 dps
         mpuWrite(0x1C,0x00) && // accel +/-2 g
         mpuWrite(0x1A,0x03) && // DLPF
         mpuWrite(0x19,0x09);   // 100 Hz
}

bool readMPU(int16_t &ax,int16_t &ay,int16_t &az,
             int16_t &gx,int16_t &gy,int16_t &gz) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(MPU_ADDR,(uint8_t)14,(uint8_t)true) != 14) return false;
  ax=(int16_t)((Wire.read()<<8)|Wire.read());
  ay=(int16_t)((Wire.read()<<8)|Wire.read());
  az=(int16_t)((Wire.read()<<8)|Wire.read());
  Wire.read(); Wire.read(); // skip temperature
  gx=(int16_t)((Wire.read()<<8)|Wire.read());
  gy=(int16_t)((Wire.read()<<8)|Wire.read());
  gz=(int16_t)((Wire.read()<<8)|Wire.read());
  return true;
}

void stopMotor() {
  analogWrite(MOTOR_PIN,0);
  motorActive=false;
}

void startMotor(uint8_t duration) {
  if (duration==0) { stopMotor(); return; }
  analogWrite(MOTOR_PIN,MOTOR_PWM);
  motorActive=true;
  motorStart=millis();
  motorDuration=duration;
}

void updateMotor() {
  if (motorActive && (uint32_t)(millis()-motorStart)>=motorDuration)
    stopMotor();
}

// Arduino-ESP32 2.x callback signature.
void onReceive(const uint8_t*, const uint8_t *data, int len) {
  if (len != sizeof(ActuateMsg)) return;
  ActuateMsg m; memcpy(&m,data,sizeof(m));
  if (m.type!=ACTUATE_MSG || m.nodeID!=LEFT_NODE_ID) return;
  if (m.command==0x01) startMotor(m.duration);
  else if (m.command==0x00) stopMotor();
}

//count number of failed and successful sends
void onSent(const uint8_t *, esp_now_send_status_t status) {
  if (status == ESP_NOW_SEND_SUCCESS) {
    sendSuccess++;
  } else {
    sendFailed++;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_PIN,OUTPUT);
  stopMotor();

  Wire.begin(); // SDA=21, SCL=22 on typical FireBeetle ESP32
  Wire.setClock(400000);
  if (!initMPU()) {
    Serial.println("MPU6050 init failed");
    while(true) delay(1000);
  }

  WiFi.mode(WIFI_STA);
  Serial.print("LEFT STA MAC: "); Serial.println(WiFi.macAddress());

  if (esp_now_init()!=ESP_OK) {
    Serial.println("ESP-NOW init failed");
    while(true) delay(1000);
  }
  esp_now_register_recv_cb(onReceive);
  esp_now_register_send_cb(onSent);

  esp_now_peer_info_t peer={};
  memcpy(peer.peer_addr,RIGHT_MAC,6);
  peer.channel=0;
  peer.encrypt=false;
  if (esp_now_add_peer(&peer)!=ESP_OK) {
    Serial.println("Could not add RIGHT peer");
    while(true) delay(1000);
  }
}

void loop() {
  updateMotor();

  // print send success/failure counts every 1 second //for debugging
  static uint32_t lastSendReport = 0;
  if ((uint32_t)(millis() - lastSendReport) >= 1000) {
    lastSendReport = millis();
    Serial.print("Send success: ");
    Serial.print(sendSuccess);
    Serial.print(" | Send failures: ");
    Serial.println(sendFailed);
  }

  static uint32_t nextUs=micros();
  uint32_t nowUs=micros();
  if ((int32_t)(nowUs-nextUs)>=0) {
    nextUs += SAMPLE_PERIOD_US;
    if ((int32_t)(nowUs-nextUs)>=(int32_t)SAMPLE_PERIOD_US)
      nextUs=nowUs+SAMPLE_PERIOD_US;

    int16_t ax, ay, az;
    int16_t gx, gy, gz;

    if (readMPU(ax, ay, az, gx, gy, gz)) {

        SensorMsg m{};

        m.type = SENSOR_MSG;
        m.nodeID = LEFT_NODE_ID;
        m.timestamp = millis();

        m.ax = ax;
        m.ay = ay;
        m.az = az;

        m.gx = gx;
        m.gy = gy;
        m.gz = gz;

        esp_now_send(
            RIGHT_MAC,
            reinterpret_cast<uint8_t *>(&m),
            sizeof(m)
        );
    }
  }
}
