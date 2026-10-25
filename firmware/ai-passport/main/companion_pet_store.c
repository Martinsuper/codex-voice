#include "companion_pet_store.h"
#include <string.h>

static uint32_t get32(const uint8_t *p) { return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static void put32(uint8_t *p,uint32_t v) { for (int i=0;i<4;++i) p[i]=(uint8_t)(v>>(8*i)); }
static uint32_t crc(const uint8_t *p,size_t n)
{
    uint32_t v=~0u;
    for (size_t i=0;i<n;++i) { v^=p[i]; for (int j=0;j<8;++j) v=(v>>1)^((v&1)?0xedb88320u:0); }
    return ~v;
}
bool cp_pet_unhex(const char *s,size_t bytes,uint8_t *out)
{
    if (!s || strlen(s)!=bytes*2) return false;
    for (size_t i=0;i<bytes;++i) {
        unsigned v=0;
        for (int j=0;j<2;++j) { char c=s[2*i+j]; if (c>='0'&&c<='9') v=v*16+(unsigned)(c-'0'); else if(c>='a'&&c<='f') v=v*16+(unsigned)(c-'a'+10); else return false; }
        out[i]=(uint8_t)v;
    }
    return true;
}
void cp_pet_hex(const uint8_t *data,size_t bytes,char *out)
{
    const char *hex="0123456789abcdef";
    for (size_t i=0;i<bytes;++i) { out[2*i]=hex[data[i]>>4];out[2*i+1]=hex[data[i]&15]; } out[bytes*2]=0;
}
bool cp_pet_decode_header(const uint8_t *p,cp_pet_meta_t *out)
{
    if (memcmp(p,"CPPET001",8) || get32(p+8)!=1 || get32(p+12)!=(CP_PET_WIDTH|(CP_PET_HEIGHT<<16)) ||
        get32(p+16)!=CP_PET_FRAMES || get32(p+20)!=CP_PET_BYTES || get32(p+64)!=crc(p,64) || get32(p+68)!=0x50455431u) return false;
    out->generation=(uint64_t)get32(p+24)|(uint64_t)get32(p+28)<<32;
    memcpy(out->sha,p+32,32); return out->generation!=0;
}
void cp_pet_encode_header(uint8_t *p,const cp_pet_meta_t *m)
{
    memset(p,0,CP_PET_HEADER_BYTES); memcpy(p,"CPPET001",8);put32(p+8,1);
    put32(p+12,CP_PET_WIDTH|(CP_PET_HEIGHT<<16));put32(p+16,CP_PET_FRAMES);put32(p+20,CP_PET_BYTES);
    put32(p+24,(uint32_t)m->generation);put32(p+28,(uint32_t)(m->generation>>32));memcpy(p+32,m->sha,32);
    put32(p+64,crc(p,64));put32(p+68,0x50455431u);
}
bool cp_pet_packet(const uint8_t *p,size_t length,uint8_t id[8],uint32_t *offset)
{
    if (length<=CP_PET_PACKET_HEADER || length>CP_PET_PACKET_MAX || p[0]!='P' || p[1]!='A' || p[2]!=1) return false;
    memcpy(id,p+3,8); *offset=get32(p+11);
    return *offset<=CP_PET_BYTES && length-CP_PET_PACKET_HEADER<=CP_PET_BYTES-*offset;
}
void cp_pet_store_init(cp_pet_store_t *s,cp_pet_io_t io)
{
    memset(s,0,sizeof(*s));s->io=io;s->active=-1;s->target=-1;
    for (int i=0;i<2;++i) {
        const uint8_t *p=io.mapped+(size_t)i*CP_PET_SLOT_SIZE;uint8_t sha[32];
        if (cp_pet_decode_header(p,&s->meta[i]) && io.hash(p+CP_PET_DATA_OFFSET,CP_PET_BYTES,sha) && !memcmp(sha,s->meta[i].sha,32) &&
            (s->active<0 || s->meta[i].generation>s->meta[s->active].generation)) s->active=i;
    }
}
int cp_pet_store_begin(cp_pet_store_t *s,const uint8_t sha[32])
{
    if (s->active>=0 && !memcmp(s->meta[s->active].sha,sha,32)) return 1;
    if (s->transferring && !memcmp(s->desired_sha,sha,32)) return 0;
    s->transferring=false;s->target=s->active==0?1:0;s->received=0;s->erased=0;memcpy(s->desired_sha,sha,32);
    if (!s->io.erase(s->io.context,(size_t)s->target*CP_PET_SLOT_SIZE,CP_PET_DATA_OFFSET)) return -1;
    s->transferring=true;return 0;
}
bool cp_pet_store_data(cp_pet_store_t *s,size_t offset,const uint8_t *data,size_t size)
{
    if (!s->transferring || !size || size>CP_PET_PACKET_MAX || offset>CP_PET_BYTES || size>CP_PET_BYTES-offset) return false;
    size_t base=(size_t)s->target*CP_PET_SLOT_SIZE+CP_PET_DATA_OFFSET;
    if (offset<s->received) return offset+size<=s->received && !memcmp(s->io.mapped+base+offset,data,size);
    if (offset!=s->received) return false;
    while (s->erased<offset+size) {
        if (!s->io.erase(s->io.context,base+s->erased,4096)) return false;
        s->erased+=4096;
    }
    if (!s->io.write(s->io.context,base+offset,data,size)) return false;
    s->received+=size;return true;
}
bool cp_pet_store_commit(cp_pet_store_t *s)
{
    if (!s->transferring || s->received!=CP_PET_BYTES) return false;
    size_t base=(size_t)s->target*CP_PET_SLOT_SIZE;uint8_t sha[32];
    if (!s->io.hash(s->io.mapped+base+CP_PET_DATA_OFFSET,CP_PET_BYTES,sha) || memcmp(sha,s->desired_sha,32)) {s->transferring=false;return false;}
    cp_pet_meta_t next={.generation=s->active<0?1:s->meta[s->active].generation+1};memcpy(next.sha,sha,32);
    uint8_t header[CP_PET_HEADER_BYTES];cp_pet_encode_header(header,&next);
    /* Only the final commit word makes a fully written, verified slot valid. */
    if (!s->io.write(s->io.context,base,header,68) || !s->io.write(s->io.context,base+68,header+68,4)) return false;
    s->meta[s->target]=next;s->active=s->target;s->transferring=false;return true;
}
