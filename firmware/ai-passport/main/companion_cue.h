#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
/* Same codec as speech. Full 15 ms blocks match the 240-frame I2S DMA units. */
#define CP_CUE_BLOCK 240
#define CP_CUE_VOLUME 65
#define CP_CUE_LEAD_SAMPLES 1920U
#define CP_CUE_RATE 16000

typedef enum { CP_CUE_READY, CP_CUE_COMPLETE, CP_CUE_ATTENTION } cp_cue_t;
size_t cp_cue_samples(cp_cue_t cue);
size_t cp_cue_render(cp_cue_t cue, size_t offset, int16_t *pcm, size_t capacity);

typedef struct {
    void *context;
    bool (*write)(void *, const int16_t *, size_t);
    bool (*mute)(void *, bool);
} cp_cue_output_t;
// Keep the DAC muted during pre-roll/tail and fail closed on any I/O error.
bool cp_cue_play(cp_cue_t cue, const cp_cue_output_t *output);
