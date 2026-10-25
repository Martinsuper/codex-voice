#include "companion_pet.h"
#include "companion_ble.h"
#include "esp_partition.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "mbedtls/sha256.h"
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

typedef struct {int kind;uint8_t id[8],sha[32];size_t length;uint8_t data[CP_PET_PACKET_MAX];} job_t;
static const esp_partition_t *s_partition;
static QueueHandle_t s_jobs;
static cp_pet_store_t s_store;
static atomic_bool s_busy;
static atomic_int s_pending=-1;
static int s_visible=-1;
static uint8_t s_id[8];
static bool erase(void *ctx,size_t offset,size_t size) {return esp_partition_erase_range(ctx,offset,size)==ESP_OK;}
static bool write(void *ctx,size_t offset,const void *data,size_t size) {return esp_partition_write(ctx,offset,data,size)==ESP_OK;}
static bool hash(const uint8_t *data,size_t size,uint8_t out[32]) {return mbedtls_sha256(data,size,out,0)==0;}
static void reply(const char *state)
{
    char id[17],sha[65]="",frame[256];cp_pet_hex(s_id,8,id);
    if (s_store.active>=0) cp_pet_hex(s_store.meta[s_store.active].sha,32,sha);
    snprintf(frame,sizeof(frame),"{\"v\":1,\"type\":\"pet_ack\",\"id\":\"%s\",\"state\":\"%s\",\"offset\":%u,\"sha\":\"%s\"}",id,state,(unsigned)s_store.received,sha);
    (void)cp_ble_send(frame);
}
static void worker(void *unused)
{
    (void)unused;job_t job;
    for (;;) {
        if (xQueueReceive(s_jobs,&job,portMAX_DELAY)!=pdTRUE) continue;
        while (atomic_load(&s_busy)) vTaskDelay(pdMS_TO_TICKS(25));
        if (job.kind==0) {
            memcpy(s_id,job.id,8);
            if (atomic_load(&s_pending)>=0) {reply("busy");continue;}
            int result=cp_pet_store_begin(&s_store,job.sha);
            reply(result==1?"current":result==0?"ready":"error");
        } else if (memcmp(s_id,job.id,8)) continue;
        else if (job.kind==1) {
            uint8_t id[8];uint32_t offset;
            if (!cp_pet_packet(job.data,job.length,id,&offset)) continue;
            bool ok=cp_pet_store_data(&s_store,offset,job.data+CP_PET_PACKET_HEADER,job.length-CP_PET_PACKET_HEADER);
            reply(ok?"progress":"retry");
        } else if (job.kind==2) {
            bool ok=cp_pet_store_commit(&s_store);
            if (ok) atomic_store_explicit(&s_pending,s_store.active,memory_order_release);
            reply(ok?"complete":"error");
        }
    }
}
bool cp_pet_init(void)
{
    s_partition=esp_partition_find_first(ESP_PARTITION_TYPE_DATA,0x40,"pet_assets");
    if (!s_partition || s_partition->size!=CP_PET_SLOT_SIZE*2) return false;
    const void *mapped;esp_partition_mmap_handle_t handle;
    if (esp_partition_mmap(s_partition,0,s_partition->size,ESP_PARTITION_MMAP_DATA,&mapped,&handle)!=ESP_OK) return false;
    cp_pet_io_t io={.context=(void *)s_partition,.mapped=mapped,.erase=erase,.write=write,.hash=hash};
    cp_pet_store_init(&s_store,io);s_visible=s_store.active;
    s_jobs=xQueueCreate(8,sizeof(job_t));
    if (!s_jobs || xTaskCreate(worker,"codex_pet",4096,NULL,3,NULL)!=pdPASS) {
        if (s_jobs) vQueueDelete(s_jobs);
        s_jobs=NULL;esp_partition_munmap(handle);s_partition=NULL;return false;
    }
    return true;
}
bool cp_pet_supported(void) {return s_jobs!=NULL;}
void cp_pet_set_busy(bool busy) {atomic_store(&s_busy,busy);}
bool cp_pet_begin(const char *id,const char *sha)
{
    job_t job={.kind=0};
    return s_jobs && cp_pet_unhex(id,8,job.id) && cp_pet_unhex(sha,32,job.sha) && xQueueSend(s_jobs,&job,0)==pdTRUE;
}
bool cp_pet_commit(const char *id)
{
    job_t job={.kind=2};return s_jobs && cp_pet_unhex(id,8,job.id) && xQueueSend(s_jobs,&job,0)==pdTRUE;
}
bool cp_pet_receive(const uint8_t *data,size_t length)
{
    job_t job={.kind=1,.length=length};uint32_t offset;
    if (!s_jobs || !cp_pet_packet(data,length,job.id,&offset)) return false;
    memcpy(job.data,data,length);return xQueueSend(s_jobs,&job,0)==pdTRUE;
}
const uint8_t *cp_pet_current(void)
{
    int next=atomic_exchange_explicit(&s_pending,-1,memory_order_acq_rel);
    if (next>=0) s_visible=next;
    return s_jobs && s_visible>=0?s_store.io.mapped+(size_t)s_visible*CP_PET_SLOT_SIZE+CP_PET_DATA_OFFSET:NULL;
}
void cp_pet_current_hash(char out[65])
{
    out[0]=0;
    if (s_jobs && s_visible>=0) cp_pet_hex(s_store.meta[s_visible].sha,32,out);
}
