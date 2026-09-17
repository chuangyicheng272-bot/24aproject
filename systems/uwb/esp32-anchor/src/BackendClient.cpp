#include "BackendClient.h"

#include <HTTPClient.h>

BackendClient::BackendClient(const char* serverUrl) : serverUrl_(serverUrl) {}

bool BackendClient::postAnchorRanges(const String& jsonPayload) {
  Serial.println();
  Serial.println("Sending JSON payload:");
  Serial.println(jsonPayload);

  HTTPClient http;
  http.begin(serverUrl_);
  http.addHeader("Content-Type", "application/json");

  lastStatusCode_ = http.POST(jsonPayload);

  Serial.print("HTTP response code: ");
  Serial.println(lastStatusCode_);

  if (lastStatusCode_ > 0) {
    lastResponseBody_ = http.getString();
    Serial.println("Backend response:");
    Serial.println(lastResponseBody_);
  } else {
    lastResponseBody_ = http.errorToString(lastStatusCode_);
    Serial.print("HTTP POST failed: ");
    Serial.println(lastResponseBody_);
  }

  http.end();
  return lastStatusCode_ >= 200 && lastStatusCode_ < 300;
}

int BackendClient::lastStatusCode() const {
  return lastStatusCode_;
}

String BackendClient::lastResponseBody() const {
  return lastResponseBody_;
}
