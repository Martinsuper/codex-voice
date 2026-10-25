#include "companion_pet_store.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t flash[CP_PET_SLOT_SIZE*2],payload[CP_PET_BYTES];
static int protected_slot=-1;
static size_t fail_offset=(size_t)-1;
/* Storage tests inject a deterministic checksum. Production uses mbedTLS SHA-256. */
static bool hash(const uint8_t *p,size_t size,uint8_t out[32])
{
    uint32_t h=2166136261u;for (size_t i=0;i<size;++i) h=(h^p[i])*16777619u;
    for (int i=0;i<32;++i) out[i]=(uint8_t)(h>>((i%4)*8));return true;
}
static bool erase(void *ctx,size_t offset,size_t size)
{
    (void)ctx;assert(offset%4096==0 && size%4096==0 && offset+size<=sizeof(flash));
    assert(protected_slot<0 || offset/CP_PET_SLOT_SIZE!=(size_t)protected_slot);
    memset(flash+offset,255,size);return true;
}
static bool write(void *ctx,size_t offset,const void *data,size_t size)
{
    (void)ctx;assert(offset+size<=sizeof(flash));assert(protected_slot<0 || offset/CP_PET_SLOT_SIZE!=(size_t)protected_slot);
    if (offset==fail_offset) return false;
    const uint8_t *p=data;for(size_t i=0;i<size;++i){assert((flash[offset+i]&p[i])==p[i]);flash[offset+i]&=p[i];}return true;
}
static cp_pet_io_t io(void) {return (cp_pet_io_t){NULL,flash,erase,write,hash};}
static void fill(cp_pet_store_t *s)
{
    while(s->received<CP_PET_BYTES){size_t n=CP_PET_BYTES-s->received;if(n>229)n=229;assert(cp_pet_store_data(s,s->received,payload+s->received,n));}
}
int main(void)
{
    memset(flash,255,sizeof(flash));memset(payload,35,sizeof(payload));uint8_t sha[32];hash(payload,sizeof(payload),sha);
    cp_pet_store_t s;cp_pet_store_init(&s,io());assert(s.active==-1);
    assert(cp_pet_store_begin(&s,sha)==0);assert(!cp_pet_store_commit(&s));
    assert(!cp_pet_store_data(&s,1,payload,20));assert(!cp_pet_store_data(&s,CP_PET_BYTES,payload,1));
    assert(cp_pet_store_data(&s,0,payload,20));assert(cp_pet_store_data(&s,0,payload,20));
    uint8_t changed[20]={0};assert(!cp_pet_store_data(&s,0,changed,20));
    assert(cp_pet_store_begin(&s,sha)==0 && s.received==20);fill(&s);assert(cp_pet_store_commit(&s));assert(s.active==0);
    protected_slot=0;cp_pet_store_t boot;cp_pet_store_init(&boot,io());assert(boot.active==0);assert(cp_pet_store_begin(&s,sha)==1);
    memset(payload,81,sizeof(payload));hash(payload,sizeof(payload),sha);assert(cp_pet_store_begin(&s,sha)==0);
    assert(cp_pet_store_data(&s,0,payload,100));cp_pet_store_init(&boot,io());assert(boot.active==0); /* interrupted transfer */
    fill(&s);flash[CP_PET_SLOT_SIZE+CP_PET_DATA_OFFSET+400]^=1;assert(!cp_pet_store_commit(&s));cp_pet_store_init(&boot,io());assert(boot.active==0);
    assert(cp_pet_store_begin(&s,sha)==0);fill(&s);fail_offset=CP_PET_SLOT_SIZE+68;
    assert(!cp_pet_store_commit(&s));cp_pet_store_init(&boot,io());assert(boot.active==0); /* power loss before commit word */
    fail_offset=(size_t)-1;assert(cp_pet_store_commit(&s));assert(s.active==1);protected_slot=1;
    cp_pet_store_init(&boot,io());assert(boot.active==1);
    flash[CP_PET_SLOT_SIZE+32]^=1;cp_pet_store_init(&boot,io());assert(boot.active==0); /* corrupt newest header falls back */
    uint8_t packet[244]={'P','A',1},id[8];uint32_t offset;
    assert(cp_pet_packet(packet,sizeof(packet),id,&offset));assert(offset==0);
    memset(packet+11,255,4);assert(!cp_pet_packet(packet,sizeof(packet),id,&offset));assert(!cp_pet_packet(packet,15,id,&offset));
    uint8_t decoded[8];assert(!cp_pet_unhex("../../no",8,decoded));assert(cp_pet_unhex("0123456789abcdef",8,decoded));
    char hex[17];cp_pet_hex(decoded,8,hex);assert(!strcmp(hex,"0123456789abcdef"));
    puts("Pet A/B storage: bounds, resume, duplicate/conflict, hash rejection, interrupted commit, corruption fallback and active-slot preservation PASS");
}
