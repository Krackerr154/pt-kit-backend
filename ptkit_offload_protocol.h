#ifndef PTKIT_OFFLOAD_PROTOCOL_H
#define PTKIT_OFFLOAD_PROTOCOL_H

/*
 * PT-Kit physical ESP32 <-> Uno control protocol, version 1.
 *
 * Frames are ASCII, newline-delimited by the caller, and have a CRC-8 suffix:
 *   V1:<TYPE>:<field>...:<CRC-8-hex>
 *
 * This header is deliberately dependency-light so the same parser can be tested
 * on the host and compiled by both Arduino targets. Temperatures are deci-degrees
 * Celsius and lux is an unsigned integer, keeping Uno frames compact and bounded.
 */

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace ptkit {

const size_t FRAME_MAX_CHARS = 64;  // Payload only; caller adds CRLF/LF.
const size_t BACKEND_COMMAND_MAX_CHARS = 160;  // ESP32-side public text command only.
const int32_t INVALID_DECI_C = -32768;

enum SensorFlags : uint8_t {
  SENSOR_IR_VALID = 0x01,
  SENSOR_TC_VALID = 0x02,
  SENSOR_LUX_VALID = 0x04,
  SENSOR_OVER_TEMP = 0x08,
  SENSOR_LINK_EXPIRED = 0x10,
};

enum FaultCode : uint8_t {
  FAULT_NONE = 0,
  FAULT_LINK_TIMEOUT = 1,
  FAULT_OVER_TEMPERATURE = 2,
  FAULT_SENSOR_INVALID = 3,
  FAULT_BAD_COMMAND = 4,
  FAULT_DISCOVERY_TIMEOUT = 5,
};

struct ArmPacket {
  uint16_t sequence;
  uint16_t maxTempDeciC;
};

struct OutputPacket {
  uint16_t sequence;
  uint8_t lampPwm;
  uint8_t fanPwm;
  uint16_t ttlMs;
  uint8_t stateCode;
};

struct SensorPacket {
  int32_t irDeciC;
  int32_t tcDeciC;
  uint32_t lux;
  uint32_t maxHardwareLux;
  uint8_t flags;
};

struct AckPacket {
  uint16_t sequence;
  uint8_t code;
};

struct LinkPausePacket {
  uint16_t lastOutputSequence;
  uint8_t lampPwm;
  uint8_t fanPwm;
};

struct CalibrationPacket {
  uint16_t sequence;
  uint8_t phase;  // 1=bare, 2=tape, 3=full
};

struct CalibrationResultPacket {
  uint8_t phase;
  uint32_t bareDeciLux;
  uint32_t tapedDeciLux;
  uint16_t attenuationPermille;
  uint32_t maxDeciLux;
};

inline unsigned char crc8(const char *text) {
  unsigned char crc = 0;
  if (!text) return crc;
  while (*text) {
    crc ^= static_cast<unsigned char>(*text++);
    for (uint8_t bit = 0; bit < 8; ++bit)
      crc = (crc & 0x80) ? static_cast<unsigned char>((crc << 1) ^ 0x07)
                          : static_cast<unsigned char>(crc << 1);
  }
  return crc;
}

inline char hexDigit(uint8_t value) {
  value &= 0x0F;
  return value < 10 ? static_cast<char>('0' + value)
                    : static_cast<char>('A' + value - 10);
}

inline int hexValue(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}

class FrameBuilder {
 public:
  FrameBuilder(char *out, size_t capacity) : out_(out), capacity_(capacity), length_(0), ok_(out && capacity) {
    if (ok_) out_[0] = '\0';
  }

  bool literal(const char *value) {
    if (!value) return fail();
    while (*value) {
      if (!push(*value++)) return false;
    }
    return true;
  }

  bool separator() { return push(':'); }

  bool unsignedValue(uint32_t value) {
    char reversed[11];
    uint8_t count = 0;
    do {
      reversed[count++] = static_cast<char>('0' + (value % 10U));
      value /= 10U;
    } while (value && count < sizeof(reversed));
    while (count) {
      if (!push(reversed[--count])) return false;
    }
    return true;
  }

  bool signedValue(int32_t value) {
    if (value < 0) {
      if (!push('-')) return false;
      // Avoid signed-min overflow by converting through a wider signed type.
      return unsignedValue(static_cast<uint32_t>(-(static_cast<int64_t>(value))));
    }
    return unsignedValue(static_cast<uint32_t>(value));
  }

  bool finish() {
    if (!ok_) return false;
    const uint8_t crc = crc8(out_);
    return separator() && push(hexDigit(crc >> 4)) && push(hexDigit(crc));
  }

  bool ok() const { return ok_; }

 private:
  bool push(char c) {
    if (!ok_ || length_ + 1 >= capacity_) return fail();
    out_[length_++] = c;
    out_[length_] = '\0';
    return true;
  }
  bool fail() { ok_ = false; return false; }

  char *out_;
  size_t capacity_;
  size_t length_;
  bool ok_;
};

inline bool parseUnsigned(const char *text, uint32_t &value, uint32_t maximum = 0xFFFFFFFFUL) {
  if (!text || !*text) return false;
  uint32_t result = 0;
  for (const char *p = text; *p; ++p) {
    if (*p < '0' || *p > '9') return false;
    const uint32_t digit = static_cast<uint32_t>(*p - '0');
    if (result > (maximum - digit) / 10U) return false;
    result = result * 10U + digit;
  }
  value = result;
  return true;
}

inline bool parseSigned(const char *text, int32_t &value) {
  if (!text || !*text) return false;
  bool negative = *text == '-';
  if (negative) ++text;
  uint32_t magnitude = 0;
  const uint32_t limit = negative ? 2147483648UL : 2147483647UL;
  if (!parseUnsigned(text, magnitude, limit)) return false;
  if (negative) {
    value = magnitude == 2147483648UL ? (-2147483647L - 1L)
                                      : -static_cast<int32_t>(magnitude);
  } else {
    value = static_cast<int32_t>(magnitude);
  }
  return true;
}

inline bool splitPayload(char *payload, char *fields[], uint8_t maximumFields, uint8_t &count) {
  if (!payload || !fields || !maximumFields) return false;
  count = 0;
  fields[count++] = payload;
  for (char *p = payload; *p; ++p) {
    if (*p == ':') {
      *p = '\0';
      if (count >= maximumFields) return false;
      fields[count++] = p + 1;
    }
  }
  return true;
}

inline bool verifiedPayload(const char *frame, char *payload, size_t payloadCapacity) {
  if (!frame || !payload || payloadCapacity < 6) return false;
  size_t length = strlen(frame);
  if (length < 6 || length >= payloadCapacity) return false;
  const char *suffix = frame + length - 3;
  if (*suffix != ':') return false;
  const int high = hexValue(suffix[1]);
  const int low = hexValue(suffix[2]);
  if (high < 0 || low < 0) return false;
  const size_t bodyLength = static_cast<size_t>(suffix - frame);
  if (bodyLength + 1 > payloadCapacity) return false;
  memcpy(payload, frame, bodyLength);
  payload[bodyLength] = '\0';
  return crc8(payload) == static_cast<uint8_t>((high << 4) | low);
}

inline bool validPrefix(char *fields[], uint8_t count, const char *type, uint8_t requiredCount) {
  return count == requiredCount && strcmp(fields[0], "V1") == 0 && strcmp(fields[1], type) == 0;
}

inline bool parseArm(const char *frame, ArmPacket &packet) {
  char payload[FRAME_MAX_CHARS];
  char *fields[5]; uint8_t count = 0; uint32_t sequence = 0, maximum = 0;
  if (!verifiedPayload(frame, payload, sizeof(payload)) || !splitPayload(payload, fields, 5, count) ||
      !validPrefix(fields, count, "A", 4) || !parseUnsigned(fields[2], sequence, 65535UL) ||
      !parseUnsigned(fields[3], maximum, 20000UL) || !maximum) return false;
  packet.sequence = static_cast<uint16_t>(sequence);
  packet.maxTempDeciC = static_cast<uint16_t>(maximum);
  return true;
}

inline bool parseOutput(const char *frame, OutputPacket &packet) {
  char payload[FRAME_MAX_CHARS];
  char *fields[8]; uint8_t count = 0;
  uint32_t sequence = 0, lamp = 0, fan = 0, ttl = 0, state = 0;
  if (!verifiedPayload(frame, payload, sizeof(payload)) || !splitPayload(payload, fields, 8, count) ||
      !validPrefix(fields, count, "O", 7) || !parseUnsigned(fields[2], sequence, 65535UL) ||
      !parseUnsigned(fields[3], lamp, 255UL) || !parseUnsigned(fields[4], fan, 255UL) ||
      !parseUnsigned(fields[5], ttl, 5000UL) || !parseUnsigned(fields[6], state, 15UL) || !ttl) return false;
  packet.sequence = static_cast<uint16_t>(sequence);
  packet.lampPwm = static_cast<uint8_t>(lamp);
  packet.fanPwm = static_cast<uint8_t>(fan);
  packet.ttlMs = static_cast<uint16_t>(ttl);
  packet.stateCode = static_cast<uint8_t>(state);
  return true;
}

inline bool parseStop(const char *frame, uint16_t &sequence) {
  char payload[FRAME_MAX_CHARS];
  char *fields[4]; uint8_t count = 0; uint32_t parsed = 0;
  if (!verifiedPayload(frame, payload, sizeof(payload)) || !splitPayload(payload, fields, 4, count) ||
      !validPrefix(fields, count, "X", 3) || !parseUnsigned(fields[2], parsed, 65535UL)) return false;
  sequence = static_cast<uint16_t>(parsed);
  return true;
}

inline bool parsePing(const char *frame, uint16_t &sequence) {
  char payload[FRAME_MAX_CHARS];
  char *fields[4]; uint8_t count = 0; uint32_t parsed = 0;
  if (!verifiedPayload(frame, payload, sizeof(payload)) || !splitPayload(payload, fields, 4, count) ||
      !validPrefix(fields, count, "P", 3) || !parseUnsigned(fields[2], parsed, 65535UL)) return false;
  sequence = static_cast<uint16_t>(parsed);
  return true;
}

inline bool parseCalibration(const char *frame, CalibrationPacket &packet) {
  char payload[FRAME_MAX_CHARS];
  char *fields[5]; uint8_t count = 0; uint32_t sequence = 0, phase = 0;
  if (!verifiedPayload(frame, payload, sizeof(payload)) || !splitPayload(payload, fields, 5, count) ||
      !validPrefix(fields, count, "C", 4) || !parseUnsigned(fields[2], sequence, 65535UL) ||
      !parseUnsigned(fields[3], phase, 3UL) || phase < 1) return false;
  packet.sequence = static_cast<uint16_t>(sequence);
  packet.phase = static_cast<uint8_t>(phase);
  return true;
}

inline bool parseSensor(const char *frame, SensorPacket &packet) {
  char payload[FRAME_MAX_CHARS];
  char *fields[8]; uint8_t count = 0;
  int32_t ir = 0, tc = 0; uint32_t lux = 0, maximum = 0, flags = 0;
  if (!verifiedPayload(frame, payload, sizeof(payload)) || !splitPayload(payload, fields, 8, count) ||
      !validPrefix(fields, count, "R", 7) || !parseSigned(fields[2], ir) || !parseSigned(fields[3], tc) ||
      !parseUnsigned(fields[4], lux) || !parseUnsigned(fields[5], maximum) ||
      !parseUnsigned(fields[6], flags, 255UL)) return false;
  packet.irDeciC = ir; packet.tcDeciC = tc; packet.lux = lux;
  packet.maxHardwareLux = maximum; packet.flags = static_cast<uint8_t>(flags);
  return true;
}

inline bool parseAck(const char *frame, AckPacket &packet) {
  char payload[FRAME_MAX_CHARS];
  char *fields[5]; uint8_t count = 0; uint32_t sequence = 0, code = 0;
  if (!verifiedPayload(frame, payload, sizeof(payload)) || !splitPayload(payload, fields, 5, count) ||
      !validPrefix(fields, count, "K", 4) || !parseUnsigned(fields[2], sequence, 65535UL) ||
      !parseUnsigned(fields[3], code, 255UL)) return false;
  packet.sequence = static_cast<uint16_t>(sequence);
  packet.code = static_cast<uint8_t>(code);
  return true;
}

inline bool parseLinkPause(const char *frame, LinkPausePacket &packet) {
  char payload[FRAME_MAX_CHARS];
  char *fields[6]; uint8_t count = 0;
  uint32_t sequence = 0, lamp = 0, fan = 0;
  if (!verifiedPayload(frame, payload, sizeof(payload)) || !splitPayload(payload, fields, 6, count) ||
      !validPrefix(fields, count, "L", 5) || !parseUnsigned(fields[2], sequence, 65535UL) ||
      !parseUnsigned(fields[3], lamp, 255UL) || !parseUnsigned(fields[4], fan, 255UL)) return false;
  packet.lastOutputSequence = static_cast<uint16_t>(sequence);
  packet.lampPwm = static_cast<uint8_t>(lamp);
  packet.fanPwm = static_cast<uint8_t>(fan);
  return true;
}

inline bool parseFault(const char *frame, uint8_t &fault) {
  char payload[FRAME_MAX_CHARS];
  char *fields[4]; uint8_t count = 0; uint32_t value = 0;
  if (!verifiedPayload(frame, payload, sizeof(payload)) || !splitPayload(payload, fields, 4, count) ||
      !validPrefix(fields, count, "F", 3) || !parseUnsigned(fields[2], value, 255UL)) return false;
  fault = static_cast<uint8_t>(value);
  return true;
}

inline bool parseCalibrationResult(const char *frame, CalibrationResultPacket &packet) {
  char payload[FRAME_MAX_CHARS];
  char *fields[8]; uint8_t count = 0;
  uint32_t phase = 0, bare = 0, taped = 0, attenuation = 0, maximum = 0;
  if (!verifiedPayload(frame, payload, sizeof(payload)) || !splitPayload(payload, fields, 8, count) ||
      !validPrefix(fields, count, "Q", 7) || !parseUnsigned(fields[2], phase, 3UL) || phase < 1 ||
      !parseUnsigned(fields[3], bare) || !parseUnsigned(fields[4], taped) ||
      !parseUnsigned(fields[5], attenuation, 65535UL) || !parseUnsigned(fields[6], maximum)) return false;
  packet.phase = static_cast<uint8_t>(phase);
  packet.bareDeciLux = bare;
  packet.tapedDeciLux = taped;
  packet.attenuationPermille = static_cast<uint16_t>(attenuation);
  packet.maxDeciLux = maximum;
  return true;
}

inline bool frameArm(char *out, size_t capacity, uint16_t sequence, uint16_t maxTempDeciC) {
  FrameBuilder b(out, capacity);
  return b.literal("V1") && b.separator() && b.literal("A") && b.separator() && b.unsignedValue(sequence) &&
         b.separator() && b.unsignedValue(maxTempDeciC) && b.finish();
}

inline bool frameOutput(char *out, size_t capacity, uint16_t sequence, uint8_t lampPwm,
                        uint8_t fanPwm, uint16_t ttlMs, uint8_t stateCode) {
  FrameBuilder b(out, capacity);
  return b.literal("V1") && b.separator() && b.literal("O") && b.separator() && b.unsignedValue(sequence) &&
         b.separator() && b.unsignedValue(lampPwm) && b.separator() && b.unsignedValue(fanPwm) &&
         b.separator() && b.unsignedValue(ttlMs) && b.separator() && b.unsignedValue(stateCode) && b.finish();
}

inline bool frameStop(char *out, size_t capacity, uint16_t sequence) {
  FrameBuilder b(out, capacity);
  return b.literal("V1") && b.separator() && b.literal("X") && b.separator() && b.unsignedValue(sequence) && b.finish();
}

inline bool framePing(char *out, size_t capacity, uint16_t sequence) {
  FrameBuilder b(out, capacity);
  return b.literal("V1") && b.separator() && b.literal("P") && b.separator() && b.unsignedValue(sequence) && b.finish();
}

inline bool frameCalibration(char *out, size_t capacity, uint16_t sequence, uint8_t phase) {
  if (phase < 1 || phase > 3) return false;
  FrameBuilder b(out, capacity);
  return b.literal("V1") && b.separator() && b.literal("C") && b.separator() && b.unsignedValue(sequence) &&
         b.separator() && b.unsignedValue(phase) && b.finish();
}

inline bool frameSensor(char *out, size_t capacity, int32_t irDeciC, int32_t tcDeciC,
                        uint32_t lux, uint32_t maxHardwareLux, uint8_t flags) {
  FrameBuilder b(out, capacity);
  return b.literal("V1") && b.separator() && b.literal("R") && b.separator() && b.signedValue(irDeciC) &&
         b.separator() && b.signedValue(tcDeciC) && b.separator() && b.unsignedValue(lux) &&
         b.separator() && b.unsignedValue(maxHardwareLux) && b.separator() && b.unsignedValue(flags) && b.finish();
}

inline bool frameAck(char *out, size_t capacity, uint16_t sequence, uint8_t code) {
  FrameBuilder b(out, capacity);
  return b.literal("V1") && b.separator() && b.literal("K") && b.separator() && b.unsignedValue(sequence) &&
         b.separator() && b.unsignedValue(code) && b.finish();
}

inline bool frameFault(char *out, size_t capacity, uint8_t fault) {
  FrameBuilder b(out, capacity);
  return b.literal("V1") && b.separator() && b.literal("F") && b.separator() && b.unsignedValue(fault) && b.finish();
}

inline bool frameLinkPause(char *out, size_t capacity, uint16_t lastOutputSequence,
                           uint8_t lampPwm, uint8_t fanPwm) {
  FrameBuilder b(out, capacity);
  return b.literal("V1") && b.separator() && b.literal("L") && b.separator() &&
         b.unsignedValue(lastOutputSequence) && b.separator() && b.unsignedValue(lampPwm) &&
         b.separator() && b.unsignedValue(fanPwm) && b.finish();
}

inline bool frameCalibrationResult(char *out, size_t capacity, uint8_t phase, uint32_t bareDeciLux,
                                   uint32_t tapedDeciLux, uint16_t attenuationPermille,
                                   uint32_t maxDeciLux) {
  if (phase < 1 || phase > 3) return false;
  FrameBuilder b(out, capacity);
  return b.literal("V1") && b.separator() && b.literal("Q") && b.separator() && b.unsignedValue(phase) &&
         b.separator() && b.unsignedValue(bareDeciLux) && b.separator() && b.unsignedValue(tapedDeciLux) &&
         b.separator() && b.unsignedValue(attenuationPermille) && b.separator() && b.unsignedValue(maxDeciLux) && b.finish();
}

}  // namespace ptkit
#endif
