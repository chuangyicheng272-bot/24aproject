#pragma once

// Copy to local_config.h and fill in local network settings.
// local_config.h is ignored by Git.
static const char *WIFI_SSID = "YOUR_WIFI_SSID";
static const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
// Use the Flask computer's LAN IP, not localhost.
static const char *FLASK_URL = "http://192.168.1.100:5000/api/uwb/range";
