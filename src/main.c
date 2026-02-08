/**
 * @file main.c
 * @brief e-Paper Album Main Entry - Tuya IoT + Network Mode
 *
 * This file follows the switch_demo pattern for Tuya IoT initialization
 * and network configuration.
 *
 * @copyright Copyright (c) 2025 Tuya Inc. All Rights Reserved.
 */

#include <stdlib.h>
#include <signal.h>
#include "EPD_Test.h"
#include "tuya_config.h"
#include "tuya_iot.h"
#include "tuya_iot_dp.h"
#include "cJSON.h"
#include "reset_netcfg.h"
#include "netmgr.h"
#include "netconn_wifi.h"

/* Tuya device handle */
tuya_iot_client_t g_client;

/* Device status - shared with EPD_Album.c */
volatile bool g_wifi_connected = false;
volatile bool g_tuya_mqtt_connected = false;
volatile bool g_refresh_trigger = false;  // Trigger from Tuya App

/* Server IP - pending (received from App, not confirmed) */
static uint8_t g_server_ip_pending[4] = {192, 168, 1, 15};

/* Server IP - active (confirmed and saved, used by EPD_Album.c) */
uint8_t g_server_ip_active[4] = {192, 168, 1, 15};

/* Tuya thread handle */
static THREAD_HANDLE ty_app_thread = NULL;

/* Application version */
#ifndef PROJECT_VERSION
#define PROJECT_VERSION "1.0.0"
#endif

/**
 * @brief User defined log output callback
 */
void user_log_output_cb(const char *str)
{
    tkl_log_output(str);
}

/**
 * @brief User defined upgrade notify callback
 */
void user_upgrade_notify_on(tuya_iot_client_t *client, cJSON *upgrade)
{
    PR_INFO("----- Upgrade Information -----");
    cJSON *item = NULL;
    if (upgrade) {
        item = cJSON_GetObjectItem(upgrade, "type");
        if (item) {
            PR_INFO("OTA Channel: %d", item->valueint);
        }
        item = cJSON_GetObjectItem(upgrade, "version");
        if (item) {
            PR_INFO("Version: %s", item->valuestring);
        }
        item = cJSON_GetObjectItem(upgrade, "size");
        if (item) {
            PR_INFO("Size: %s", item->valuestring);
        }
    }
}

/**
 * @brief User defined event handler
 */
