#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define CP_PET_SLOT_SIZE 0x100000u
#define CP_PET_DATA_OFFSET 4096u
#define CP_PET_WIDTH 144u
#define CP_PET_HEIGHT 156u
#define CP_PET_FRAMES 16u
#define CP_PET_FRAME_BYTES (CP_PET_WIDTH*CP_PET_HEIGHT*2u)
#define CP_PET_BYTES (CP_PET_FRAME_BYTES*CP_PET_FRAMES)
#define CP_PET_HEADER_BYTES 72u
#define CP_PET_PACKET_HEADER 15u
#define CP_PET_PACKET_MAX 244u

typedef struct { uint64_t generation; uint8_t sha[32]; } cp_pet_meta_t;
typedef struct {
    void *context;
    const uint8_t *mapped;
    bool (*erase)(void *,size_t,size_t);
    bool (*write)(void *,size_t,const void *,size_t);
    bool (*hash)(const uint8_t *,size_t,uint8_t[32]);
} cp_pet_io_t;
typedef struct {
    cp_pet_io_t io;
    cp_pet_meta_t meta[2];
    int active, target;
    bool transferring;
    size_t received, erased;
    uint8_t desired_sha[32];
} cp_pet_store_t;

bool cp_pet_unhex(const char *s,size_t bytes,uint8_t *out);
void cp_pet_hex(const uint8_t *data,size_t bytes,char *out);
bool cp_pet_decode_header(const uint8_t *data,cp_pet_meta_t *out);
void cp_pet_encode_header(uint8_t *data,const cp_pet_meta_t *meta);
bool cp_pet_packet(const uint8_t *data,size_t length,uint8_t id[8],uint32_t *offset);
void cp_pet_store_init(cp_pet_store_t *s,cp_pet_io_t io);
/* 1 = already current, 0 = transfer/resume ready, -1 = I/O failure. */
int cp_pet_store_begin(cp_pet_store_t *s,const uint8_t sha[32]);
bool cp_pet_store_data(cp_pet_store_t *s,size_t offset,const uint8_t *data,size_t size);
bool cp_pet_store_commit(cp_pet_store_t *s);
