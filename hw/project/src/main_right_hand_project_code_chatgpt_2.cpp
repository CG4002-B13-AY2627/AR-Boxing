#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>

#define LEFT_NODE_ID 0x01
#define RIGHT_NODE_ID 0x02
#define ESP_SENSOR_MSG 0x01
#define SENSOR_PACKET_TYPE 0x02
#define ACTUATE_PACKET_TYPE 0x10

// remember to change to 0x02 when flashing Player 2.
#define PLAYER_ID 0x01

const uint8_t MPU_ADDR=0x68;
const int MOTOR_PIN=25;
const uint8_t MOTOR_PWM=165;            // ~70%; tune as needed
const uint32_t SAMPLE_PERIOD_US=10000;   // 100 Hz

// remember to update these
const char *WIFI_SSID="SHAO-XPS13 1090";
const char *WIFI_PASSWORD="33333333";
IPAddress LAPTOP_IP(192,168,137,1);
const uint16_t LAPTOP_PORT=5000;

// change this to left FireBeetle STA MAC.
uint8_t LEFT_MAC[]={0x38,0x18,0x2B,0x13,0x04,0x6C};

WiFiClient tcp;

struct __attribute__((packed)) SensorMsg {
  uint8_t type, nodeID;
  uint32_t timestamp;
  int16_t ax,ay,az,gx,gy,gz;
};

struct __attribute__((packed)) ActuateMsg {
  uint8_t type,nodeID,command,duration;
};

// Exact 22-byte TCP sensor packet.
struct __attribute__((packed)) SensorPacket {
  uint8_t header;       // 0xAA
  uint8_t packetType;   // 0x02
  uint8_t playerID;
  uint8_t nodeID;
  uint32_t timestamp;
  int16_t ax,ay,az;
  int16_t gx,gy,gz;
  uint8_t checksum;
  uint8_t footer;       // 0x55
};
static_assert(sizeof(SensorPacket)==22,"SensorPacket must be 22 bytes");

portMUX_TYPE leftMux=portMUX_INITIALIZER_UNLOCKED;
SensorMsg pendingLeft{};
volatile bool pendingLeftReady=false;

bool motorActive=false;
uint32_t motorStart=0;
uint8_t motorDuration=0;

bool mpuWrite(uint8_t reg,uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg); Wire.write(val);
  return Wire.endTransmission()==0;
}

bool initMPU() {
  return mpuWrite(0x6B,0x00) &&
         mpuWrite(0x1B,0x18) && // +/-2000 dps
         mpuWrite(0x1C,0x18) && // +/-16 g
         mpuWrite(0x1A,0x03) && // DLPF
         mpuWrite(0x19,0x09);   // 100 Hz
}

bool readMPU(int16_t &ax,int16_t &ay,int16_t &az,
             int16_t &gx,int16_t &gy,int16_t &gz) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  if (Wire.endTransmission(false)!=0) return false;
  if (Wire.requestFrom(MPU_ADDR,(uint8_t)14,(uint8_t)true)!=14) return false;
  ax=(int16_t)((Wire.read()<<8)|Wire.read());
  ay=(int16_t)((Wire.read()<<8)|Wire.read());
  az=(int16_t)((Wire.read()<<8)|Wire.read());
  Wire.read(); Wire.read();
  gx=(int16_t)((Wire.read()<<8)|Wire.read());
  gy=(int16_t)((Wire.read()<<8)|Wire.read());
  gz=(int16_t)((Wire.read()<<8)|Wire.read());
  return true;
}

void stopMotor(){ analogWrite(MOTOR_PIN,0); motorActive=false; }
void startMotor(uint8_t d){
  if(d==0){stopMotor();return;}
  analogWrite(MOTOR_PIN,MOTOR_PWM);
  motorActive=true; motorStart=millis(); motorDuration=d;
}
void updateMotor(){
  if(motorActive && (uint32_t)(millis()-motorStart)>=motorDuration) stopMotor();
}

