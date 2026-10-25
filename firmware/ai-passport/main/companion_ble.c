#include "companion_ble.h"
#include "companion_model.h"
#include "companion_pet.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "host/ble_hs.h"
#include "host/ble_gap.h"
#include "host/ble_att.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "store/config/ble_store_config.h"
#include <stdio.h>
#include <string.h>

static const char *TAG = "codex_ble";
static QueueHandle_t s_frames;
static SemaphoreHandle_t s_tx_lock;
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static uint16_t s_conn = BLE_HS_CONN_HANDLE_NONE, s_tx_handle, s_voice_handle;
static bool s_secure, s_subscribed, s_voice_subscribed;
static uint32_t s_passkey;
static uint8_t s_addr_type;
static char s_name[24];
static cp_line_t s_line;
static const ble_uuid128_t s_service = BLE_UUID128_INIT(
    0x01,0xa0,0x32,0xb9,0x79,0x6d,0x01,0x95,0xef,0x47,0x2b,0x4e,0x01,0xf0,0x37,0xea);
static const ble_uuid128_t s_rx = BLE_UUID128_INIT(
    0x01,0xa0,0x32,0xb9,0x79,0x6d,0x01,0x95,0xef,0x47,0x2b,0x4e,0x02,0xf0,0x37,0xea);
static const ble_uuid128_t s_tx = BLE_UUID128_INIT(
    0x01,0xa0,0x32,0xb9,0x79,0x6d,0x01,0x95,0xef,0x47,0x2b,0x4e,0x03,0xf0,0x37,0xea);
static const ble_uuid128_t s_voice = BLE_UUID128_INIT(
    0x01,0xa0,0x32,0xb9,0x79,0x6d,0x01,0x95,0xef,0x47,0x2b,0x4e,0x04,0xf0,0x37,0xea);
static const ble_uuid128_t s_asset = BLE_UUID128_INIT(
    0x01,0xa0,0x32,0xb9,0x79,0x6d,0x01,0x95,0xef,0x47,0x2b,0x4e,0x05,0xf0,0x37,0xea);
void ble_store_config_init(void);
static int gap_event(struct ble_gap_event *event, void *arg);

bool cp_ble_ready(void)
{
    portENTER_CRITICAL(&s_lock);
    bool ready = s_secure && s_subscribed && s_conn != BLE_HS_CONN_HANDLE_NONE;
    portEXIT_CRITICAL(&s_lock);
    return ready;
}
bool cp_ble_voice_ready(void)
{
    portENTER_CRITICAL(&s_lock);
    bool ready = s_secure && s_voice_subscribed && s_conn != BLE_HS_CONN_HANDLE_NONE;
    portEXIT_CRITICAL(&s_lock);
    return ready;
}
uint32_t cp_ble_passkey(void)
{
    portENTER_CRITICAL(&s_lock);
    uint32_t value = s_passkey;
    portEXIT_CRITICAL(&s_lock);
    return value;
}
static void on_line(const char *line, void *unused)
{
    (void)unused;
    if (s_frames && xQueueSend(s_frames, line, 0) != pdTRUE)
        ESP_LOGW(TAG, "RX queue full; frame rejected");
}
static int access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    (void)attr; (void)arg;
    struct ble_gap_conn_desc desc;
    if (ble_gap_conn_find(conn, &desc) != 0 || !desc.sec_state.encrypted ||
        !desc.sec_state.authenticated || desc.sec_state.key_size != 16)
        return BLE_ATT_ERR_INSUFFICIENT_AUTHEN;
    if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
        const uint16_t total = OS_MBUF_PKTLEN(ctxt->om);
        if (ble_uuid_cmp(ctxt->chr->uuid,&s_asset.u)==0) {
            uint8_t packet[CP_PET_PACKET_MAX];
            if (total>sizeof(packet) || os_mbuf_copydata(ctxt->om,0,total,packet)) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
            return cp_pet_receive(packet,total)?0:BLE_ATT_ERR_INSUFFICIENT_RES;
        }
        uint8_t chunk[128];
        for (uint16_t offset = 0; offset < total;) {
            uint16_t length = total - offset;
            if (length > sizeof(chunk)) length = sizeof(chunk);
            if (os_mbuf_copydata(ctxt->om, offset, length, chunk)) return BLE_ATT_ERR_UNLIKELY;
            cp_line_feed(&s_line, chunk, length, on_line, NULL);
            offset += length;
        }
    }
    return 0;
}
static const struct ble_gatt_svc_def s_services[] = {
    {.type = BLE_GATT_SVC_TYPE_PRIMARY, .uuid = &s_service.u,
     .characteristics = (struct ble_gatt_chr_def[]) {
         {.uuid = &s_rx.u, .access_cb = access,
          .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_ENC | BLE_GATT_CHR_F_WRITE_AUTHEN},
         {.uuid = &s_tx.u, .access_cb = access, .val_handle = &s_tx_handle,
          .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC | BLE_GATT_CHR_F_READ_AUTHEN |
                   BLE_GATT_CHR_F_NOTIFY | BLE_GATT_CHR_F_NOTIFY_INDICATE_ENC},
         {.uuid = &s_voice.u, .access_cb = access, .val_handle = &s_voice_handle,
          .flags = BLE_GATT_CHR_F_NOTIFY | BLE_GATT_CHR_F_NOTIFY_INDICATE_ENC},
         {.uuid = &s_asset.u, .access_cb = access,
          .flags = BLE_GATT_CHR_F_WRITE_NO_RSP | BLE_GATT_CHR_F_WRITE_ENC | BLE_GATT_CHR_F_WRITE_AUTHEN},
         {0}}},
    {0}
};

