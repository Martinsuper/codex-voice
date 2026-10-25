#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define CP_VOICE_SAMPLES 320
#define CP_VOICE_HEADER 20
#define CP_VOICE_PACKET (CP_VOICE_HEADER + CP_VOICE_SAMPLES / 2)
#define CP_VOICE_MAX_FRAMES 1500
/* Independent IMA-ADPCM blocks: no predictor state is shared across packets.
 * Header PV,version,lengthLE16,session8,sequenceLE16,samplesLE16,predictorLE16,index.
 * The first sample is the predictor; remaining samples use low nibble first. */
size_t cp_voice_encode(const char *id, uint16_t sequence, const int16_t *pcm,
                       size_t samples, uint8_t *packet, size_t capacity);
size_t cp_voice_decode(const uint8_t *packet, size_t length, int16_t *pcm, size_t capacity);

typedef enum { CP_VOICE_IDLE, CP_VOICE_PREPARING, CP_VOICE_RECORDING,
               CP_VOICE_PROCESSING, CP_VOICE_DONE, CP_VOICE_RETAINED, CP_VOICE_ERROR } cp_voice_phase_t;
typedef struct {
    cp_voice_phase_t phase;
    char id[17];
    uint64_t since_ms;
    int level;
    char message[80];
    char target[49];
} cp_voice_view_t;
/* Wake consumes the short click, never the hold or release. */
typedef struct { bool wake_click; bool held; char alert[17]; } cp_gesture_t;
void cp_gesture_press(cp_gesture_t *gesture, bool asleep, const char *selected_alert);
bool cp_gesture_click(cp_gesture_t *gesture);
