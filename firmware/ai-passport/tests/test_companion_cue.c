#include "companion_cue.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct { size_t written; bool muted; bool failed; } sink_t;
static bool mute(void *context,bool value) {
    sink_t *sink=context;
    if (!value) assert(sink->written==CP_CUE_LEAD_SAMPLES);
    else if (sink->written) assert(sink->failed || sink->written==cp_cue_samples(CP_CUE_COMPLETE));
    sink->muted=value; return true;
}
static bool write_pcm(void *context,const int16_t *pcm,size_t count) {
    sink_t *sink=context; assert(count==CP_CUE_BLOCK);
    if (sink->written<CP_CUE_LEAD_SAMPLES) assert(sink->muted);
    for (size_t i=0;i<count;++i) if (pcm[i]) assert(!sink->muted);
    if (sink->failed && sink->written>=CP_CUE_LEAD_SAMPLES) return false;
    sink->written+=count; return true;
}
int main(void)
{
    int16_t pcm[CP_CUE_BLOCK];
    assert(cp_cue_samples(CP_CUE_READY)==5760);
    assert(cp_cue_samples(CP_CUE_COMPLETE)==7200);
    assert(cp_cue_samples((cp_cue_t)9)==0);
    for (int cue=CP_CUE_READY;cue<=CP_CUE_ATTENTION;++cue) {
        double energy=0; int peak=0; size_t count=0, sounding=0;
        for (size_t offset=0;offset<cp_cue_samples(cue);offset+=CP_CUE_BLOCK) {
            size_t n=cp_cue_render(cue,offset,pcm,CP_CUE_BLOCK); assert(n==CP_CUE_BLOCK);
            for (size_t i=0;i<n;++i) {
                int p=abs(pcm[i]); if (p>peak) peak=p;
                assert(p<=9000); energy+=(double)pcm[i]*pcm[i];
                if (offset+i<1920 || offset+i>=cp_cue_samples(cue)-1920) assert(pcm[i]==0);
                else if (p>100) ++sounding;
            }
            count+=n;
        }
        assert(peak>8500 && sounding>1200 && sqrt(energy/count)>3000);
        assert(!cp_cue_render(cue,count,pcm,CP_CUE_BLOCK));
    }
    double signal=0,error=0;
    for (size_t n=240;n<1920-480;++n) {
        int16_t sample;
        assert(cp_cue_render(CP_CUE_READY,CP_CUE_LEAD_SAMPLES+n,&sample,1)==1);
        double ideal=9000*sin(6.283185307179586*1046.5*n/16000);
        signal+=ideal*ideal; double delta=ideal-sample; error+=delta*delta;
    }
    assert(10*log10(signal/error)>55); // Interpolation/quantization does not add audible grit.
    sink_t sink={0};
    cp_cue_output_t out={.context=&sink,.write=write_pcm,.mute=mute};
    assert(cp_cue_play(CP_CUE_COMPLETE,&out)); assert(sink.muted);
    sink=(sink_t){.failed=true}; assert(!cp_cue_play(CP_CUE_COMPLETE,&out)); assert(sink.muted);
    puts("Cue PCM energy, envelope, DMA alignment, warm-up/drain silence: PASS");
    return 0;
}
