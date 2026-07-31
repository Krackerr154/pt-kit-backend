#ifndef ISOTHERMAL_CONTROL_H
#define ISOTHERMAL_CONTROL_H
#include <stdlib.h>
#include <string.h>
#include <math.h>

enum ControlSensor { SENSOR_TC, SENSOR_IR };
enum PostPlateauMode { POST_PASSIVE, POST_REGULATED };
struct IsoCommand { float targetTemp,tolerance,maxTemp,rampRate; unsigned long holdSeconds,qualificationSeconds,logInterval; ControlSensor sensor; };
struct PlateauCommand { float targetLux,maxSlope,maxPeakToPeak,maxTemp; unsigned long holdSeconds,windowSeconds,confirmationSeconds,maxDiscoverySeconds,logInterval; ControlSensor sensor; PostPlateauMode postMode; };
const int PLATEAU_CAPACITY=60;
inline bool finitePositive(float x){ return isfinite(x)&&x>0; }
inline int splitFields(const char* in,char out[][20],int max){ int n=0,j=0; if(!in)return 0; for(;*in && n<max;in++){ if(*in==':'){out[n][j]=0;n++;j=0;} else if(j<19) out[n][j++]=*in; else return 0;} if(n<max){out[n][j]=0;n++;} return n; }
inline bool sensorField(const char*s,ControlSensor&v){if(!strcmp(s,"TC")){v=SENSOR_TC;return true;}if(!strcmp(s,"IR")){v=SENSOR_IR;return true;}return false;}
inline bool parseIsoCommand(const char* text,IsoCommand&o){char f[9][20];if(splitFields(text,f,9)!=9||strcmp(f[0],"ISO1"))return false;o.targetTemp=atof(f[1]);o.holdSeconds=strtoul(f[2],0,10);o.tolerance=atof(f[3]);o.qualificationSeconds=strtoul(f[4],0,10);o.maxTemp=atof(f[5]);o.logInterval=strtoul(f[6],0,10);o.rampRate=atof(f[8]);return finitePositive(o.targetTemp)&&o.holdSeconds&&finitePositive(o.tolerance)&&o.qualificationSeconds&&o.maxTemp>o.targetTemp&&o.logInterval&&sensorField(f[7],o.sensor)&&finitePositive(o.rampRate);}
inline bool parsePlateauCommand(const char*text,PlateauCommand&o){char f[12][20];if(splitFields(text,f,12)!=12||strcmp(f[0],"PLAT1"))return false;o.targetLux=atof(f[1]);o.holdSeconds=strtoul(f[2],0,10);o.windowSeconds=strtoul(f[3],0,10);o.maxSlope=atof(f[4]);o.maxPeakToPeak=atof(f[5]);o.confirmationSeconds=strtoul(f[6],0,10);o.maxDiscoverySeconds=strtoul(f[7],0,10);o.maxTemp=atof(f[8]);o.logInterval=strtoul(f[9],0,10);bool post=!strcmp(f[11],"PASSIVE")?(o.postMode=POST_PASSIVE,true):!strcmp(f[11],"REGULATED")?(o.postMode=POST_REGULATED,true):false;return finitePositive(o.targetLux)&&o.holdSeconds&&o.windowSeconds>=3&&o.windowSeconds<=PLATEAU_CAPACITY&&finitePositive(o.maxSlope)&&finitePositive(o.maxPeakToPeak)&&o.confirmationSeconds&&o.maxDiscoverySeconds>=o.windowSeconds&&finitePositive(o.maxTemp)&&o.logInterval&&sensorField(f[10],o.sensor)&&post;}
struct PlateauWindow{float t[PLATEAU_CAPACITY],y[PLATEAU_CAPACITY];int count,next;};
struct PlateauStats{bool valid;float slopePerMin,peakToPeak,mean;};
inline void plateauReset(PlateauWindow&w){w.count=w.next=0;}
inline void plateauAdd(PlateauWindow&w,float t,float y){if(!isfinite(y))return;w.t[w.next]=t;w.y[w.next]=y;w.next=(w.next+1)%PLATEAU_CAPACITY;if(w.count<PLATEAU_CAPACITY)w.count++;}
inline PlateauStats plateauStats(const PlateauWindow&w,unsigned long required){PlateauStats r={false,0,0,0};if(w.count<3||w.count<(int)required)return r;int n=w.count<(int)required?w.count:(int)required;float st=0,sy=0,stt=0,sty=0,mn=1e9,mx=-1e9;for(int k=0;k<n;k++){int i=(w.next-1-k+PLATEAU_CAPACITY)%PLATEAU_CAPACITY;float t=w.t[i],y=w.y[i];st+=t;sy+=y;stt+=t*t;sty+=t*y;if(y<mn)mn=y;if(y>mx)mx=y;}float d=n*stt-st*st;if(fabs(d)<1e-6)return r;r.valid=true;r.slopePerMin=60*(n*sty-st*sy)/d;r.peakToPeak=mx-mn;r.mean=sy/n;return r;}
struct PIController{float integral,lastOutput;}; inline void piReset(PIController&p){p.integral=p.lastOutput=0;}
inline float piStep(PIController&p,float set,float measured,float dt,float kp,float ki,float maxOut,float approach){float e=set-measured;float candidate=p.integral+ki*e*dt;float out=kp*e+candidate;if(approach>0&&e<approach&&out>maxOut*.55f)out=maxOut*.55f;if(out<0)out=0;if(out>maxOut)out=maxOut;if(out>0&&out<maxOut)p.integral=candidate;p.lastOutput=out;return out;}
#endif
