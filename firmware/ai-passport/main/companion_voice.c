#include "companion_voice.h"
#include "companion_model.h"
#include <string.h>
static const int steps[89] = {
    7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,
    80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,
    494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,
    2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,
    8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767};
static const int indices[8] = {-1,-1,-1,-1,2,4,6,8};
static int clamp(int x, int low, int high) { return x < low ? low : x > high ? high : x; }
static void put16(uint8_t *p, unsigned n) { p[0] = n; p[1] = n >> 8; }
static unsigned get16(const uint8_t *p) { return p[0] | ((unsigned)p[1] << 8); }
static unsigned unhex(char c) { return c <= '9' ? (unsigned)(c - '0') : (unsigned)(c - 'a' + 10); }
static int apply(unsigned nibble, int *predictor, int *index)
{
    int step = steps[*index], delta = step >> 3;
    if (nibble & 4) delta += step;
    if (nibble & 2) delta += step >> 1;
    if (nibble & 1) delta += step >> 2;
    *predictor = clamp(*predictor + ((nibble & 8) ? -delta : delta), -32768, 32767);
    *index = clamp(*index + indices[nibble & 7], 0, 88);
    return *predictor;
}
size_t cp_voice_encode(const char *id, uint16_t seq, const int16_t *pcm,
                       size_t samples, uint8_t *packet, size_t capacity)
{
    size_t payload = samples / 2;
    if (!cp_token_valid(id) || !pcm || !packet || !samples || samples > CP_VOICE_SAMPLES ||
        seq >= CP_VOICE_MAX_FRAMES || capacity < CP_VOICE_HEADER + payload) return 0;
    memset(packet, 0, CP_VOICE_HEADER + payload);
    packet[0] = 'P'; packet[1] = 'V'; packet[2] = 1; put16(packet + 3, payload);
    for (int i = 0; i < 8; ++i) packet[5+i] = (unhex(id[2*i]) << 4) | unhex(id[2*i+1]);
    put16(packet + 13, seq); put16(packet + 15, samples); put16(packet + 17, (uint16_t)pcm[0]);
    /* Start with a moderate step; independent blocks recover without drift. */
    int predictor = pcm[0], index = 40;
    packet[19] = index;
    for (size_t i = 1; i < samples; ++i) {
        int diff = (int)pcm[i] - predictor, step = steps[index];
        unsigned code = diff < 0 ? 8 : 0;
        if (diff < 0) diff = -diff;
        if (diff >= step) { code |= 4; diff -= step; }
        if (diff >= (step >> 1)) { code |= 2; diff -= step >> 1; }
        if (diff >= (step >> 2)) code |= 1;
        apply(code, &predictor, &index);
        packet[CP_VOICE_HEADER + (i-1)/2] |= code << (((i-1)%2)*4);
    }
    return CP_VOICE_HEADER + payload;
}
size_t cp_voice_decode(const uint8_t *p, size_t length, int16_t *pcm, size_t capacity)
{
    if (!p || length < CP_VOICE_HEADER || p[0] != 'P' || p[1] != 'V' || p[2] != 1) return 0;
    size_t count = get16(p+15);
    if (!pcm || !count || count > CP_VOICE_SAMPLES || capacity < count || p[19] > 88 ||
        length != CP_VOICE_HEADER + count/2 || get16(p+3) != count/2) return 0;
    int predictor = (int16_t)get16(p+17), index = p[19];
    pcm[0] = predictor;
    for (size_t i = 1; i < count; ++i) {
        unsigned code = (p[CP_VOICE_HEADER + (i-1)/2] >> (((i-1)%2)*4)) & 15;
        pcm[i] = apply(code, &predictor, &index);
    }
    return count;
}
void cp_gesture_press(cp_gesture_t *g, bool asleep, const char *id)
{
    memset(g, 0, sizeof(*g)); g->wake_click = asleep;
    if (id) memcpy(g->alert, id, 17);
}
bool cp_gesture_click(cp_gesture_t *g)
{
    bool action = !g->wake_click && !g->held;
    g->wake_click = false;
    return action;
}