void user_event_handler_on(tuya_iot_client_t *client, tuya_event_msg_t *event)
{
    PR_DEBUG("Tuya Event ID:%d", event->id);

    switch (event->id) {
    case TUYA_EVENT_BIND_START:
        PR_INFO("Device Bind Start! Use Tuya App to bind.");
        break;

    case TUYA_EVENT_DIRECT_MQTT_CONNECTED:
        PR_INFO("Direct MQTT Connected!");
        g_tuya_mqtt_connected = true;
        break;

    case TUYA_EVENT_MQTT_CONNECTED:
        PR_INFO("Device MQTT Connected to Tuya Cloud!");
        g_tuya_mqtt_connected = true;

        /* NOTE: DP reporting is intentionally disabled.
         * Direct call to tuya_iot_dp_obj_report causes MemFault.
         * The App can query DP values when needed.
         */
        PR_INFO("MQTT connected. DP reporting disabled (MemFault issue).");
        PR_INFO("App can query server IP via DP read operations.");
        break;

    case TUYA_EVENT_MQTT_DISCONNECT:
        PR_INFO("Device MQTT Disconnected!");
        g_tuya_mqtt_connected = false;
        break;

    case TUYA_EVENT_UPGRADE_NOTIFY:
        user_upgrade_notify_on(client, event->value.asJSON);
        break;

    case TUYA_EVENT_TIMESTAMP_SYNC:
        PR_INFO("Sync timestamp:%d", event->value.asInteger);
        tal_time_set_posix(event->value.asInteger, 1);
        break;

    case TUYA_EVENT_RESET:
        PR_INFO("Device Reset:%d", event->value.asInteger);
        break;

    /* Receive Object DP (control commands from App) */
    case TUYA_EVENT_DP_RECEIVE_OBJ: {
        dp_obj_recv_t *dpobj = event->value.dpobj;
        PR_DEBUG("Receive DP Command, count:%u", dpobj->dpscnt);

        uint32_t i = 0;
        for (i = 0; i < dpobj->dpscnt; i++) {
            dp_obj_t *dp = dpobj->dps + i;

            switch (dp->id) {
            case DP_ID_SERVER_IP_F1:
                if (dp->type == PROP_VALUE) {
                    g_server_ip_pending[0] = dp->value.dp_value & 0xFF;
                    PR_INFO("Pending IP byte 1: %d", g_server_ip_pending[0]);
                }
                break;

            case DP_ID_SERVER_IP_F2:
                if (dp->type == PROP_VALUE) {
                    g_server_ip_pending[1] = dp->value.dp_value & 0xFF;
                    PR_INFO("Pending IP byte 2: %d", g_server_ip_pending[1]);
                }
                break;

            case DP_ID_SERVER_IP_F3:
                if (dp->type == PROP_VALUE) {
                    g_server_ip_pending[2] = dp->value.dp_value & 0xFF;
                    PR_INFO("Pending IP byte 3: %d", g_server_ip_pending[2]);
                }
                break;

            case DP_ID_SERVER_IP_F4:
                if (dp->type == PROP_VALUE) {
                    g_server_ip_pending[3] = dp->value.dp_value & 0xFF;
                    PR_INFO("Pending IP byte 4: %d", g_server_ip_pending[3]);
                }
                break;

            case DP_ID_SERVER_IP_SET:
                if (dp->type == PROP_BOOL && dp->value.dp_bool == true) {
                    PR_INFO("==========================================");
                    PR_INFO("  IP Setting Request Received");
                    PR_INFO("==========================================");
                    PR_INFO("Pending IP configuration:");
                    PR_INFO("  Byte 1 (101): %d", g_server_ip_pending[0]);
                    PR_INFO("  Byte 2 (102): %d", g_server_ip_pending[1]);
                    PR_INFO("  Byte 3 (103): %d", g_server_ip_pending[2]);
                    PR_INFO("  Byte 4 (104): %d", g_server_ip_pending[3]);
                    PR_INFO("  Full IP: %d.%d.%d.%d",
                            g_server_ip_pending[0], g_server_ip_pending[1],
                            g_server_ip_pending[2], g_server_ip_pending[3]);
                    PR_INFO("Active IP before apply:");
                    PR_INFO("  Full IP: %d.%d.%d.%d",
                            g_server_ip_active[0], g_server_ip_active[1],
                            g_server_ip_active[2], g_server_ip_active[3]);

                    /* Apply pending IP to active IP */
                    memcpy(g_server_ip_active, g_server_ip_pending, 4);

                    /* Save to flash */
                    tal_kv_set(KV_KEY_SERVER_IP, g_server_ip_active, 4);
                    PR_INFO("Server IP saved to flash");

                    PR_INFO("Active IP after apply:");
                    PR_INFO("  Full IP: %d.%d.%d.%d",
                            g_server_ip_active[0], g_server_ip_active[1],
                            g_server_ip_active[2], g_server_ip_active[3]);
                    PR_INFO("==========================================");

                    /* Report confirmed IP */
                    {
                        dp_obj_t dps[4] = {0};
                        dps[0].id = DP_ID_SERVER_IP_F1;
                        dps[0].type = PROP_VALUE;
                        dps[0].value.dp_value = g_server_ip_active[0];

                        dps[1].id = DP_ID_SERVER_IP_F2;
                        dps[1].type = PROP_VALUE;
                        dps[1].value.dp_value = g_server_ip_active[1];

                        dps[2].id = DP_ID_SERVER_IP_F3;
                        dps[2].type = PROP_VALUE;
                        dps[2].value.dp_value = g_server_ip_active[2];

                        dps[3].id = DP_ID_SERVER_IP_F4;
                        dps[3].type = PROP_VALUE;
                        dps[3].value.dp_value = g_server_ip_active[3];

                        /* NOTE: DP reporting disabled due to MemFault issue
                         * App will receive updated values on next query
                         */
                        /* tuya_iot_dp_obj_report(client, dpobj->devid, dps, 4, 0); */
                    }
                }
                break;

            case DP_ID_REFRESH:
                if (dp->type == PROP_BOOL && dp->value.dp_bool == true) {
                    PR_INFO("Refresh trigger received!");
                    g_refresh_trigger = true;
                }
                break;

            default:
                PR_DEBUG("Unknown DP id: %d", dp->id);
                break;
            }
        }
    } break;

    default:
        break;
    }
}

/**
 * @brief User defined network check callback
 */
bool user_network_check(void)
{
    netmgr_status_e status = NETMGR_LINK_DOWN;
    netmgr_conn_get(NETCONN_AUTO, NETCONN_CMD_STATUS, &status);
    return status == NETMGR_LINK_DOWN ? false : true;
}

/**
 * @brief Process Tuya SDK events
 * @note Must be called periodically to process WiFi and MQTT events
 */
void user_tuya_yield(void)
{
    tuya_iot_yield(&g_client);
}

/**
 * @brief Main user initialization function
 */
