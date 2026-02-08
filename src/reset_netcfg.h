/**
 * @file reset_netcfg.h
 * @brief Network configuration reset functionality for e-Paper Album
 *
 * @copyright Copyright (c) 2025 Tuya Inc. All Rights Reserved.
 */

#ifndef SRC_RESET_NETCFG_H_
#define SRC_RESET_NETCFG_H_

#include "tal_api.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Starts the network configuration reset process
 * @return int Returns 0 on success, or a negative value on failure
 */
int reset_netconfig_start(void);

/**
 * @brief Checks the status of the network configuration reset process
 * @return int Returns 0 on success, or a negative value on failure
 */
int reset_netconfig_check(void);

#ifdef __cplusplus
}
#endif

#endif /* SRC_RESET_NETCFG_H_ */
