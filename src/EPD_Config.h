#ifndef _EPD_CONFIG_H_
#define _EPD_CONFIG_H_

#include "tal_api.h"
#include "tkl_output.h"
#include "tal_cli.h"
#include "tkl_spi.h"

// 官方默认
#if 0
#define EPD_PWR_PIN  TUYA_GPIO_NUM_28
#define EPD_BUSY_PIN TUYA_GPIO_NUM_6
#define EPD_RST_PIN  TUYA_GPIO_NUM_8
#define EPD_DC_PIN   TUYA_GPIO_NUM_7
#define EPD_CS_PIN   TUYA_GPIO_NUM_3
#define EPD_SCLK_PIN TUYA_GPIO_NUM_2
#define EPD_MOSI_PIN TUYA_GPIO_NUM_4
#endif

// 自定义
#if 1
#define EPD_PWR_PIN  TUYA_GPIO_NUM_44
#define EPD_BUSY_PIN TUYA_GPIO_NUM_46
#define EPD_RST_PIN  TUYA_GPIO_NUM_19
#define EPD_DC_PIN   TUYA_GPIO_NUM_17
#define EPD_CS_PIN   TUYA_GPIO_NUM_45
#define EPD_SCLK_PIN TUYA_GPIO_NUM_14
#define EPD_MOSI_PIN TUYA_GPIO_NUM_16

#define SPI_ID TUYA_SPI_NUM_0
#endif

#endif // _EPD_CONFIG_H_
