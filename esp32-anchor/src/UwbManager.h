#pragma once

#include <Arduino.h>

struct UwbLocationData {
  unsigned long sequenceId;
  String anchorId;
  unsigned long timestamp;
  String beltId;
  int distanceMm;
};

class UwbManager {
 public:
  void begin();
  bool readLocation(UwbLocationData& outData);
};
