#include "companion_voice.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
int main(void)
{
    cp_gesture_t g;
    cp_gesture_press(&g,true,"0123456789abcdef");
    assert(!cp_gesture_click(&g));
    cp_gesture_press(&g,true,"0123456789abcdef");
    g.held=true; assert(!cp_gesture_click(&g));
    cp_gesture_press(&g,false,"0123456789abcdef");
    assert(cp_gesture_click(&g)); assert(!strcmp(g.alert,"0123456789abcdef"));
    cp_gesture_press(&g,false,NULL); assert(!g.alert[0]);
    int16_t pcm[320],decoded[320]; uint8_t packet[CP_VOICE_PACKET];
    double signal=0,error=0;
    for (int f=0;f<20;++f) {
        for (int i=0;i<320;++i) pcm[i]=(int16_t)(10000*sin((i+f*320)*0.1));
        size_t n=cp_voice_encode("0123456789abcdef",f,pcm,320,packet,sizeof(packet));
        assert(n==180); assert(cp_voice_decode(packet,n,decoded,320)==320);
        assert(decoded[0]==pcm[0]);
        for (int i=0;i<320;++i) { signal+=(double)pcm[i]*pcm[i]; double e=pcm[i]-decoded[i]; error+=e*e; }
    }
    assert(10*log10(signal/error)>18);
    assert(!cp_voice_encode("BAD",0,pcm,320,packet,sizeof(packet)));
    assert(!cp_voice_encode("0123456789abcdef",1500,pcm,320,packet,sizeof(packet)));
    assert(!cp_voice_encode("0123456789abcdef",0,pcm,321,packet,sizeof(packet)));
    assert(!cp_voice_decode(packet,179,decoded,320));
    packet[19]=89; assert(!cp_voice_decode(packet,180,decoded,320));
    for (int n=1;n<=320;++n) {
        for (int i=0;i<n;++i) pcm[i]=(i%2) ? -32768 : 32767;
        size_t size=cp_voice_encode("0123456789abcdef",0,pcm,n,packet,sizeof(packet));
        assert(size==20+(size_t)n/2); assert(cp_voice_decode(packet,size,decoded,320)==(size_t)n);
    }
    puts("Pocket voice codec, bounds, quality and wake/hold gestures: PASS");
    return 0;
}
