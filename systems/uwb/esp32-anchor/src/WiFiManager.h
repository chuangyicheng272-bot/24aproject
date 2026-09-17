#pragma once

#include <Arduino.h>

class WiFiManager {
 public:
  WiFiManager(const char* ssid, const char* password, unsigned long timeoutMs);

  bool begin();
  bool ensureConnected();
  bool isConnected() const;

 private:
  const char* ssid_;
  const char* password_;
  unsigned long timeoutMs_;
};
