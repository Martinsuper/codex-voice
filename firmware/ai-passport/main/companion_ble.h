#pragma once
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
esp_err_t cp_ble_init(QueueHandle_t frames);
bool cp_ble_ready(void);
bool cp_ble_voice_ready(void);
bool cp_ble_send_voice(const uint8_t *data, size_t length);
uint32_t cp_ble_passkey(void);
bool cp_ble_send(const char *json);
void cp_ble_unpair(void);
