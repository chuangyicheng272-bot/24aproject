#include "PayloadBuilder.h"

String PayloadBuilder::buildLocationJson(const UwbLocationData& data) {
  String payload = "{";
  payload += "\"sequence_id\":" + String(data.sequenceId) + ",";
  payload += "\"anchor_id\":\"" + data.anchorId + "\",";
  payload += "\"timestamp\":" + String(data.timestamp) + ",";
  payload += "\"detected_belts\":{\"" + data.beltId + "\":{";
  payload += "\"distance_mm\":" + String(data.distanceMm);
  payload += "}}";
  payload += "}";
  return payload;
}
