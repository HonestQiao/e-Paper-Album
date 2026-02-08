/**
 * @file tuya_config.h
 * @brief IoT specific configuration file for e-Paper Album
 *
 * @copyright Copyright (c) 2025 Tuya Inc. All Rights Reserved.
 */

#ifndef TUYA_CONFIG_H_
#define TUYA_CONFIG_H_

/**
 * @brief configure the product information
 *
 * TUYA_PRODUCT_ID: PID, create on the Tuya IoT platform
 * TUYA_OPENSDK_UUID: UUID, create on the Tuya IoT platform
 * TUYA_OPENSDK_AUTHKEY: AUTHKEY, create on the Tuya IoT platform
 *
 * detail please refer to:
 * 1. Create the product and get the pid:
 * https://developer.tuya.com/cn/docs/iot-device-dev/application-creation?id=Kbxw7ket3aujc
 * 2. Get the open-sdk license code or module: https://platform.tuya.com/purchase/index?type=6
 *
 * warning: please replace these production information with your product id
 * and license, otherwise the demo cannot work.
 *
 */
// clang-format off
#define TUYA_PRODUCT_ID       "********"
#define TUYA_OPENSDK_UUID     "********"
#define TUYA_OPENSDK_AUTHKEY  "********"
// clang-format on

/**
 * @brief DP ID definition for e-Paper Album
 *
 * DP (Data Point) is the basic unit for data interaction with Tuya Cloud.
 * Each DP has a unique ID and type.
 *
 * Design:
 * - DP_101: server_ip_f1 (value, rw) - Server IP byte 1 (0-255)
 * - DP_102: server_ip_f2 (value, rw) - Server IP byte 2 (0-255)
 * - DP_103: server_ip_f3 (value, rw) - Server IP byte 3 (0-255)
 * - DP_104: server_ip_f4 (value, rw) - Server IP byte 4 (0-255)
 * - DP_105: refresh (bool, wr) - Trigger image update
 * - DP_106: server_ip_set (bool, wr) - Confirm and save IP settings
 */
#define DP_ID_SERVER_IP_F1   101  // Value type, IP byte 1
#define DP_ID_SERVER_IP_F2   102  // Value type, IP byte 2
#define DP_ID_SERVER_IP_F3   103  // Value type, IP byte 3
#define DP_ID_SERVER_IP_F4   104  // Value type, IP byte 4
#define DP_ID_REFRESH        105  // Bool type, trigger image update
#define DP_ID_SERVER_IP_SET  106  // Bool type, confirm and save IP

/**
 * @brief KV key for saved server IP
 */
#define KV_KEY_SERVER_IP    "epd_svr_ip"

/**
 * @brief Enable Tuya Cloud features
 * Set to 1 to enable Tuya IoT cloud features
 */
#ifndef ENABLE_TUYA_IOT
#define ENABLE_TUYA_IOT       1
#endif

#endif // TUYA_CONFIG_H_
