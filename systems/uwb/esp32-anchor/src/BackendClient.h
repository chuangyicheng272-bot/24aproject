#pragma once

#include <Arduino.h>

class BackendClient {
 public:
  explicit BackendClient(const char* serverUrl);

  bool postAnchorRanges(const String& jsonPayload);
  int lastStatusCode() const;
  String lastResponseBody() const;

 private:
  const char* serverUrl_;
  int lastStatusCode_ = 0;
  String lastResponseBody_;
};