uint8_t checksum22(const SensorPacket &p) {
  const uint8_t *b=(const uint8_t*)&p;
  uint8_t c=0;
  for(uint8_t i=1;i<=19;i++) c^=b[i];
  return c;
}

SensorPacket makePacket(uint8_t node,uint32_t ts,
                        int16_t ax,int16_t ay,int16_t az,
                        int16_t gx,int16_t gy,int16_t gz) {
  SensorPacket p{};
  p.header=0xAA; p.packetType=SENSOR_PACKET_TYPE;
  p.playerID=PLAYER_ID; p.nodeID=node; p.timestamp=ts;
  p.ax=ax;p.ay=ay;p.az=az;p.gx=gx;p.gy=gy;p.gz=gz;
  p.checksum=checksum22(p); p.footer=0x55;
  return p;
}

void sendPacket(const SensorPacket &p) {
  if(tcp.connected()) tcp.write((const uint8_t*)&p,sizeof(p));
}

// Keep callback short: hand sample to loop(), don't perform TCP I/O here.
void onReceive(const uint8_t*,const uint8_t *data,int len) {
  if(len!=sizeof(SensorMsg)) return;
  SensorMsg m; memcpy(&m,data,sizeof(m));
  if(m.type!=ESP_SENSOR_MSG || m.nodeID!=LEFT_NODE_ID) return;
  portENTER_CRITICAL(&leftMux);
  pendingLeft=m; pendingLeftReady=true;
  portEXIT_CRITICAL(&leftMux);
}

bool takeLeft(SensorMsg &m) {
  bool ok;
  portENTER_CRITICAL(&leftMux);
  ok=pendingLeftReady;
  if(ok){m=pendingLeft;pendingLeftReady=false;}
  portEXIT_CRITICAL(&leftMux);
  return ok;
}

uint8_t actuateChecksum(uint8_t type,uint8_t node,uint8_t cmd,uint8_t dur) {
  return type^node^cmd^dur;
}

void processActuate(uint8_t node,uint8_t cmd,uint8_t dur) {
  if(node==RIGHT_NODE_ID) {
    if(cmd==0x01) startMotor(dur); else stopMotor();
  } else if(node==LEFT_NODE_ID) {
    ActuateMsg m{ACTUATE_PACKET_TYPE,LEFT_NODE_ID,cmd,dur};
    esp_now_send(LEFT_MAC,(uint8_t*)&m,sizeof(m));
  }
}

// Parse 7-byte downlink packets from the persistent TCP byte stream:
// AA 10 Node Command Duration Checksum 55
void readActuate() {
  static uint8_t p[7];
  static uint8_t pos=0;

  while(tcp.connected() && tcp.available()) {
    uint8_t b=(uint8_t)tcp.read();
    if(pos==0) {
      if(b==0xAA) p[pos++]=b;
      continue;
    }
    p[pos++]=b;
    if(pos<7) continue;

    bool valid =
      p[0]==0xAA && p[1]==ACTUATE_PACKET_TYPE && p[6]==0x55 &&
      (p[2]==LEFT_NODE_ID || p[2]==RIGHT_NODE_ID) &&
      (p[3]==0x00 || p[3]==0x01) &&
      p[5]==actuateChecksum(p[1],p[2],p[3],p[4]);

    if(valid) {
      processActuate(p[2],p[3],p[4]);
      pos=0;
    } else {
      // Retain a trailing 0xAA as a possible next header.
      if(p[6]==0xAA){p[0]=0xAA;pos=1;}
      else pos=0;
    }
  }
}

void maintainWiFi() {
  //for debugging
  //Serial.println("WiFi maintained");
  static uint32_t last=0;
  if(WiFi.status()==WL_CONNECTED) return;
  if((uint32_t)(millis()-last)<3000) return;
  last=millis();
  WiFi.disconnect();
  //for debugging
  Serial.println("WiFi disconnected");
  WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
}

