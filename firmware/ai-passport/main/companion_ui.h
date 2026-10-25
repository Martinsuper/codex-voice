#pragma once
#include "companion_model.h"
#include "companion_voice.h"
#include <stdint.h>
void cp_ui_init(void);
void cp_ui_render(const cp_model_t *model, uint32_t passkey, int battery, bool audio,
                  int menu, int selection, const char *toast, bool asleep, int quota,
                  const cp_voice_view_t *voice, uint64_t now);
