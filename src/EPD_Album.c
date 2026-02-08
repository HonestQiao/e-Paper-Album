/*****************************************************************************
 * | File       :  EPD_Album.c
 * | Author     :   HonestQiao
 * | Function   :   e-Paper Smart Album - Tuya IoT + Network Mode
 * | Info       :   Connect to WiFi, Tuya Cloud for App control, socket server
 *                 for remote image data, display on 4-inch 6-color e-Paper
 *----------------
 * | Version:   V2.0
 * | Changelog   :
 * |                2025-01-21  :   First Version
 * |                2025-02-08  :   Access Tuya IoT platform, support App network configuration
 ******************************************************************************/
#include "EPD_Album.h"
#include "EPD_4in0e.h"
#include "tal_api.h"
#include "tal_network.h"
#include "tal_system.h"
#include "netmgr.h"
#include "tuya_config.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

/***********************************************************
 *                    Socket 配置
 ***********************************************************/
#define SOCKET_SERVER_PORT 18888            // socket服务端口
#define RECV_BUFFER_SIZE   1024
#define LOOP_INTERVAL_MS   180000 // 循环间隔
#define IMAGE_BUFFER_SIZE  120000 // 400x600 屏幕 6 色格式大小 (400*600/2)
#define RLE_LINE_BUFFER_SIZE  512   // RLE 单行解码缓冲区大小
#define RLE_RECV_BUFFER_SIZE 4096   // RLE 接收缓冲区大小

/* 默认服务器地址字节（如果没有从 App 设置） */
#define DEFAULT_SERVER_IP_BYTES  {192, 168, 1, 15}

/* 存储当前使用的服务器 IP 字符串 */
static char g_current_ip_str[32] = {0};

/***********************************************************
 *                    全局变量 (在 main.c 中定义)
 ***********************************************************/
extern volatile bool g_wifi_connected;
extern volatile bool g_refresh_trigger;  // Trigger from Tuya App

/* Server IP - active (confirmed and saved, used for connections) */
extern uint8_t g_server_ip_active[4];

/* Yield function (defined in main.c) */
extern void user_tuya_yield(void);

static volatile bool g_socket_connected = false;

/* RLE 解码静态缓冲区（避免栈溢出） */
static uint8_t g_rle_buffer[RLE_RECV_BUFFER_SIZE];
static uint8_t g_line_buffer[RLE_LINE_BUFFER_SIZE];

/***********************************************************
 *                    函数声明
 ***********************************************************/
static int  socket_send_command(const char *cmd, char *response, int resp_size);
static int  socket_recv_json_response(char *response, int resp_size);
static int  socket_get_image_data(uint8_t *data, uint32_t *data_size);
static int  net_wait_connected(void);
static void print_hex_dump(const uint8_t *data, uint32_t len, uint32_t max_lines);
static uint32_t rle_decode_line(const uint8_t *rle_data, uint32_t rle_len, uint8_t *output, uint32_t out_max);

/***********************************************************
 *                    函数定义
 ***********************************************************/

/**
 * @brief 获取服务器IP字符串
 * @note 从 g_server_ip_active 构造 IP 字符串
 */
static const char *get_server_ip(void)
{
    snprintf(g_current_ip_str, sizeof(g_current_ip_str),
             "%d.%d.%d.%d",
             g_server_ip_active[0],
             g_server_ip_active[1],
             g_server_ip_active[2],
             g_server_ip_active[3]);
    PR_DEBUG("Server IP: %s", g_current_ip_str);
    return g_current_ip_str;
}

/**
 * @brief 等待网络连接
 * @note 使用 netmgr 检查网络状态，不再使用 tal_wifi_* API
 * @return 0 成功, -1 超时失败
 */
