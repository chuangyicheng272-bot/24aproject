#pragma once

// Change these values before uploading to ESP32-S3.
static const char* WIFI_SSID = "YOUR_WIFI_SSID";
static const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Change this to your FastAPI backend computer IP.
// Example: http://192.168.1.20:8000/api/anchor/ranges
// Do not use localhost or 127.0.0.1 on ESP32.
static const char* SERVER_URL = "http://192.168.1.20:8000/api/anchor/ranges";

// Fixed value for one integration-test round only.
// Anchor1 through Anchor4 in the same complete ranging cycle MUST use the
// same sequence_id. Production hardware will obtain it from the Tag packet.
static const unsigned long SEQUENCE_ID = 1024;
static const char* ANCHOR_ID = "Anchor1";
static const char* BELT_ID = "BELT-001";

static const unsigned long SEND_INTERVAL_MS = 1000;
static const unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;
