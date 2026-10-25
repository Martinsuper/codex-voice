#pragma once
#include "companion_pet_store.h"

bool cp_pet_init(void);
bool cp_pet_supported(void);
void cp_pet_set_busy(bool busy);
bool cp_pet_begin(const char *id,const char *sha);
bool cp_pet_commit(const char *id);
bool cp_pet_receive(const uint8_t *data,size_t length);
/* Main application only; call while holding the LVGL lock before updating its image. */
const uint8_t *cp_pet_current(void);
/* Main application task only, serialized with cp_pet_current. */
void cp_pet_current_hash(char out[65]);
