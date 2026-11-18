#pragma once
#include <Arduino.h>
// Edit BOTH copies. Same hotspot credentials, and the two test-board STA MACs.
const bool SIMULATED_SENSORS = false; // true for bare boards; no MPU or motor required
#define PLAYER_ID 1  // Set to 2 for P2 in both sketch configurations.
const char *WIFI_SSID = "LYS8700";
const char *WIFI_PASSWORD = "20031123";
const char *ULTRA96_TUNNEL_HOST = "192.168.137.1";
const uint16_t ULTRA96_TUNNEL_PORT = 8888;
// Replace with YOUR boards, not the hardware group's board addresses.
#if PLAYER_ID == 1
const uint8_t LEFT_MAC[6]  = {0x38, 0x18, 0x2B, 0x13, 0x04, 0x6C};
const uint8_t RIGHT_MAC[6] = {0x6C, 0xC8, 0x40, 0x7C, 0xB3, 0x4C};
#elif PLAYER_ID == 2
const uint8_t LEFT_MAC[6]  = {0x6C, 0xC8, 0x40, 0x45, 0x40, 0xD8};
const uint8_t RIGHT_MAC[6] = {0x70, 0x4B, 0xCA, 0xE5, 0x18, 0xC4};
#else
#error "PLAYER_ID must be 1 or 2"
#endif