void maintainTCP() {
    static uint32_t last = 0;

    if (WiFi.status() != WL_CONNECTED) {
        return;
    }

    if (tcp.connected()) {
        return;
    }

    if ((uint32_t)(millis() - last) < 2000) {
        return;
    }

    last = millis();

    Serial.print("Trying TCP connection to ");
    Serial.print(LAPTOP_IP);
    Serial.print(":");
    Serial.println(LAPTOP_PORT);

    tcp.stop();

    if (tcp.connect(LAPTOP_IP, LAPTOP_PORT)) {
        Serial.println("TCP CONNECTED!");
    }
    else {
        Serial.println("TCP connection FAILED");
    }
}

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_PIN,OUTPUT); stopMotor();

  Wire.begin();
  Wire.setClock(400000);
  if(!initMPU()){
    Serial.println("MPU6050 init failed");
    while(true) delay(1000);
  }

  WiFi.mode(WIFI_STA);
  // WiFi.begin(WIFI_SSID,WIFI_PASSWORD); //comented out for debugging
  // while(WiFi.status()!=WL_CONNECTED){delay(250);Serial.print(".");}
  // Serial.println();
  // Serial.print("RIGHT IP: ");Serial.println(WiFi.localIP());
  Serial.print("RIGHT STA MAC: ");Serial.println(WiFi.macAddress());

  if(esp_now_init()!=ESP_OK){
    Serial.println("ESP-NOW init failed");
    while(true) delay(1000);
  }
  esp_now_register_recv_cb(onReceive);

  esp_now_peer_info_t peer={};
  memcpy(peer.peer_addr,LEFT_MAC,6);
  peer.channel=0; peer.encrypt=false;
  if(esp_now_add_peer(&peer)!=ESP_OK){
    Serial.println("Could not add LEFT peer");
    while(true) delay(1000);
  }
}

void loop() {
  updateMotor();
  //maintainWiFi();//commented for debugging
  //maintainTCP(); //commented for debugging
  if(tcp.connected()) readActuate();

  SensorMsg l;
  // if(takeLeft(l))
  //   sendPacket(makePacket(LEFT_NODE_ID,l.timestamp,
  //                         l.ax,l.ay,l.az,l.gx,l.gy,l.gz)); //commted out for debugging

  //temp code for debugging
  if(takeLeft(l)) {
    static uint32_t previousTimestamp = 0;
    if(previousTimestamp != 0) {
      uint32_t timestampGap = l.timestamp - previousTimestamp;
      if(timestampGap > 10) {
        uint32_t lostPackets = (timestampGap / 10) - 1;
        Serial.print("ALERT: packets lost. Gap=");
        Serial.print(timestampGap);
        Serial.print(" ms, estimated lost=");
        Serial.println(lostPackets);
      }
    }
    previousTimestamp = l.timestamp;

    Serial.print("ESP-NOW LEFT sample: timestamp=");
    Serial.print(l.timestamp);
    Serial.print(" ax="); Serial.print(l.ax);
    Serial.print(" ay="); Serial.print(l.ay);
    Serial.print(" az="); Serial.print(l.az);
    Serial.print(" gx="); Serial.print(l.gx);
    Serial.print(" gy="); Serial.print(l.gy);
    Serial.print(" gz="); Serial.println(l.gz);
  }


  static uint32_t nextUs=micros();
  uint32_t nowUs=micros();
  if((int32_t)(nowUs-nextUs)>=0) {
    nextUs+=SAMPLE_PERIOD_US;
    if((int32_t)(nowUs-nextUs)>=(int32_t)SAMPLE_PERIOD_US) //every 10000us = 10ms
      nextUs=nowUs+SAMPLE_PERIOD_US;

    int16_t ax,ay,az,gx,gy,gz;
    uint32_t ts=millis();
    // if(readMPU(ax,ay,az,gx,gy,gz))
    //   sendPacket(makePacket(RIGHT_NODE_ID,ts,ax,ay,az,gx,gy,gz)); //commented out for debugging
    //added for debugging
    if(readMPU(ax,ay,az,gx,gy,gz)) {
      // Right-hand samples are intentionally not sent to TCP during this test.
      (void)ts;
      (void)ax; (void)ay; (void)az;
      (void)gx; (void)gy; (void)gz;
    }
  }
}
