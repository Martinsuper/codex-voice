#include "companion_ui.h"
#include "companion_pet.h"
#include "bsp_display.h"
#include "lvgl.h"
#include <stdio.h>
#include <string.h>

LV_FONT_DECLARE(cp_font16);
LV_FONT_DECLARE(cp_font20);
LV_FONT_DECLARE(cp_digits58);
extern const uint8_t pet_frames_start[] asm("_binary_pet_frames_start");
static lv_obj_t *s_battery, *s_status, *s_pages[5], *s_pet, *s_pet_note, *s_pet_name;
static lv_obj_t *s_ring, *s_number, *s_period, *s_reset, *s_fresh;
static lv_obj_t *s_kind, *s_title, *s_note, *s_position, *s_bar;
static lv_obj_t *s_voice_title, *s_voice_note, *s_duration, *s_meter, *s_spinner, *s_check;
static lv_obj_t *s_menu_title, *s_menu_body, *s_footer, *s_toast;
static int s_last_pet = -1;
static lv_image_dsc_t s_pet_image;
static const uint8_t *s_dynamic_pet;
static lv_obj_t *label(lv_obj_t *parent, int x, int y, int w, int h, const lv_font_t *font)
{
    lv_obj_t *obj = lv_label_create(parent);
    lv_obj_set_pos(obj,x,y); lv_obj_set_size(obj,w,h);
    lv_obj_set_style_text_font(obj,font,0);
    lv_obj_set_style_text_color(obj,lv_color_hex(0x202124),0);
    lv_label_set_long_mode(obj,LV_LABEL_LONG_DOT);
    lv_label_set_text(obj,""); return obj;
}
static void text(lv_obj_t *obj, const char *value)
{
    if (strcmp(lv_label_get_text(obj),value)) lv_label_set_text(obj,value);
}
static void center(lv_obj_t *obj) { lv_obj_set_style_text_align(obj,LV_TEXT_ALIGN_CENTER,0); }
static void muted(lv_obj_t *obj) { lv_obj_set_style_text_color(obj,lv_color_hex(0x777983),0); }
static lv_obj_t *page(lv_obj_t *screen)
{
    lv_obj_t *obj = lv_obj_create(screen); lv_obj_remove_style_all(obj);
    lv_obj_set_pos(obj,0,49); lv_obj_set_size(obj,240,238);
    lv_obj_remove_flag(obj,LV_OBJ_FLAG_SCROLLABLE); return obj;
}
void cp_ui_init(void)
{
    if (!bsp_lvgl_lock(1000)) return;
    lv_obj_t *screen = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(screen,lv_color_hex(0xfafafc),0);
    lv_obj_set_style_bg_opa(screen,LV_OPA_COVER,0);
    lv_obj_remove_flag(screen,LV_OBJ_FLAG_SCROLLABLE);
    s_status=label(screen,20,23,152,22,&lv_font_montserrat_14);
    s_battery=label(screen,176,23,45,22,&lv_font_montserrat_14);
    lv_obj_set_style_text_align(s_battery,LV_TEXT_ALIGN_RIGHT,0); muted(s_battery);
    for (int i=0;i<5;++i) s_pages[i]=page(screen);
    s_pet=lv_image_create(s_pages[0]); lv_obj_set_pos(s_pet,48,16);
    s_pet_name=label(s_pages[0],16,178,208,24,&cp_font16); center(s_pet_name);
    s_pet_note=label(s_pages[0],16,207,208,24,&cp_font16); center(s_pet_note); muted(s_pet_note);
    s_pet_image.header.magic=LV_IMAGE_HEADER_MAGIC;
    s_pet_image.header.cf=LV_COLOR_FORMAT_RGB565;
    s_pet_image.header.w=144; s_pet_image.header.h=156; s_pet_image.header.stride=288;
    s_pet_image.data_size=44928;

    s_period=label(s_pages[1],20,0,200,26,&cp_font16); center(s_period); muted(s_period);
    s_ring=lv_arc_create(s_pages[1]); lv_obj_set_pos(s_ring,28,29); lv_obj_set_size(s_ring,184,184);
    lv_arc_set_rotation(s_ring,270); lv_arc_set_bg_angles(s_ring,0,360); lv_arc_set_range(s_ring,0,100);
    lv_obj_remove_style(s_ring,NULL,LV_PART_KNOB); lv_obj_remove_flag(s_ring,LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_arc_width(s_ring,8,LV_PART_MAIN); lv_obj_set_style_arc_width(s_ring,8,LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(s_ring,lv_color_hex(0xe7e8ed),LV_PART_MAIN);
    lv_obj_set_style_arc_color(s_ring,lv_color_hex(0x007aff),LV_PART_INDICATOR);
    s_number=label(s_pages[1],35,80,170,73,&cp_digits58); center(s_number);
    s_reset=label(s_pages[1],20,211,200,22,&cp_font16); center(s_reset); muted(s_reset);
    s_fresh=label(s_pages[1],35,153,170,22,&cp_font16); center(s_fresh); muted(s_fresh);

    s_bar=lv_obj_create(s_pages[2]); lv_obj_remove_style_all(s_bar);
    lv_obj_set_pos(s_bar,20,9); lv_obj_set_size(s_bar,4,23);
    lv_obj_set_style_bg_opa(s_bar,LV_OPA_COVER,0); lv_obj_set_style_radius(s_bar,2,0);
    s_kind=label(s_pages[2],34,8,187,29,&cp_font20);
    s_title=label(s_pages[2],20,59,200,75,&cp_font16);
    s_note=label(s_pages[2],20,145,200,51,&cp_font16); muted(s_note);
    s_position=label(s_pages[2],20,209,200,22,&cp_font16); muted(s_position);

    s_voice_title=label(s_pages[3],18,29,204,31,&cp_font20); center(s_voice_title);
    s_duration=label(s_pages[3],25,80,190,72,&cp_digits58); center(s_duration);
    s_spinner=lv_spinner_create(s_pages[3]); lv_obj_set_pos(s_spinner,81,85); lv_obj_set_size(s_spinner,78,78);
    lv_obj_set_style_arc_width(s_spinner,4,LV_PART_MAIN); lv_obj_set_style_arc_width(s_spinner,4,LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(s_spinner,lv_color_hex(0xe7e8ed),LV_PART_MAIN);
    lv_obj_set_style_arc_color(s_spinner,lv_color_hex(0x007aff),LV_PART_INDICATOR);
    static const lv_point_precise_t check_points[]={{0,25},{18,43},{52,0}};
    s_check=lv_line_create(s_pages[3]); lv_obj_set_pos(s_check,94,98);
    lv_line_set_points(s_check,check_points,3); lv_obj_set_style_line_width(s_check,6,0);
    lv_obj_set_style_line_rounded(s_check,true,0); lv_obj_set_style_line_color(s_check,lv_color_hex(0x007aff),0);
    s_meter=lv_bar_create(s_pages[3]); lv_obj_set_pos(s_meter,66,164); lv_obj_set_size(s_meter,108,5);
    lv_bar_set_range(s_meter,0,100); lv_obj_set_style_bg_color(s_meter,lv_color_hex(0x007aff),LV_PART_INDICATOR);
    s_voice_note=label(s_pages[3],18,191,204,43,&cp_font16); center(s_voice_note); muted(s_voice_note);
    s_menu_title=label(s_pages[4],20,10,200,32,&cp_font20);
    s_menu_body=label(s_pages[4],20,62,200,154,&cp_font16);
    lv_obj_set_style_text_line_space(s_menu_body,13,0);

    s_footer=label(screen,16,287,208,22,&cp_font16); center(s_footer); muted(s_footer);
    s_toast=label(screen,10,260,220,24,&cp_font16); center(s_toast);
    lv_obj_set_style_bg_color(s_toast,lv_color_hex(0xe8f1ff),0); lv_obj_set_style_bg_opa(s_toast,LV_OPA_COVER,0);
    lv_obj_set_style_radius(s_toast,8,0);
    lv_screen_load(screen); bsp_lvgl_unlock();
}
void cp_ui_render(const cp_model_t *m, uint32_t passkey, int battery, bool audio,
                  int menu, int selection, const char *toast, bool asleep, int quota,
                  const cp_voice_view_t *voice, uint64_t now)
{
    if (!s_ring || !bsp_lvgl_lock(100)) return;
    const uint8_t *dynamic=cp_pet_current();
    if (dynamic!=s_dynamic_pet) {
        s_dynamic_pet=dynamic;s_last_pet=-1;
        s_pet_image.data=dynamic?dynamic:pet_frames_start;
        lv_image_set_src(s_pet,&s_pet_image);lv_obj_invalidate(s_pet);
    }
    char temp[256], body[256];
    bool speaking=voice->phase!=CP_VOICE_IDLE;
    int p=passkey || menu ? 4 : speaking ? 3 : asleep ? 0 : m->count ? 2 : 1;
    for (int i=0;i<5;++i) {
        if (p==i) lv_obj_remove_flag(s_pages[i],LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(s_pages[i],LV_OBJ_FLAG_HIDDEN);
    }
    snprintf(temp,sizeof(temp),battery<0 ? "--" : "%d%%",battery); text(s_battery,temp);
    text(s_status,!m->online ? "CODEX / OFFLINE" : (m->muted || !m->enabled) ? "CODEX / QUIET" : "CODEX");
    text(s_footer,p==0 ? "任意键唤醒" : p==3 ? "松开确认键结束" : "按住确认键讲话");
    if (toast && toast[0]) { text(s_toast,toast); lv_obj_remove_flag(s_toast,LV_OBJ_FLAG_HIDDEN); }
    else lv_obj_add_flag(s_toast,LV_OBJ_FLAG_HIDDEN);
    if (p==0) {
        int base=0, frames=6;
        if (m->count) {
            cp_phrase_t kind=m->alerts[m->selected].kind;
            base=kind==CP_BLOCKED ? 24 : kind==CP_APPROVAL || kind==CP_QUESTION ? 18 : 12;
            frames=kind==CP_BLOCKED ? 8 : 6;
            if (dynamic) {base=kind==CP_BLOCKED?14:kind==CP_APPROVAL || kind==CP_QUESTION?12:10;frames=2;}
        } else if (m->running) {base=6;frames=dynamic?4:6;}
        /* A brief original idle animation every five seconds; otherwise calm. */
        int f=base+(int)((now%6000)/160);
        if (f>=base+frames) f=base;
        if (f!=s_last_pet) {
            s_pet_image.data=(dynamic?dynamic:pet_frames_start)+(size_t)f*44928;
            lv_image_set_src(s_pet,&s_pet_image); lv_obj_invalidate(s_pet); s_last_pet=f;
        }
        text(s_pet_name,m->pet_name);
        text(s_pet_note,m->count ? "有事项等你处理" : m->running ? "任务进行中" : "陪你工作");
    } else if (p==1) {
        const cp_quota_t *q=quota>=0 && quota<m->quota_count ? &m->quotas[quota] : NULL;
        int remaining=m->online && q ? q->remaining : -1;
        int elapsed=m->online && now>=m->updated_ms ? (int)((now-m->updated_ms)/1000) : 0;
        int reset=q ? q->reset_seconds-elapsed : -1;
        if (q && q->reset_seconds>=0 && reset<=0) remaining=-1;
        if (remaining>=0) snprintf(temp,sizeof(temp),"%d%%",remaining); else snprintf(temp,sizeof(temp),"--");
        text(s_number,temp); lv_arc_set_value(s_ring,remaining<0 ? 0 : remaining);
        lv_obj_set_style_arc_color(s_ring,lv_color_hex(remaining<20 ? 0xff9f0a : 0x007aff),LV_PART_INDICATOR);
        if (!q) snprintf(temp,sizeof(temp),"剩余额度");
        else if (q->minutes==10080) snprintf(temp,sizeof(temp),"每周剩余额度");
        else if (q->minutes>0 && q->minutes%60==0) snprintf(temp,sizeof(temp),"%d小时剩余额度",q->minutes/60);
        else snprintf(temp,sizeof(temp),"当前周期剩余额度");
        text(s_period,temp);
        if (!m->online) text(s_reset,"等待电脑连接");
        else if (remaining<0) text(s_reset,"等待额度同步");
        else if (reset<0) text(s_reset,"重置时间暂不可用");
        else {
            if (reset>=86400) snprintf(temp,sizeof(temp),"%d天%d小时后重置",reset/86400,(reset%86400)/3600);
            else if (reset>=3600) snprintf(temp,sizeof(temp),"%d小时%d分钟后重置",reset/3600,(reset%3600)/60);
            else snprintf(temp,sizeof(temp),"%d分钟后重置",(reset+59)/60);
            text(s_reset,temp);
        }
        if (remaining<0) text(s_fresh,"待更新");
        else if (m->usage_age+elapsed<60) text(s_fresh,"刚刚同步");
        else { snprintf(temp,sizeof(temp),"%d分钟前同步",(m->usage_age+elapsed)/60); text(s_fresh,temp); }
        if (m->quota_count>1) text(s_footer,"上下切换 · 按住讲话");
    } else if (p==2) {
        const cp_alert_t *a=&m->alerts[m->selected];
        static const char *kinds[]={"任务已完成","需要你回答","等待你审批","任务遇到问题","语音提醒测试"};
        static const char *notes[]={"确认键打开电脑中的任务","确认键前往电脑回答","确认键前往电脑审批","确认键前往电脑查看","确认键停止测试提醒"};
        uint32_t color=a->kind==CP_APPROVAL || a->kind==CP_QUESTION ? 0xff9f0a : a->kind==CP_BLOCKED ? 0xff453a : 0x007aff;
        text(s_kind,a->verify ? "等待核验" : a->snoozed ? "稍后提醒" : kinds[a->kind]);
        lv_obj_set_style_text_color(s_kind,lv_color_hex(color),0); lv_obj_set_style_bg_color(s_bar,lv_color_hex(color),0);
        text(s_title,a->title); text(s_note,notes[a->kind]);
        snprintf(temp,sizeof(temp),"%d / %d  ·  上下键切换",m->selected+1,m->total); text(s_position,temp);
    } else if (p==3) {
        static const char *titles[]={"","正在准备","请讲话","正在识别","已输入到电脑","文字已保留","暂时无法听写"};
        text(s_voice_title,titles[voice->phase]);
        bool processing=voice->phase==CP_VOICE_PREPARING || voice->phase==CP_VOICE_PROCESSING;
        if (voice->phase==CP_VOICE_RECORDING) snprintf(temp,sizeof(temp),"00:%02u",(unsigned)((now-voice->since_ms)/1000));
        else snprintf(temp,sizeof(temp),"!");
        text(s_duration,temp);
        if (processing || voice->phase==CP_VOICE_DONE) lv_obj_add_flag(s_duration,LV_OBJ_FLAG_HIDDEN);
        else lv_obj_remove_flag(s_duration,LV_OBJ_FLAG_HIDDEN);
        if (processing) lv_obj_remove_flag(s_spinner,LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(s_spinner,LV_OBJ_FLAG_HIDDEN);
        if (voice->phase==CP_VOICE_DONE) lv_obj_remove_flag(s_check,LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(s_check,LV_OBJ_FLAG_HIDDEN);
        if (voice->phase==CP_VOICE_RECORDING && voice->target[0]) {
            snprintf(temp,sizeof(temp),"输入到 %s\n保持按住 · 松开结束",voice->target); text(s_voice_note,temp);
        } else text(s_voice_note,voice->message[0] ? voice->message : voice->phase==CP_VOICE_RECORDING ? "保持按住 · 松开结束" : voice->phase==CP_VOICE_PREPARING ? "听到开始音后再讲话" : "请稍候");
        lv_bar_set_value(s_meter,voice->phase==CP_VOICE_RECORDING ? voice->level : 0,LV_ANIM_OFF);
        text(s_footer,voice->phase==CP_VOICE_RECORDING ? "最长30秒 · 松开结束" : "按住确认键讲话");
    } else {
        if (passkey) {
            text(s_menu_title,"蓝牙配对");
            snprintf(body,sizeof(body),"%06u\n在 Mac 配对窗口输入\n上面的六位数字",(unsigned)passkey);
        } else if (menu==2) {
            text(s_menu_title,"重新配对？"); snprintf(body,sizeof(body),"确认后清除当前配对\n上下键取消");
        } else {
            static const char *items[]={"返回","稍后5分钟","重播提醒","静音15分钟","重新配对"};
            text(s_menu_title,"工牌操作"); body[0]=0;
            int start=selection/4*4;
            for (int i=start;i<start+4 && i<5;++i) {
                snprintf(temp,sizeof(temp),"%s%s%s",i==selection ? "> " : "  ",items[i],i<4 ? "\n" : "");
                strncat(body,temp,sizeof(body)-strlen(body)-1);
            }
        }
        text(s_menu_body,body); text(s_footer,passkey ? "配对后自动连接" : "上下选择 · 确认执行");
    }
    (void)audio; bsp_lvgl_unlock();
}
