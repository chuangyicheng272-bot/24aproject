#pragma once

#include <Arduino.h>

#include "UwbManager.h"

class PayloadBuilder {
 public:
  static String buildLocationJson(const UwbLocationData& data);
};
