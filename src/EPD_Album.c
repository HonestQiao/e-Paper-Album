/*****************************************************************************
 * | File      	:	EPD_test_net.c
 * | Author      :   Tuya Developer
 * | Function    :   e-Paper network test Demo (WiFi + Socket)
 * | Info        :   Connect to WiFi and send commands via socket
 *----------------
 * |	This version:   V1.0
 * | Date        :   2025-01-21
 * | Info        :
 ******************************************************************************/
#include "EPD_Test.h"
#include "EPD_4in0e.h"
#include "tal_api.h"
#include "tal_wifi.h"
#include "tal_network.h"
#include "tal_system.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

/***********************************************************
 *                    WiFi 配置
 ***********************************************************/
#define WIFI_SSID     "WiFi名称"
#define WIFI_PASSWORD "WiFi密码"

/***********************************************************
 *                    Socket 配置
 ***********************************************************/
#define SOCKET_SERVER_IP   "192.168.1.15"   // socket服务地址
#define SOCKET_SERVER_PORT 18888            // socket服务端口
#define RECV_BUFFER_SIZE   1024
#define LOOP_INTERVAL_MS   180000 // 循环间隔
#define IMAGE_BUFFER_SIZE  120000 // 400x600 屏幕 6 色格式大小 (400*600/2)

/***********************************************************
 *                    全局变量
 ***********************************************************/
static volatile bool g_wifi_connected   = false;
static volatile bool g_socket_connected = false;
static int           g_image_index      = 0;
static int           g_image_total      = 0;

/***********************************************************
 *                    函数声明
 ***********************************************************/
static void wifi_event_callback(WF_EVENT_E event, void *arg);
static int  socket_send_command(const char *cmd, char *response, int resp_size);
static int  socket_recv_json_response(char *response, int resp_size);
static int  socket_get_image_data(uint8_t *data, uint32_t *data_size);
static int  wifi_connect_wait(void);
static void print_hex_dump(const uint8_t *data, uint32_t len, uint32_t max_lines);

/**
 * @brief WiFi 事件回调函数
 */
static void wifi_event_callback(WF_EVENT_E event, void *arg)
{
    (void)arg;
    OPERATE_RET op_ret = OPRT_OK;
    NW_IP_S     sta_info;

    PR_DEBUG("WiFi event callback: %d", event);

    switch (event) {
    case WFE_CONNECTED:
        PR_DEBUG("WiFi connected!");
        memset(&sta_info, 0, sizeof(NW_IP_S));
        op_ret = tal_wifi_get_ip(WF_STATION, &sta_info);
        if (OPRT_OK == op_ret) {
            PR_DEBUG("IP: %s, Gateway: %s, Mask: %s", sta_info.ip, sta_info.gw, sta_info.mask);
        }
        g_wifi_connected = true;
        break;

    case WFE_CONNECT_FAILED:
        PR_DEBUG("WiFi connection failed!");
        g_wifi_connected = false;
        break;

    case WFE_DISCONNECTED:
        PR_DEBUG("WiFi disconnected!");
        g_wifi_connected   = false;
        g_socket_connected = false;
        break;

    default:
        break;
    }
}

/**
 * @brief 等待WiFi连接
 * @return 0 成功, -1 超时失败
 */