static int net_wait_connected(void)
{
    int timeout = 120; // 增加等待时间到120秒（给配网足够时间）

    while (timeout > 0) {
        // 处理 Tuya SDK 事件（必须调用，否则 WiFi 连接事件无法被处理）
        user_tuya_yield();

        // 检查 netmgr 状态
        netmgr_status_e status = NETMGR_LINK_DOWN;
        netmgr_conn_get(NETCONN_AUTO, NETCONN_CMD_STATUS, &status);

        if (status != NETMGR_LINK_DOWN) {
            g_wifi_connected = true;
            PR_INFO("Network connected successfully! (status=%d)", status);
            return 0;
        }

        // 每10秒输出一次状态，减少日志刷屏
        if (timeout % 10 == 0 || timeout <= 10) {
            PR_INFO("Waiting for network connection... (%ds remaining, status=%d)", timeout, status);
        }

        tal_system_sleep(1000);
        timeout--;
    }

    PR_ERR("Network connection timeout - make sure device is paired with Tuya App");
    return -1;
}

/**
 * @brief 通过Socket发送命令并获取响应
 * @param cmd 要发送的命令
 * @param response 接收响应数据的缓冲区
 * @param resp_size 缓冲区大小
 * @return 0 成功, -1 失败
 */
static int socket_send_command(const char *cmd, char *response, int resp_size)
{
    int            fd = -1;
    TUYA_IP_ADDR_T server_addr;
    TUYA_ERRNO     conn_ret;

    if (cmd == NULL || response == NULL || resp_size <= 0) {
        PR_ERR("Invalid parameters");
        return -1;
    }

    // 创建TCP socket
    fd = tal_net_socket_create(PROTOCOL_TCP);
    if (fd < 0) {
        PR_ERR("Socket creation failed");
        return -1;
    }

    // 设置超时
    tal_net_set_timeout(fd, 5000, TRANS_RECV);
    tal_net_set_timeout(fd, 5000, TRANS_SEND);

    // 解析服务器地址
    server_addr = tal_net_str2addr(get_server_ip());
    if (server_addr == 0) {
        PR_ERR("Invalid server IP address");
        tal_net_close(fd);
        return -1;
    }

    // 连接服务器
    conn_ret = tal_net_connect(fd, server_addr, SOCKET_SERVER_PORT);
    if (conn_ret != 0) {
        PR_ERR("Connect to server failed: %d", conn_ret);
        tal_net_close(fd);
        return -1;
    }
    PR_INFO("==========================================");
    PR_INFO("  Connected to Image Server");
    PR_INFO("==========================================");
    PR_INFO("  Server: %s:%d", get_server_ip(), SOCKET_SERVER_PORT);

    // 连接成功后处理SDK事件
    user_tuya_yield();

    // 发送命令
    PR_DEBUG("Sending command: %s", cmd);
    TUYA_ERRNO send_ret = tal_net_send(fd, cmd, strlen(cmd));
    if (send_ret < 0) {
        PR_ERR("Send command failed");
        tal_net_close(fd);
        return -1;
    }

    // 发送完成后处理SDK事件
    user_tuya_yield();

    // 接收响应
    memset(response, 0, resp_size);
    TUYA_ERRNO recv_ret = tal_net_recv(fd, response, resp_size - 1);
    if (recv_ret > 0) {
        response[recv_ret] = '\0';
        PR_DEBUG("Received response: %s", response);
    } else if (recv_ret == 0) {
        PR_DEBUG("Server closed connection");
    } else {
        PR_ERR("Receive response failed: %d", recv_ret);
        tal_net_close(fd);
        return -1;
    }

    // 接收完成后处理SDK事件
    user_tuya_yield();

    // 关闭socket
    tal_net_close(fd);
    g_socket_connected = false;
    PR_INFO("==========================================");

    return 0;
}

/**
 * @brief 在电子纸上显示网络测试结果
 * @param status 状态: 0=成功, -1=失败
 * @param message 显示的消息
 */
static void display_network_result(int status, const char *message)
{
    UBYTE  *BlackImage;
    UDOUBLE Imagesize =
        ((EPD_4IN0E_WIDTH % 2 == 0) ? (EPD_4IN0E_WIDTH / 2) : (EPD_4IN0E_WIDTH / 2 + 1)) * EPD_4IN0E_HEIGHT;

    BlackImage = (UBYTE *)malloc(Imagesize);
    if (BlackImage == NULL) {
        PR_ERR("Failed to allocate memory for display");
        return;
    }

    Paint_NewImage(BlackImage, EPD_4IN0E_WIDTH, EPD_4IN0E_HEIGHT, 0, EPD_4IN0E_WHITE);
    Paint_SelectImage(BlackImage);
    Paint_Clear(EPD_4IN0E_WHITE);

    // 标题
    Paint_DrawString_EN(150, 50, "Network Test", &Font24, status == 0 ? EPD_4IN0E_GREEN : EPD_4IN0E_RED,
                        EPD_4IN0E_WHITE);

    // 状态消息
    Paint_DrawString_EN(50, 120, message, &Font16, EPD_4IN0E_BLACK, EPD_4IN0E_WHITE);

    // 显示结果
    EPD_4IN0E_Display(BlackImage);

    free(BlackImage);
}