static int advertise(void)
{
    struct ble_hs_adv_fields fields = {0}, response = {0};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.uuids128 = (ble_uuid128_t *)&s_service;
    fields.num_uuids128 = 1; fields.uuids128_is_complete = 1;
    response.name = (uint8_t *)s_name; response.name_len = strlen(s_name); response.name_is_complete = 1;
    int rc = ble_gap_adv_set_fields(&fields);
    if (!rc) rc = ble_gap_adv_rsp_set_fields(&response);
    struct ble_gap_adv_params params = {0};
    params.conn_mode = BLE_GAP_CONN_MODE_UND; params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    if (!rc) rc = ble_gap_adv_start(s_addr_type, NULL, BLE_HS_FOREVER, &params, gap_event, NULL);
    if (rc) ESP_LOGE(TAG, "advertising failed: %d", rc);
    return rc;
}
static int gap_event(struct ble_gap_event *event, void *arg)
{
    (void)arg;
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status) return advertise();
        portENTER_CRITICAL(&s_lock);
        s_conn = event->connect.conn_handle;
        s_secure = false; s_subscribed = false; s_voice_subscribed = false; s_passkey = 0;
        portEXIT_CRITICAL(&s_lock);
        memset(&s_line, 0, sizeof(s_line));
        (void)ble_gap_security_initiate(event->connect.conn_handle);
        struct ble_gap_upd_params params = {.itvl_min = 12, .itvl_max = 24,
            .latency = 0, .supervision_timeout = 400, .min_ce_len = 0, .max_ce_len = 0};
        (void)ble_gap_update_params(event->connect.conn_handle, &params);
        break;
    case BLE_GAP_EVENT_DISCONNECT:
        portENTER_CRITICAL(&s_lock);
        s_conn = BLE_HS_CONN_HANDLE_NONE; s_secure = false; s_subscribed = false; s_voice_subscribed = false; s_passkey = 0;
        portEXIT_CRITICAL(&s_lock);
        memset(&s_line, 0, sizeof(s_line));
        return advertise();
    case BLE_GAP_EVENT_ENC_CHANGE: {
        struct ble_gap_conn_desc desc = {0};
        bool valid = event->enc_change.status == 0 &&
                     ble_gap_conn_find(event->enc_change.conn_handle, &desc) == 0 &&
                     desc.sec_state.encrypted && desc.sec_state.authenticated && desc.sec_state.key_size == 16;
        portENTER_CRITICAL(&s_lock);
        s_secure = valid;
        if (valid) s_passkey = 0;
        portEXIT_CRITICAL(&s_lock);
        if (!valid) (void)ble_gap_terminate(event->enc_change.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
        break;
    }
    case BLE_GAP_EVENT_SUBSCRIBE:
        portENTER_CRITICAL(&s_lock);
        if (event->subscribe.attr_handle == s_tx_handle) s_subscribed = event->subscribe.cur_notify;
        if (event->subscribe.attr_handle == s_voice_handle) s_voice_subscribed = event->subscribe.cur_notify;
        portEXIT_CRITICAL(&s_lock);
        break;
    case BLE_GAP_EVENT_PASSKEY_ACTION:
        if (event->passkey.params.action == BLE_SM_IOACT_DISP) {
            uint32_t value = 100000 + esp_random() % 900000;
            portENTER_CRITICAL(&s_lock);
            s_passkey = value;
            portEXIT_CRITICAL(&s_lock);
            struct ble_sm_io io = {.action = BLE_SM_IOACT_DISP, .passkey = value};
            return ble_sm_inject_io(event->passkey.conn_handle, &io);
        }
        return BLE_HS_ENOTSUP;
    case BLE_GAP_EVENT_REPEAT_PAIRING:
        // Deleting a prior bond requires the on-device confirmation menu.
        return BLE_GAP_REPEAT_PAIRING_IGNORE;
    case BLE_GAP_EVENT_ADV_COMPLETE:
        return advertise();
    default: break;
    }
    return 0;
}
static void on_sync(void)
{
    if (ble_hs_util_ensure_addr(0) == 0 && ble_hs_id_infer_auto(0, &s_addr_type) == 0)
        (void)advertise();
}
static void on_reset(int reason)
{
    portENTER_CRITICAL(&s_lock);
    s_secure = false; s_subscribed = false; s_voice_subscribed = false; s_conn = BLE_HS_CONN_HANDLE_NONE; s_passkey = 0;
    portEXIT_CRITICAL(&s_lock);
    ESP_LOGW(TAG, "host reset: %d", reason);
}
static void host_task(void *arg)
{
    (void)arg;
    nimble_port_run();
    vTaskDelete(NULL);
}
esp_err_t cp_ble_init(QueueHandle_t frames)
{
    s_frames = frames;
    s_tx_lock = xSemaphoreCreateMutex();
    if (!s_tx_lock) return ESP_ERR_NO_MEM;
    esp_err_t err = nimble_port_init();
    if (err != ESP_OK) return err;
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_BT));
    snprintf(s_name, sizeof(s_name), "Codex-%02X%02X", mac[4], mac[5]);
    ble_hs_cfg.reset_cb = on_reset; ble_hs_cfg.sync_cb = on_sync;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    ble_hs_cfg.sm_io_cap = BLE_SM_IO_CAP_DISP_ONLY;
    ble_hs_cfg.sm_bonding = 1; ble_hs_cfg.sm_mitm = 1;
    ble_hs_cfg.sm_sc = 1; ble_hs_cfg.sm_sc_only = 1; ble_hs_cfg.sm_sec_lvl = 4;
    ble_hs_cfg.sm_our_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    (void)ble_att_set_preferred_mtu(247);
    ble_svc_gap_init(); ble_svc_gatt_init(); ble_store_config_init();
    int rc = ble_svc_gap_device_name_set(s_name);
    if (!rc) rc = ble_gatts_count_cfg(s_services);
    if (!rc) rc = ble_gatts_add_svcs(s_services);
    if (rc) return ESP_FAIL;
    if (xTaskCreate(host_task, "codex_ble", 6144, NULL, configMAX_PRIORITIES - 4, NULL) != pdPASS)
        return ESP_ERR_NO_MEM;
    return ESP_OK;
}
bool cp_ble_send(const char *json)
{
    if (!json || strlen(json) > 500 || !cp_ble_ready()) return false;
    if (xSemaphoreTake(s_tx_lock, pdMS_TO_TICKS(150)) != pdTRUE) return false;
    portENTER_CRITICAL(&s_lock);
    uint16_t conn = s_conn;
    portEXIT_CRITICAL(&s_lock);
    char line[512];
    int length = snprintf(line, sizeof(line), "%s\n", json);
    size_t mtu = ble_att_mtu(conn);
    size_t limit = mtu > 3 ? mtu - 3 : 20;
    bool ok = length > 0 && (size_t)length < sizeof(line);
    for (size_t offset = 0; ok && offset < (size_t)length;) {
        size_t bytes = (size_t)length - offset;
        if (bytes > limit) bytes = limit;
        int rc = BLE_HS_ENOMEM;
        for (int retry = 0; retry < 3 && rc; ++retry) {
            struct os_mbuf *buffer = ble_hs_mbuf_from_flat(line + offset, bytes);
            if (buffer) rc = ble_gatts_notify_custom(conn, s_tx_handle, buffer);
            if (rc) vTaskDelay(pdMS_TO_TICKS(10));
        }
        if (rc) ok = false;
        offset += bytes;
    }
    xSemaphoreGive(s_tx_lock);
    return ok;
}
void cp_ble_unpair(void)
{
    portENTER_CRITICAL(&s_lock);
    uint16_t conn = s_conn;
    s_secure = false; s_subscribed = false; s_voice_subscribed = false;
    portEXIT_CRITICAL(&s_lock);
    if (conn != BLE_HS_CONN_HANDLE_NONE) (void)ble_gap_terminate(conn, BLE_ERR_REM_USER_CONN_TERM);
    int rc = ble_store_clear();
    ESP_LOGI(TAG, "User-requested bond clear: %d", rc);
}

bool cp_ble_send_voice(const uint8_t *data, size_t length)
{
    if (!data || !length || length > 180 || !cp_ble_voice_ready()) return false;
    if (xSemaphoreTake(s_tx_lock, pdMS_TO_TICKS(50)) != pdTRUE) return false;
    portENTER_CRITICAL(&s_lock);
    uint16_t conn = s_conn;
    portEXIT_CRITICAL(&s_lock);
    size_t mtu = ble_att_mtu(conn), limit = mtu > 3 ? mtu - 3 : 20;
    bool ok = true;
    for (size_t offset = 0; ok && offset < length;) {
        size_t count = length - offset;
        if (count > limit) count = limit;
        int rc = BLE_HS_ENOMEM;
        for (int retry = 0; retry < 4 && rc; ++retry) {
            struct os_mbuf *buffer = ble_hs_mbuf_from_flat(data + offset, count);
            if (buffer) rc = ble_gatts_notify_custom(conn, s_voice_handle, buffer);
            if (rc) vTaskDelay(pdMS_TO_TICKS(3));
        }
        if (rc) ok = false;
        offset += count;
    }
    xSemaphoreGive(s_tx_lock);
    return ok;
}
