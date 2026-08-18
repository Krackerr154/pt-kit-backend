#include "../../ptkit_offload_protocol.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

int main() {
  char arm[] = "V1:A:7:800:00";
  const unsigned char armCrc = ptkit::crc8("V1:A:7:800");
  arm[strlen(arm) - 2] = ptkit::hexDigit(armCrc >> 4);
  arm[strlen(arm) - 1] = ptkit::hexDigit(armCrc);
  ptkit::ArmPacket parsedArm;
  assert(ptkit::parseArm(arm, parsedArm));
  assert(parsedArm.sequence == 7 && parsedArm.maxTempDeciC == 800);

  char output[] = "V1:O:8:255:0:1500:9:00";
  const unsigned char outputCrc = ptkit::crc8("V1:O:8:255:0:1500:9");
  output[strlen(output) - 2] = ptkit::hexDigit(outputCrc >> 4);
  output[strlen(output) - 1] = ptkit::hexDigit(outputCrc);
  ptkit::OutputPacket parsedOutput;
  assert(ptkit::parseOutput(output, parsedOutput));
  assert(parsedOutput.sequence == 8 && parsedOutput.lampPwm == 255 &&
         parsedOutput.fanPwm == 0 && parsedOutput.ttlMs == 1500 && parsedOutput.stateCode == 9);

  char linkPause[] = "V1:L:8:255:0:00";
  const unsigned char linkPauseCrc = ptkit::crc8("V1:L:8:255:0");
  linkPause[strlen(linkPause) - 2] = ptkit::hexDigit(linkPauseCrc >> 4);
  linkPause[strlen(linkPause) - 1] = ptkit::hexDigit(linkPauseCrc);
  ptkit::LinkPausePacket parsedLinkPause;
  assert(ptkit::parseLinkPause(linkPause, parsedLinkPause));
  assert(parsedLinkPause.lastOutputSequence == 8 && parsedLinkPause.lampPwm == 255 &&
         parsedLinkPause.fanPwm == 0);

  char framedLinkPause[ptkit::FRAME_MAX_CHARS];
  assert(ptkit::frameLinkPause(framedLinkPause, sizeof(framedLinkPause), 8, 255, 0));
  assert(ptkit::parseLinkPause(framedLinkPause, parsedLinkPause));

  char status[] = "V1:R:-12:315:38000:10000:3:00";
  const unsigned char statusCrc = ptkit::crc8("V1:R:-12:315:38000:10000:3");
  status[strlen(status) - 2] = ptkit::hexDigit(statusCrc >> 4);
  status[strlen(status) - 1] = ptkit::hexDigit(statusCrc);
  ptkit::SensorPacket parsedStatus;
  assert(ptkit::parseSensor(status, parsedStatus));
  assert(parsedStatus.irDeciC == -12 && parsedStatus.tcDeciC == 315 &&
         parsedStatus.lux == 38000 && parsedStatus.maxHardwareLux == 10000 && parsedStatus.flags == 3);

  char wrongCrc[] = "V1:A:7:800:00";
  assert(!ptkit::parseArm(wrongCrc, parsedArm));
  char overPwm[] = "V1:O:8:256:0:1500:9:00";
  const unsigned char overPwmCrc = ptkit::crc8("V1:O:8:256:0:1500:9");
  overPwm[strlen(overPwm) - 2] = ptkit::hexDigit(overPwmCrc >> 4);
  overPwm[strlen(overPwm) - 1] = ptkit::hexDigit(overPwmCrc);
  assert(!ptkit::parseOutput(overPwm, parsedOutput));

  puts("offload protocol tests: PASS");
  return 0;
}