/**
 * @brief EPD Album 主函数
 * @note 使用 netmgr 进行网络管理，通过 socket 循环获取数据: update -> info -> get_c
 */
int EPD_Album_main(void)
{
    char response[RECV_BUFFER_SIZE];
    uint8_t *image_buffer = NULL;
    uint32_t image_size = 0;
    uint32_t loop_count = 0;

    PR_NOTICE("========================================");
    PR_NOTICE("  e-Paper Album Network Test");
    PR_NOTICE("========================================");
    PR_DEBUG("Server: %s:%d", get_server_ip(), SOCKET_SERVER_PORT);
    PR_DEBUG("Loop interval: %d ms", LOOP_INTERVAL_MS);

    // ========== 等待网络连接 ==========
    // 网络初始化由 main.c 中的 netmgr 处理，这里只需要等待连接成功
    PR_INFO("Waiting for network connection...");
    if (net_wait_connected() != 0) {
        PR_ERR("Network connection failed - please pair device with Tuya App first");
        return -1;
    }

    PR_DEBUG("Network connected, entering main loop...");

    // ========== 主循环: 每3分钟获取一次数据 ==========
    while (1) {
        loop_count++;
        PR_INFO("==========================================");
        PR_INFO("  Loop #%u", loop_count);
        PR_INFO("==========================================");

        // ========== 第一步: 发送 update 命令 ==========
        PR_DEBUG("Step 1: Sending 'update' command...");
        if (socket_send_command("update", response, sizeof(response)) != 0) {
            PR_ERR("Update command failed, retrying in next cycle");
            // 等待时处理 SDK 事件
            uint32_t wait_done = 0;
            while (wait_done < LOOP_INTERVAL_MS) {
                user_tuya_yield();
                tal_system_sleep(1000);
                wait_done += 1000;
            }
            continue;
        }
        PR_DEBUG("Update response: %s", response);

        // 解析 current_index 和 total
        {
            char *p;
            int current_index = 0;
            int total = 0;

            // 解析 current_index
            p = strstr(response, "\"current_index\"");
            if (p) {
                sscanf(p, "\"current_index\" : %d", &current_index);
            }

            // 解析 total
            p = strstr(response, "\"total\"");
            if (p) {
                sscanf(p, "\"total\" : %d", &total);
            }

            PR_DEBUG("Image index: %d, total: %d", current_index, total);
        }
#if 0
        // ========== 第二步: 发送 info 命令 ==========
        PR_DEBUG("Step 2: Sending 'info' command...");
        if (socket_send_command("info", response, sizeof(response)) != 0) {
            PR_ERR("Info command failed, retrying in next cycle");
            // 等待时处理 SDK 事件
            uint32_t wait_done = 0;
            while (wait_done < LOOP_INTERVAL_MS) {
                user_tuya_yield();
                tal_system_sleep(1000);
                wait_done += 1000;
            }
            continue;
        }
        PR_DEBUG("Info response: %s", response);

        // 解析并显示图片信息
        {
            char  filename[256] = {0};
            int   index = 0, total = 0;
            char *p;

            // 解析 index
            p = strstr(response, "\"index\"");
            if (p) {
                sscanf(p, "\"index\" : %d", &index);
            }

            // 解析 total
            p = strstr(response, "\"total\"");
            if (p) {
                sscanf(p, "\"total\" : %d", &total);
            }

            // 解析 filename
            p = strstr(response, "\"filename\"");
            if (p) {
                char *start = strchr(p, '"');
                char *end   = strchr(start + 1, '"');
                if (start && end && end > start + 1) {
                    int len = end - start - 1;
                    if (len < (int)sizeof(filename) - 1) {
                        memcpy(filename, start + 1, len);
                        filename[len] = '\0';
                    }
                }
            }

            PR_INFO("==========================================");
            PR_INFO("  Image Info:");
            PR_INFO("    Index: %d / %d", index, total);
            PR_INFO("    Filename: %s", filename);
            PR_INFO("==========================================");
        }
#endif
        // ========== 第三步: 发送 get_c 命令获取打包数据（每像素4位） ==========
        PR_DEBUG("Step 3: Sending 'get_c' command...");

        // 分配图片缓冲区
        image_buffer = (uint8_t *)malloc(IMAGE_BUFFER_SIZE);
        if (image_buffer == NULL) {
            PR_ERR("Failed to allocate memory for image");
            // 等待时处理 SDK 事件
            uint32_t wait_done = 0;
            while (wait_done < LOOP_INTERVAL_MS) {
                user_tuya_yield();
                tal_system_sleep(1000);
                wait_done += 1000;
            }
            continue;
        }

        if (socket_get_image_data(image_buffer, &image_size) != 0) {
            PR_ERR("Failed to get image data");
            free(image_buffer);
            image_buffer = NULL;
            // 等待时处理 SDK 事件
            uint32_t wait_done = 0;
            while (wait_done < LOOP_INTERVAL_MS) {
                user_tuya_yield();
                tal_system_sleep(1000);
                wait_done += 1000;
            }
            continue;
        }

        PR_INFO("Image downloaded successfully: %u bytes", image_size);

        // 显示十六进制数据（前20字节）
        PR_DEBUG("Displaying first 20 bytes of image data:");
        print_hex_dump(image_buffer, image_size, 2);

        // ========== 第四步: 显示图片到 e-Paper ==========
        PR_DEBUG("Step 4: Displaying image on e-Paper...");

        // 初始化模块
        if (DEV_Module_Init() != 0) {
            PR_ERR("DEV Module Init failed");
            free(image_buffer);
            image_buffer = NULL;
            // 等待时处理 SDK 事件
            uint32_t wait_done = 0;
            while (wait_done < LOOP_INTERVAL_MS) {
                user_tuya_yield();
                tal_system_sleep(1000);
                wait_done += 1000;
            }
            continue;
        }

        // 初始化屏幕
        EPD_4IN0E_Init();

        // 显示图片 (使用 get_c 返回的 6 色数据)
        EPD_4IN0E_Display_Fast(image_buffer);

        PR_INFO("Image displayed successfully");

        // 注意：EPD_4IN0E_Display_Fast() 内部已经通过 EPD_BUSY_PIN 等待刷新完成
        // 无需额外等待！只需要短暂延时让屏幕完全稳定
        PR_INFO("Waiting briefly for display to stabilize...");
        tal_system_sleep(200);

        // 短暂处理 SDK 事件
        user_tuya_yield();

        // 等待19秒确保屏幕刷新完成
        PR_INFO("Waiting 19s for display refresh to complete...");
        tal_system_sleep(19000);

        // 进入睡眠
        PR_INFO("Calling EPD_4IN0E_Sleep()...");
        EPD_4IN0E_Sleep();
        PR_INFO("EPD_4IN0E_Sleep() completed");

        // 处理SDK事件
        PR_INFO("Processing SDK events (500ms)...");
        user_tuya_yield();
        tal_system_sleep(500);

        // 关闭模块
        PR_INFO("Calling DEV_Module_Exit()...");
        DEV_Module_Exit();
        PR_INFO("DEV_Module_Exit() completed");

        // 释放内存
        PR_INFO("Freeing image buffer...");
        free(image_buffer);
        image_buffer = NULL;
        PR_INFO("Image buffer freed");

        // ========== 等待下一次循环 ==========
        PR_INFO("========== Waiting %d ms for next cycle (Loop #%d) ==========", LOOP_INTERVAL_MS, ++loop_count);

        // 等待时检查是否有来自 App 的刷新触发，同时处理 SDK 事件
        uint32_t waited = 0;
        while (waited < LOOP_INTERVAL_MS) {
            if (g_refresh_trigger) {
                PR_INFO("Refresh trigger from App detected!");
                g_refresh_trigger = false;
                break;  // 立即跳出等待，进入下一次更新
            }
            // 处理 SDK 事件（防止事件队列堆积导致 AP/BLE 异常）
            user_tuya_yield();
            tal_system_sleep(1000);
            waited += 1000;
            // 每30秒输出一次等待进度
            if (waited % 30000 == 0) {
                PR_INFO("Waited %d ms, continuing...", waited);
            }
        }
    }

    PR_DEBUG("========== EPD Network Test End ==========");
    return 0;
}

