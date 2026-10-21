#pragma once
#include <Arduino.h>
// Edit BOTH copies. Same hotspot credentials, and the two test-board STA MACs.
const bool SIMULATED_SENSORS = true; // true for bare boards; no MPU or motor required
const uint8_t PLAYER_ID = 1;        // gateway packet player identity: 1 or 2
const char *WIFI_SSID = "LYS8700";
const char *WIFI_PASSWORD = "20031123";
const char *ULTRA96_TUNNEL_HOST = "192.168.137.1";
const uint16_t ULTRA96_TUNNEL_PORT = 8888;
// Replace with YOUR boards, not the hardware group's board addresses.
const uint8_t LEFT_MAC[6]  = {0x38, 0x18, 0x2B, 0x18, 0x93, 0xFC};
const uint8_t RIGHT_MAC[6] = {0x38, 0x18, 0x2B, 0x18, 0x2D, 0x54};