static void user_main(void)
{
    int rt = OPRT_OK;

    /* Initialize log system */
    tal_log_init(TAL_LOG_LEVEL_DEBUG, 1024, (TAL_LOG_OUTPUT_CB)user_log_output_cb);

    PR_NOTICE("========================================");
    PR_NOTICE("  e-Paper Album Starting...");
    PR_NOTICE("  Version: %s", PROJECT_VERSION);
    PR_NOTICE("========================================");

    /* Initialize KV storage */
    tal_kv_init(&(tal_kv_cfg_t){
        .seed = "epd_album_seed",
        .key = "epd_album_key",
    });

    /* Load server IP from flash */
    {
        uint8_t *read_buf = NULL;
        size_t read_len;
        int ret = tal_kv_get(KV_KEY_SERVER_IP, &read_buf, &read_len);
        if (ret == OPRT_OK && read_len >= 4) {
            memcpy(g_server_ip_active, read_buf, 4);
            PR_INFO("Loaded server IP from flash: %d.%d.%d.%d",
                    g_server_ip_active[0], g_server_ip_active[1],
                    g_server_ip_active[2], g_server_ip_active[3]);
        } else {
            PR_INFO("Using default server IP: 192.168.1.15");
        }
        if (read_buf) {
            tal_kv_free(read_buf);
        }
        /* Initialize pending IP to match active */
        memcpy(g_server_ip_pending, g_server_ip_active, 4);
    }

    /* Initialize software timer and workqueue */
    tal_sw_timer_init();
    tal_workq_init();

#if !defined(PLATFORM_UBUNTU) || (PLATFORM_UBUNTU == 0)
    tal_cli_init();
#endif

    /* Start network config reset timer */
    reset_netconfig_start();

    /* Initialize Tuya IoT */
    tuya_iot_license_t license = {
        .uuid = TUYA_OPENSDK_UUID,
        .authkey = TUYA_OPENSDK_AUTHKEY,
    };

    rt = tuya_iot_init(&g_client, &(const tuya_iot_config_t){
                                    .software_ver = PROJECT_VERSION,
                                    .productkey = TUYA_PRODUCT_ID,
                                    .uuid = license.uuid,
                                    .authkey = license.authkey,
                                    .event_handler = user_event_handler_on,
                                    .network_check = user_network_check,
                                });
    if (rt != OPRT_OK) {
        PR_ERR("Tuya IoT init failed: %d", rt);
        return;
    }

    PR_INFO("Tuya IoT initialized successfully");
    PR_INFO("Product ID: %s", TUYA_PRODUCT_ID);

    /* Initialize network manager with WiFi */
    netmgr_type_e type = NETCONN_WIFI;
    netmgr_init(type);

    /* Set network config mode (BLE + AP) for first-time pairing */
    netmgr_conn_set(NETCONN_WIFI, NETCONN_CMD_NETCFG, &(netcfg_args_t){.type = NETCFG_TUYA_BLE | NETCFG_TUYA_WIFI_AP});

    PR_INFO("Network manager initialized, waiting for WiFi connection...");
    PR_INFO("If not paired, use Tuya App to configure WiFi network.");

    /* Start Tuya IoT task */
    tuya_iot_start(&g_client);

    /* Check if need to reset network config */
    reset_netconfig_check();

    /* ========================================================
     * Wait for Tuya Cloud activation and MQTT connection
     * This is critical - without this, device won't be paired
     * ========================================================
     */
    PR_INFO("Waiting for Tuya Cloud activation and MQTT connection...");
    int activation_timeout = 120;  // 120 seconds max
    while (activation_timeout > 0) {
        user_tuya_yield();

        if (g_tuya_mqtt_connected) {
            PR_INFO("Tuya MQTT Connected successfully!");
            break;
        }

        tal_system_sleep(1000);
        activation_timeout--;

        if (activation_timeout % 10 == 0) {
            PR_INFO("Waiting for MQTT... (%ds remaining)", activation_timeout);
        }
    }

    if (!g_tuya_mqtt_connected) {
        PR_ERR("MQTT connection timeout - device may not be paired properly");
        PR_INFO("Note: If this is first pairing, make sure to complete pairing in Tuya App");
    } else {
        /* MQTT connected - give time for events to be fully processed */
        PR_INFO("MQTT connected, processing remaining events...");
        /* Process SDK events for 2 seconds without blocking */
        uint32_t waited = 0;
        while (waited < 2000) {
            user_tuya_yield();
            tal_system_sleep(100);
            waited += 100;
        }
        PR_INFO("Event processing complete, proceeding to EPD_test_net()...");
    }

    /* Run main e-Paper test function */
    PR_INFO("Starting EPD_test_net()...");
    EPD_test_net();
    PR_INFO("EPD_test_net() returned - continuing to process SDK events...");

    /* IMPORTANT: Continue processing SDK events forever
     * This is critical for MQTT keepalive and App communication
     */
    for (;;) {
        user_tuya_yield();
        tal_system_sleep(100);
    }
}

#if OPERATING_SYSTEM == SYSTEM_LINUX
void main(int argc, char *argv[])
{
    user_main();
}
#else

/**
 * @brief Task thread for main function
 */
static void tuya_app_thread(void *arg)
{
    (void)arg;

    PR_DEBUG("App thread started");
    user_main();
    PR_DEBUG("App thread exit");

    tal_thread_delete(ty_app_thread);
    ty_app_thread = NULL;
}

void tuya_app_main(void)
{
    THREAD_CFG_T thrd_param = {4096, 4, "tuya_app_main"};
    tal_thread_create_and_start(&ty_app_thread, NULL, NULL, tuya_app_thread, NULL, &thrd_param);
}
#endif