#ifndef ISOTHERMAL_CONTROL_H
#define ISOTHERMAL_CONTROL_H
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <errno.h>
#include <stdint.h>

#ifdef ARDUINO
#include <Arduino.h>
#endif

enum ControlSensor { SENSOR_TC, SENSOR_IR };
enum PostPlateauMode { POST_PASSIVE, POST_REGULATED };
enum IlluminationMode { TARGET_LUX, MAX_OUTPUT, TEMPERATURE_CONTROLLED };
struct SensorTemperatures { float irRaw,tcRaw,irExposed,tcExposed; bool irValid,tcValid; };
inline SensorTemperatures sensorTemperatures(float ir,float tc,bool legacyExposure){
  SensorTemperatures r={ir,tc,ir,tc,isfinite(ir),isfinite(tc)};
  if(legacyExposure){if(!r.irValid)r.irExposed=0.0f;if(!r.tcValid)r.tcExposed=0.0f;}
  return r;
}
inline bool selectedTemperatureValid(const SensorTemperatures&r,ControlSensor sensor){return sensor==SENSOR_TC?r.tcValid:r.irValid;}
inline bool invalidSensorAbortDue(unsigned long now,unsigned long invalidSince,unsigned long limit=10000UL){return invalidSince!=0&&now-invalidSince>=limit;}
struct IsoCommand { float targetTemp,tolerance,maxTemp,rampRate; unsigned long holdSeconds,qualificationSeconds,logInterval; ControlSensor sensor; };
struct PlateauCommand { float targetLux,maxSlope,maxPeakToPeak,maxTemp; unsigned long holdSeconds,windowSeconds,confirmationSeconds,maxDiscoverySeconds,logInterval; ControlSensor sensor; PostPlateauMode postMode; IlluminationMode illuminationMode; };
struct MaxOutputNormalCommand { unsigned long durationSeconds,cycles,logInterval; float maxTemp; };
const int PLATEAU_CAPACITY=60;
const unsigned long MAX_MILLIS_SECONDS=4294967UL;
const unsigned long MAX_PLATEAU_SECONDS=6500UL;
inline bool finitePositive(float x){ return isfinite(x)&&x>0; }
inline int splitFields(const char* in,char out[][20],int max){ int n=0,j=0; if(!in)return 0; for(;*in && n<max;in++){ if(*in==':'){out[n][j]=0;n++;j=0;} else if(j<19) out[n][j++]=*in; else return 0;} if(n<max){out[n][j]=0;n++;} return n; }
inline bool sensorField(const char*s,ControlSensor&v){if(!strcmp(s,"TC")){v=SENSOR_TC;return true;}if(!strcmp(s,"IR")){v=SENSOR_IR;return true;}return false;}
inline bool parseUnsignedField(const char*s,unsigned long&v,unsigned long maximum=MAX_MILLIS_SECONDS){
  if(!s||!*s)return false;
  for(const char*p=s;*p;p++)if(*p<'0'||*p>'9')return false;
  errno=0; char*end=0; unsigned long x=strtoul(s,&end,10); if(errno==ERANGE||!end||*end||x>maximum)return false; v=x; return true;
}
inline bool parseFloatField(const char*s,float&v){
  if(!s||!*s)return false;
  bool dot=false,digit=false; for(const char*p=s;*p;p++){if(*p=='.'&&!dot){dot=true;continue;}if(*p<'0'||*p>'9')return false;digit=true;}if(!digit)return false;
  errno=0;char*end=0;double x=strtod(s,&end);if(errno==ERANGE||!end||*end||!isfinite(x)||x>3.402823466e38)return false;v=(float)x;return isfinite(v);
}
inline bool parseIsoCommand(const char* text,IsoCommand&o){char f[9][20];if(splitFields(text,f,9)!=9||strcmp(f[0],"ISO1"))return false;if(!parseFloatField(f[1],o.targetTemp)||!parseUnsignedField(f[2],o.holdSeconds)||!parseFloatField(f[3],o.tolerance)||!parseUnsignedField(f[4],o.qualificationSeconds)||!parseFloatField(f[5],o.maxTemp)||!parseUnsignedField(f[6],o.logInterval,32767UL)||!parseFloatField(f[8],o.rampRate))return false;return finitePositive(o.targetTemp)&&o.holdSeconds&&finitePositive(o.tolerance)&&o.qualificationSeconds&&o.maxTemp>o.targetTemp&&o.logInterval&&sensorField(f[7],o.sensor)&&finitePositive(o.rampRate);}
inline bool parseMaxOutputNormalCommand(const char*text,MaxOutputNormalCommand&o){
  char f[6][20];
  if(splitFields(text,f,6)!=6||strcmp(f[0],"SET2")||strcmp(f[5],"MAX_OUTPUT"))return false;
  if(!parseUnsignedField(f[1],o.durationSeconds)||!parseUnsignedField(f[2],o.cycles,32767UL)||!parseFloatField(f[3],o.maxTemp)||!parseUnsignedField(f[4],o.logInterval,32767UL))return false;
  return o.durationSeconds&&o.cycles&&finitePositive(o.maxTemp)&&o.logInterval;
}
inline bool parsePlateauCommand(const char*text,PlateauCommand&o){
  char f[12][20];
  if(splitFields(text,f,12)!=12)return false;
  if(!strcmp(f[0],"PLAT1")){
    if(!parseFloatField(f[1],o.targetLux)||!finitePositive(o.targetLux))return false;
    o.illuminationMode=TARGET_LUX;
  }else if(!strcmp(f[0],"PLAT2")&&!strcmp(f[1],"MAX_OUTPUT")){
    o.targetLux=0; o.illuminationMode=MAX_OUTPUT;
  }else return false;
  if(!parseUnsignedField(f[2],o.holdSeconds)||!parseUnsignedField(f[3],o.windowSeconds,MAX_PLATEAU_SECONDS)||!parseFloatField(f[4],o.maxSlope)||!parseFloatField(f[5],o.maxPeakToPeak)||!parseUnsignedField(f[6],o.confirmationSeconds)||!parseUnsignedField(f[7],o.maxDiscoverySeconds,MAX_PLATEAU_SECONDS)||!parseFloatField(f[8],o.maxTemp)||!parseUnsignedField(f[9],o.logInterval,32767UL))return false;
  bool post=!strcmp(f[11],"PASSIVE")?(o.postMode=POST_PASSIVE,true):!strcmp(f[11],"REGULATED")?(o.postMode=POST_REGULATED,true):false;
  return o.holdSeconds&&o.windowSeconds>=3&&o.windowSeconds<=PLATEAU_CAPACITY&&finitePositive(o.maxSlope)&&finitePositive(o.maxPeakToPeak)&&o.confirmationSeconds&&o.maxDiscoverySeconds>=o.windowSeconds&&finitePositive(o.maxTemp)&&o.logInterval&&sensorField(f[10],o.sensor)&&post;
}
struct PlateauWindow{uint32_t t[PLATEAU_CAPACITY];float y[PLATEAU_CAPACITY];int count,next;};
struct PlateauStats{bool valid;float slopePerMin,peakToPeak,mean;};
inline void plateauReset(PlateauWindow&w){w.count=w.next=0;}
inline void plateauAdd(PlateauWindow&w,float t,float y){if(!isfinite(t)||!isfinite(y))return;w.t[w.next]=(uint32_t)(t*10.0f);w.y[w.next]=y;w.next=(w.next+1)%PLATEAU_CAPACITY;if(w.count<PLATEAU_CAPACITY)w.count++;}
inline PlateauStats plateauStats(const PlateauWindow&w,unsigned long required){PlateauStats r={false,0,0,0};if(w.count<3||required<1||required>MAX_PLATEAU_SECONDS)return r;int newest=(w.next-1+PLATEAU_CAPACITY)%PLATEAU_CAPACITY;uint32_t newestT=w.t[newest],span=(uint32_t)(required*10UL);int n=0;double st=0,sy=0,stt=0,sty=0;float mn=INFINITY,mx=-INFINITY;uint32_t oldestAge=0;for(int k=0;k<w.count;k++){int i=(w.next-1-k+PLATEAU_CAPACITY)%PLATEAU_CAPACITY;uint32_t age=newestT-w.t[i];if(age>span)break;double t=-(double)age/10.0,y=w.y[i];st+=t;sy+=y;stt+=t*t;sty+=t*y;if(y<mn)mn=y;if(y>mx)mx=y;oldestAge=age;n++;}if(n<3||oldestAge+10<span)return r;double d=n*stt-st*st;if(fabs(d)<1e-9)return r;r.valid=true;r.slopePerMin=(float)(60*(n*sty-st*sy)/d);r.peakToPeak=mx-mn;r.mean=(float)(sy/n);return r;}
struct PIController{float integral,lastOutput;}; inline void piReset(PIController&p){p.integral=p.lastOutput=0;}
inline float piStep(PIController&p,float set,float measured,float dt,float kp,float ki,float maxOut,float approach){float e=set-measured;float candidate=p.integral+ki*e*dt;float cap=(approach>0&&e<approach)?maxOut*.55f:maxOut;float raw=kp*e+candidate;float out=raw;if(out<0)out=0;if(out>cap)out=cap;if((raw>=0&&raw<=cap)||(raw>cap&&e<0)||(raw<0&&e>0))p.integral=candidate;p.lastOutput=out;return out;}
#endif
