#include "UwbManager.h"

#include "config.h"

void UwbManager::begin() {
  Serial.println("UwbManager started in mock mode");
}

bool UwbManager::readLocation(UwbLocationData& outData) {
  // MVP mock data. Replace this method with DW3000 ranging/location data later.
  // Test value only. All four anchors in one ranging cycle must receive the
  // same sequence_id from the Tag; anchors must not generate separate IDs.
  outData.sequenceId = SEQUENCE_ID;
  outData.anchorId = ANCHOR_ID;
  outData.timestamp = 1781943343;
  outData.beltId = BELT_ID;
  outData.distanceMm = 1820;
  return true;
}
