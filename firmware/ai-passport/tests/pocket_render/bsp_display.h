#pragma once
#include <stdbool.h>
#define BSP_LCD_W 240
#define BSP_LCD_H 320
bool bsp_lvgl_lock(int timeout_ms);
void bsp_lvgl_unlock(void);
