#include "companion_cue.h"
#define LEAD CP_CUE_LEAD_SAMPLES
#define TAIL 1920U
#define READY 1920U
#define NOTE 1440U
#define GAP 480U
// Interpolated Q15 oscillator. The C3 has no FPU: do not evaluate sinf/cosf
// in the real-time feed loop while BLE and display tasks share the core.
static const int16_t sine[256] = {
    0,804,1608,2410,3212,4011,4808,5602,6393,7179,7962,8739,9512,10278,11039,11793,
    12539,13279,14010,14732,15446,16151,16846,17530,18204,18868,19519,20159,20787,21403,22005,22594,
    23170,23731,24279,24811,25329,25832,26319,26790,27245,27683,28105,28510,28898,29268,29621,29956,
    30273,30571,30852,31113,31356,31580,31785,31971,32137,32285,32412,32521,32609,32678,32728,32757,
    32767,32757,32728,32678,32609,32521,32412,32285,32137,31971,31785,31580,31356,31113,30852,30571,
    30273,29956,29621,29268,28898,28510,28105,27683,27245,26790,26319,25832,25329,24811,24279,23731,
    23170,22594,22005,21403,20787,20159,19519,18868,18204,17530,16846,16151,15446,14732,14010,13279,
    12539,11793,11039,10278,9512,8739,7962,7179,6393,5602,4808,4011,3212,2410,1608,804,
    0,-804,-1608,-2410,-3212,-4011,-4808,-5602,-6393,-7179,-7962,-8739,-9512,-10278,-11039,-11793,
    -12539,-13279,-14010,-14732,-15446,-16151,-16846,-17530,-18204,-18868,-19519,-20159,-20787,-21403,-22005,-22594,
    -23170,-23731,-24279,-24811,-25329,-25832,-26319,-26790,-27245,-27683,-28105,-28510,-28898,-29268,-29621,-29956,
    -30273,-30571,-30852,-31113,-31356,-31580,-31785,-31971,-32137,-32285,-32412,-32521,-32609,-32678,-32728,-32757,
    -32767,-32757,-32728,-32678,-32609,-32521,-32412,-32285,-32137,-31971,-31785,-31580,-31356,-31113,-30852,-30571,
    -30273,-29956,-29621,-29268,-28898,-28510,-28105,-27683,-27245,-26790,-26319,-25832,-25329,-24811,-24279,-23731,
    -23170,-22594,-22005,-21403,-20787,-20159,-19519,-18868,-18204,-17530,-16846,-16151,-15446,-14732,-14010,-13279,
    -12539,-11793,-11039,-10278,-9512,-8739,-7962,-7179,-6393,-5602,-4808,-4011,-3212,-2410,-1608,-804};
static const uint32_t phase_steps[] = {280917705U,353934833U,472446403U,176966074U,140458852U};
static size_t body_samples(cp_cue_t cue) { return cue==CP_CUE_READY ? READY : NOTE*2+GAP; }
size_t cp_cue_samples(cp_cue_t cue)
{
    return cue>=CP_CUE_READY && cue<=CP_CUE_ATTENTION ? LEAD+body_samples(cue)+TAIL : 0;
}
static int32_t fade(size_t n,size_t duration)
{
    if (n>=duration) return 32768;
    int32_t t=(int32_t)(n*32768U/duration);
    int32_t square=t*t/32768;
    return square*(98304-2*t)/32768; // smoothstep: zero slope at both ends
}
size_t cp_cue_render(cp_cue_t cue,size_t offset,int16_t *pcm,size_t capacity)
{
    size_t total=cp_cue_samples(cue);
    if (!pcm || !capacity || offset>=total) return 0;
    size_t count=total-offset; if (count>capacity) count=capacity;
    for (size_t i=0;i<count;++i) {
        size_t at=offset+i; pcm[i]=0;
        if (at<LEAD || at>=total-TAIL) continue;
        size_t n=at-LEAD,duration=READY;
        unsigned oscillator=0;
        if (cue!=CP_CUE_READY) {
            if (n>=NOTE && n<NOTE+GAP) continue;
            bool second=n>=NOTE+GAP;
            if (second) n-=NOTE+GAP;
            duration=NOTE;
            oscillator=cue==CP_CUE_COMPLETE ? (second ? 2 : 1) : (second ? 4 : 3);
        }
        uint32_t phase=(uint32_t)n*phase_steps[oscillator];
        unsigned index=phase>>24, fraction=(phase>>8)&65535;
        int32_t sample=sine[index]+((int32_t)sine[(index+1)&255]-sine[index])*(int32_t)fraction/65536;
        int32_t attack=fade(n,240),release=fade(duration-1-n,480);
        int32_t gain=attack<release ? attack : release;
        pcm[i]=(int16_t)((sample*9000/32768)*gain/32768);
    }
    return count;
}
bool cp_cue_play(cp_cue_t cue,const cp_cue_output_t *out)
{
    if (!out || !out->write || !out->mute || !cp_cue_samples(cue)) return false;
    if (!out->mute(out->context,true)) return false;
    int16_t pcm[CP_CUE_BLOCK];
    for (size_t offset=0;offset<cp_cue_samples(cue);) {
        if (offset==LEAD && !out->mute(out->context,false)) {
            (void)out->mute(out->context,true); return false;
        }
        size_t count=cp_cue_render(cue,offset,pcm,CP_CUE_BLOCK);
        if (!count || !out->write(out->context,pcm,count)) {
            (void)out->mute(out->context,true); return false;
        }
        offset+=count;
    }
    return out->mute(out->context,true);
}
