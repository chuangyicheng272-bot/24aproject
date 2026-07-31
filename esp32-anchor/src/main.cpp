#include <Arduino.h>

#include "BackendClient.h"
#include "PayloadBuilder.h"
#include "UwbManager.h"
#include "WiFiManager.h"
#include "config.h"

WiFiManager wifiManager(WIFI_SSID, WIFI_PASSWORD, WIFI_CONNECT_TIMEOUT_MS);
BackendClient backendClient(SERVER_URL);
UwbManager uwbManager;

unsigned long lastSendTime = 0;

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("ESP32-S3 UWB Anchor MVP");
  Serial.println("DW3000 is not used yet. UwbManager returns mock data.");

  wifiManager.begin();
  uwbManager.begin();
}

void loop() {
  unsigned long now = millis();
  if (now - lastSendTime < SEND_INTERVAL_MS) {
    return;
  }
  lastSendTime = now;

  if (!wifiManager.ensureConnected()) {
    Serial.println("Skip sending because Wi-Fi is not connected");
    return;
  }

  UwbLocationData locationData;
  if (!uwbManager.readLocation(locationData)) {
    Serial.println("No UWB location data available");
    return;
  }

  String payload = PayloadBuilder::buildLocationJson(locationData);

  backendClient.postAnchorRanges(payload);
}