/**
 * @brief 接收JSON响应（连接复用模式）
 * @param response 接收响应数据的缓冲区
 * @param resp_size 缓冲区大小
 * @return 0 成功, -1 失败
 */
static int socket_recv_json_response(char *response, int resp_size)
{
    int            fd = -1;
    TUYA_IP_ADDR_T server_addr;
    TUYA_ERRNO     conn_ret;

    if (response == NULL || resp_size <= 0) {
        PR_ERR("Invalid parameters");
        return -1;
    }

    // 创建TCP socket
    fd = tal_net_socket_create(PROTOCOL_TCP);
    if (fd < 0) {
        PR_ERR("Socket creation failed");
        return -1;
    }

    // 设置超时
    tal_net_set_timeout(fd, 5000, TRANS_RECV);
    tal_net_set_timeout(fd, 5000, TRANS_SEND);

    // 解析服务器地址
    server_addr = tal_net_str2addr(get_server_ip());
    if (server_addr == 0) {
        PR_ERR("Invalid server IP address");
        tal_net_close(fd);
        return -1;
    }

    // 连接服务器
    conn_ret = tal_net_connect(fd, server_addr, SOCKET_SERVER_PORT);
    if (conn_ret != 0) {
        PR_ERR("Connect to server failed: %d", conn_ret);
        tal_net_close(fd);
        return -1;
    }

    // 接收响应
    memset(response, 0, resp_size);
    TUYA_ERRNO recv_ret = tal_net_recv(fd, response, resp_size - 1);
    if (recv_ret > 0) {
        response[recv_ret] = '\0';
    } else if (recv_ret == 0) {
        PR_DEBUG("Server closed connection");
    } else {
        PR_ERR("Receive response failed: %d", recv_ret);
        tal_net_close(fd);
        return -1;
    }

    // 关闭socket
    tal_net_close(fd);

    return recv_ret > 0 ? 0 : -1;
}

