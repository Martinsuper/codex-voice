#include "companion_model.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static int s_lines;
static char s_last[CP_FRAME_MAX];
static void line(const char *s, void *arg) { (void)arg; ++s_lines; strcpy(s_last, s); }
static cp_model_t state(void)
{
    cp_model_t m;
    cp_model_init(&m);
    strcpy(m.epoch, "0123456789abcdef");
    m.enabled = true; m.monitor = true; m.count = 2; m.total = 2;
    strcpy(m.alerts[0].id, "0000000000000001"); strcpy(m.alerts[0].title, "测试任务");
    strcpy(m.alerts[1].id, "0000000000000002"); strcpy(m.alerts[1].title, "另一个任务");
    return m;
}
int main(void)
{
    cp_model_t alias; cp_model_init(&alias); assert(!strcmp(alias.pet_name, CP_DEFAULT_PET_NAME));

    cp_model_t m, in = state();
    cp_model_init(&m);
    assert(cp_model_apply(&m, &in, 1000));
    assert(cp_can_play(&m, in.epoch, 1000));
    assert(!cp_can_play(&m, "fedcba9876543210", 1000));
    cp_model_select(&m, -1); assert(m.selected == 1);
    cp_alert_t a = in.alerts[0]; in.alerts[0] = in.alerts[1]; in.alerts[1] = a;
    assert(cp_model_apply(&m, &in, 2000)); assert(m.selected == 0);
    in.usage = 101;
    assert(!cp_model_apply(&m, &in, 3000)); assert(m.updated_ms == 2000);
    in.usage = -1; strcpy(in.alerts[1].id, in.alerts[0].id);
    assert(!cp_model_apply(&m, &in, 3000));
    m.muted = true; assert(!cp_can_play(&m, m.epoch, 2000));
    m.muted = false; m.quiet = true;
    assert(cp_can_play(&m, m.epoch, 2000)); /* the Mac applies per-kind DND exceptions */
    assert(!cp_model_expire(&m, 12000)); assert(cp_model_expire(&m, 12001));
    assert(!m.online && m.count == 0 && m.epoch[0] == 0);
    assert(cp_text_valid("中文 ABC", CP_TITLE_MAX));
    assert(!cp_text_valid("\xf0\x80\x80\x80", CP_TITLE_MAX));
    assert(!cp_text_valid("\xed\xa0\x80", CP_TITLE_MAX));
    assert(!cp_text_valid("bad\ntext", CP_TITLE_MAX));
    assert(!cp_text_valid("\xe4\xb8", CP_TITLE_MAX));
    cp_line_t parser = {0};
    cp_line_feed(&parser, (uint8_t *)"{\"v\":", 5, line, NULL);
    assert(s_lines == 0);
    cp_line_feed(&parser, (uint8_t *)"1}\n{}\n", 6, line, NULL);
    assert(s_lines == 2 && !strcmp(s_last, "{}"));
    static uint8_t huge[CP_FRAME_MAX + 8];
    memset(huge, 'a', sizeof(huge));
    cp_line_feed(&parser, huge, sizeof(huge), line, NULL);
    cp_line_feed(&parser, (uint8_t *)"\nOK\n", 4, line, NULL);
    assert(s_lines == 3 && !strcmp(s_last, "OK"));
    const uint8_t nul[] = {'a', 0, 'b', '\n', 'X', '\n'};
    cp_line_feed(&parser, nul, sizeof(nul), line, NULL);
    assert(s_lines == 4 && !strcmp(s_last, "X"));
    puts("Companion state/framing tests: PASS");
}