static int wifi_connect_wait(void)
{
    int timeout = 30; // 最多等待30秒

    while (timeout > 0) {
        if (g_wifi_connected) {
            PR_DEBUG("WiFi connected successfully");
            return 0;
        }
        tal_system_sleep(1000);
        timeout--;
        PR_DEBUG("Waiting for WiFi connection... (%ds remaining)", timeout);
    }

    PR_ERR("WiFi connection timeout");
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
    server_addr = tal_net_str2addr(SOCKET_SERVER_IP);
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
    PR_DEBUG("Connected to server %s:%d", SOCKET_SERVER_IP, SOCKET_SERVER_PORT);

    // 发送命令
    PR_DEBUG("Sending command: %s", cmd);
    TUYA_ERRNO send_ret = tal_net_send(fd, cmd, strlen(cmd));
    if (send_ret < 0) {
        PR_ERR("Send command failed");
        tal_net_close(fd);
        return -1;
    }

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

    // 关闭socket
    tal_net_close(fd);
    g_socket_connected = false;

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
 * @brief EPD 网络测试函数
 * @note 连接WiFi并通过socket循环获取数据: update -> info -> get_c (每15秒)
 */
int EPD_test_net(void)
{
    OPERATE_RET op_ret = OPRT_OK;
    char        response[RECV_BUFFER_SIZE];
    uint8_t    *image_buffer = NULL;
    uint32_t    image_size   = 0;
    uint32_t    loop_count   = 0;

    PR_DEBUG("========== EPD Network Test Start ==========");
    PR_DEBUG("WiFi SSID: %s", WIFI_SSID);
    PR_DEBUG("Server: %s:%d", SOCKET_SERVER_IP, SOCKET_SERVER_PORT);
    PR_DEBUG("Loop interval: %d ms", LOOP_INTERVAL_MS);

    // ========== EPD 初始化代码已注释掉，优先调通网络 ==========
    // 初始化电子纸
    // if (DEV_Module_Init() != 0) {
    //     PR_ERR("DEV Module Init failed");
    //     return -1;
    // }
    // PR_DEBUG("e-Paper Init...");
    // EPD_4IN0E_Init();
    // EPD_4IN0E_Clear(EPD_4IN0E_WHITE);
    // DEV_Delay_ms(500);
    // ==========================================================

    // 初始化WiFi
    PR_DEBUG("Initializing WiFi...");
    op_ret = tal_wifi_init(wifi_event_callback);
    if (op_ret != OPRT_OK) {
        PR_ERR("WiFi init failed: %d", op_ret);
        return -1;
    }

    // 设置为Station模式
    op_ret = tal_wifi_set_work_mode(WWM_STATION);
    if (op_ret != OPRT_OK) {
        PR_ERR("Set work mode failed: %d", op_ret);
        return -1;
    }

    // 连接WiFi
    PR_DEBUG("Connecting to WiFi: %s", WIFI_SSID);
    op_ret = tal_wifi_station_connect((int8_t *)WIFI_SSID, (int8_t *)WIFI_PASSWORD);
    if (op_ret != OPRT_OK) {
        PR_ERR("WiFi connect failed: %d", op_ret);
        return -1;
    }

    // 等待WiFi连接成功
    if (wifi_connect_wait() != 0) {
        PR_ERR("WiFi connection timeout");
        tal_wifi_station_disconnect();
        return -1;
    }

    PR_DEBUG("WiFi connected, entering main loop...");

    // ========== 主循环: 每15秒获取一次数据 ==========
    while (1) {
        loop_count++;
        PR_INFO("==========================================");
        PR_INFO("  Loop #%u", loop_count);
        PR_INFO("==========================================");

        // ========== 第一步: 发送 update 命令 ==========
        PR_DEBUG("Step 1: Sending 'update' command...");
        if (socket_send_command("update", response, sizeof(response)) != 0) {
            PR_ERR("Update command failed, retrying in next cycle");
            tal_system_sleep(LOOP_INTERVAL_MS);
            continue;
        }
        PR_DEBUG("Update response: %s", response);

        // 解析 current_index 和 total
        {
            char *p;

            // 解析 current_index
            p = strstr(response, "\"current_index\"");
            if (p) {
                sscanf(p, "\"current_index\" : %d", &g_image_index);
            }

            // 解析 total
            p = strstr(response, "\"total\"");
            if (p) {
                sscanf(p, "\"total\" : %d", &g_image_total);
            }

            PR_DEBUG("Image index: %d, total: %d", g_image_index, g_image_total);
        }

        // ========== 第二步: 发送 info 命令 ==========
        PR_DEBUG("Step 2: Sending 'info' command...");
        if (socket_send_command("info", response, sizeof(response)) != 0) {
            PR_ERR("Info command failed, retrying in next cycle");
            tal_system_sleep(LOOP_INTERVAL_MS);
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
                g_image_total = total;
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

        // ========== 第三步: 发送 get_c 命令获取 C 数组数据 ==========
        PR_DEBUG("Step 3: Sending 'get_c' command...");

        // 分配图片缓冲区
        image_buffer = (uint8_t *)malloc(IMAGE_BUFFER_SIZE);
        if (image_buffer == NULL) {
            PR_ERR("Failed to allocate memory for image");
            tal_system_sleep(LOOP_INTERVAL_MS);
            continue;
        }

        if (socket_get_image_data(image_buffer, &image_size) != 0) {
            PR_ERR("Failed to get image data");
            free(image_buffer);
            image_buffer = NULL;
            tal_system_sleep(LOOP_INTERVAL_MS);
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
            tal_system_sleep(LOOP_INTERVAL_MS);
            continue;
        }

        // 初始化屏幕
        EPD_4IN0E_Init();

        // 显示图片 (使用 get_c 返回的 6 色数据)
        EPD_4IN0E_Display_Fast(image_buffer);

        PR_INFO("Image displayed successfully");

        // 等待显示刷新完成 (30秒)
        PR_DEBUG("Waiting 30s for display refresh to complete...");
        DEV_Delay_ms(30000);

        // 进入睡眠
        PR_INFO("Enter Sleep mode");
        EPD_4IN0E_Sleep();
        DEV_Delay_ms(500);
        DEV_Module_Exit();

        // 释放内存
        free(image_buffer);
        image_buffer = NULL;

        // ========== 等待下一次循环 ==========
        PR_DEBUG("Waiting %d ms before next update...", LOOP_INTERVAL_MS);
        tal_system_sleep(LOOP_INTERVAL_MS);
    }

    // 断开WiFi连接 (理论上不会执行到这里)
    tal_wifi_station_disconnect();

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
    server_addr = tal_net_str2addr(SOCKET_SERVER_IP);
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
    server_addr = tal_net_str2addr(SOCKET_SERVER_IP);
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

    // 发送 "get_c" 命令
    TUYA_ERRNO send_ret = tal_net_send(fd, "get_c", 5);
    if (send_ret < 0) {
        PR_ERR("Send command failed");
        tal_net_close(fd);
        return -1;
    }

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
    while (received < image_size) {
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

    PR_DEBUG("Received %u bytes image data", received);

    // 关闭socket
    tal_net_close(fd);

    return 0;
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