/**
 * @brief 获取图片二进制数据
 * @param data 接收图片数据的缓冲区
 * @param data_size 图片数据大小
 * @return 0 成功, -1 失败
 */
static int socket_get_image_data(uint8_t *data, uint32_t *data_size)
{
    int            fd = -1;
    TUYA_IP_ADDR_T server_addr;
    TUYA_ERRNO     conn_ret;
    uint8_t        header[4];
    uint32_t       image_size = 0;
    uint32_t       received   = 0;

    if (data == NULL || data_size == NULL) {
        PR_ERR("Invalid parameters");
        return -1;
    }

    // 创建TCP socket
    fd = tal_net_socket_create(PROTOCOL_TCP);
    if (fd < 0) {
        PR_ERR("Socket creation failed");
        return -1;
    }

    // 设置超时
    tal_net_set_timeout(fd, 10000, TRANS_RECV);
    tal_net_set_timeout(fd, 5000, TRANS_SEND);

    // 解析服务器地址
    server_addr = tal_net_str2addr(get_server_ip());
    if (server_addr == 0) {
        PR_ERR("Invalid server IP address");
        tal_net_close(fd);
        return -1;
    }

    // 连接服务器
    conn_ret = tal_net_connect(fd, server_addr, SOCKET_SERVER_PORT);
    if (conn_ret != 0) {
        PR_ERR("Connect to server failed: %d", conn_ret);
        tal_net_close(fd);
        return -1;
    }

    PR_INFO("  Server: %s:%d", get_server_ip(), SOCKET_SERVER_PORT);

    // 连接成功后处理SDK事件
    user_tuya_yield();

    // 发送 "get_c" 命令
    TUYA_ERRNO send_ret = tal_net_send(fd, "get_c", 5);
    if (send_ret < 0) {
        PR_ERR("Send command failed");
        tal_net_close(fd);
        return -1;
    }

    // 发送完成后处理SDK事件
    user_tuya_yield();

    // 接收4字节长度头部（大端）
    memset(header, 0, sizeof(header));
    TUYA_ERRNO recv_ret = tal_net_recv(fd, header, 4);
    if (recv_ret != 4) {
        PR_ERR("Failed to receive header");
        tal_net_close(fd);
        return -1;
    }

    // 解析图片大小（大端）
    image_size = (header[0] << 24) | (header[1] << 16) | (header[2] << 8) | header[3];
    PR_DEBUG("Image size: %u bytes", image_size);

    // 检查大小是否超过缓冲区
    if (image_size > IMAGE_BUFFER_SIZE) {
        PR_ERR("Image size %u exceeds buffer size %u", image_size, IMAGE_BUFFER_SIZE);
        tal_net_close(fd);
        return -1;
    }
    *data_size = image_size;

    // 接收图片数据
    received = 0;
    uint32_t yield_counter = 0;  // 计数器，减少 user_tuya_yield() 调用频率
    while (received < image_size) {
        // 每接收约 40KB 数据才处理一次 SDK 事件，提高传输效率
        // 原来每次循环（约 4KB）都调用，导致云端响应阻塞时传输变慢
        if (++yield_counter >= 10) {
            user_tuya_yield();
            yield_counter = 0;
        }

        uint32_t to_recv = image_size - received;
        if (to_recv > 4096) {
            to_recv = 4096;
        }
        recv_ret = tal_net_recv(fd, data + received, to_recv);
        if (recv_ret <= 0) {
            PR_ERR("Failed to receive image data at %u/%u", received, image_size);
            tal_net_close(fd);
            return -1;
        }
        received += recv_ret;
    }

    // 接收完成后处理SDK事件
    user_tuya_yield();

    PR_DEBUG("Received %u bytes image data", received);
    PR_INFO("==========================================");

    // 关闭socket
    tal_net_close(fd);

    return 0;
}

