#include "WiFiManager.h"

#include <WiFi.h>

WiFiManager::WiFiManager(
    const char* ssid,
    const char* password,
    unsigned long timeoutMs)
    : ssid_(ssid), password_(password), timeoutMs_(timeoutMs) {}

bool WiFiManager::begin() {
  Serial.print("Connecting Wi-Fi: ");
  Serial.println(ssid_);

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid_, password_);

  unsigned long startTime = millis();
  while (WiFi.status() != WL_CONNECTED &&
         millis() - startTime < timeoutMs_) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi connection failed");
    return false;
  }

  Serial.println("Wi-Fi connected");
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());
  return true;
}

bool WiFiManager::ensureConnected() {
  if (isConnected()) {
    return true;
  }

  Serial.println("Wi-Fi disconnected. Reconnecting...");
  return begin();
}

bool WiFiManager::isConnected() const {
  return WiFi.status() == WL_CONNECTED;
}
