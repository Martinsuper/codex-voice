#include "companion_voice.h"
#include <stdio.h>
#include <assert.h>
int main(int argc,char **argv) {
    assert(argc==4);
    FILE *input=fopen(argv[1],"rb"),*output=fopen(argv[2],"wb"),*decoded=fopen(argv[3],"wb");
    assert(input && output && decoded);
    int16_t pcm[320],result[320]; uint8_t packet[180]; unsigned seq=0;
    while (fread(pcm,2,320,input)==320) {
        size_t n=cp_voice_encode("0123456789abcdef",seq++,pcm,320,packet,sizeof(packet)); assert(n==180);
        assert(fwrite(packet,1,n,output)==n);
        assert(cp_voice_decode(packet,n,result,320)==320); assert(fwrite(result,2,320,decoded)==320);
    }
    fclose(input); fclose(output); fclose(decoded); printf("C encoder fixture: %u frames\n",seq);
}