/**
 * @brief RLE 解码单行数据
 * @param rle_data RLE 编码数据
 * @param rle_len RLE 数据长度
 * @param output 输出缓冲区
 * @param out_max 输出缓冲区最大长度
 * @return 解码后的数据长度
 */
static uint32_t rle_decode_line(const uint8_t *rle_data, uint32_t rle_len, uint8_t *output, uint32_t out_max)
{
    uint32_t i = 0;      // RLE 数据索引
    uint32_t out_pos = 0; // 输出位置

    while (i < rle_len && out_pos < out_max) {
        uint8_t count = rle_data[i++];
        uint8_t value = rle_data[i++];

        // 展开运行长度编码
        if (out_pos + count > out_max) {
            count = out_max - out_pos;
        }
        memset(output + out_pos, value, count);
        out_pos += count;
    }

    return out_pos;
}

/**
 * @brief 打印十六进制数据（显示前20字节）
 * @param data 数据缓冲区
 * @param len 数据长度
 * @param max_lines 最大行数
 */
static void print_hex_dump(const uint8_t *data, uint32_t len, uint32_t max_lines)
{
    uint32_t i, j;
    uint32_t lines = (len + 15) / 16;

    if (lines > max_lines) {
        lines = max_lines;
    }

    PR_INFO("Hex dump (first %u bytes):", len > 20 ? 20 : len);

    for (i = 0; i < lines; i++) {
        // 打印偏移
        printf("  %08X: ", i * 16);

        // 打印十六进制
        for (j = 0; j < 16; j++) {
            uint32_t offset = i * 16 + j;
            if (offset < len) {
                printf("%02X ", data[offset]);
            } else {
                printf("   ");
            }
        }

        // 打印分隔符
        printf(" |");

        // 打印ASCII
        for (j = 0; j < 16; j++) {
            uint32_t offset = i * 16 + j;
            if (offset < len) {
                uint8_t c = data[offset];
                printf("%c", (c >= 32 && c < 127) ? c : '.');
            } else {
                printf(" ");
            }
        }

        printf("|\n");

        // 如果只显示前20字节，在适当位置停止
        if ((i + 1) * 16 >= 20 && lines > 1) {
            printf("  ... (truncated, total %u bytes)\n", len);
            break;
        }
    }
}
