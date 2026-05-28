/**
  ******************************************************************************
  * @file    main.c
  * @author  fire
  * @version V1.0
  * @date    2013-xx-xx
  * @brief   DeepSeek AI 交互终端主程序
  ******************************************************************************
  * @attention
  *
  * ʵ��ƽ̨:Ұ�� F103-ָ���� STM32 ������
  * ��̳    :http://www.firebbs.cn
  * �Ա�    :https://fire-stm32.taobao.com
  *
  ******************************************************************************
  */

#include "stm32f10x.h"
#include "./usart/bsp_usart.h"
#include "./lcd/bsp_ili9341_lcd.h"
#include "./led/bsp_led.h"
#include "./SysTick/bsp_SysTick.h"
#include "./flash/bsp_spi_flash.h"
#include <string.h>

/* ========== 蜂鸣器引脚 PA8，高电平鸣叫 ========== */
#define BUZZOR_GPIO_PORT   GPIOA
#define BUZZOR_GPIO_PIN    GPIO_Pin_8
#define BUZZOR_GPIO_CLK    RCC_APB2Periph_GPIOA

#define BUZZOR_ON   GPIO_SetBits(BUZZOR_GPIO_PORT, BUZZOR_GPIO_PIN)
#define BUZZOR_OFF  GPIO_ResetBits(BUZZOR_GPIO_PORT, BUZZOR_GPIO_PIN)

/* ========== LCD 显示参数 ========== */
#define LINE_MAX_UNITS  30      /* 一行最大宽度单位：15汉字(×2) = 30英文字符(×1) */
#define LINE_OFFSET_Y   24      /* 换行Y偏移(px)，16点阵+8行距 */
#define FONT_W_EN        8      /* 英文字符宽度(px) */
#define FONT_W_CN       16      /* 中文字符宽度(px) */
#define MAX_LINES       16      /* 最大排版行数 */
#define CURSOR_X_INIT   10      /* 追加模式初始X */
#define CURSOR_Y_INIT   40      /* 追加模式初始Y */

/* ========== 蜂鸣器 GPIO 初始化 ========== */
static void Buzzer_GPIO_Config(void)
{
    GPIO_InitTypeDef GPIO_InitStructure;
    RCC_APB2PeriphClockCmd(BUZZOR_GPIO_CLK, ENABLE);
    GPIO_InitStructure.GPIO_Pin = BUZZOR_GPIO_PIN;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(BUZZOR_GPIO_PORT, &GPIO_InitStructure);
    BUZZOR_OFF;
}




/* ========== 追加模式光标状态 ========== */
static uint16_t g_cx = CURSOR_X_INIT;
static uint16_t g_cy = CURSOR_Y_INIT;
static uint16_t g_line_units = 0;


static void Display_Text(const char *str)
{
    /* === Phase 1: 排版分析，记录每行占用的 units 数 === */
    uint8_t lu[MAX_LINES];
    uint8_t lc = 0;
    const char *p = str;
    uint16_t units = 0;

    while (*p && lc < MAX_LINES)
    {
        if ((uint8_t)*p < 128) {
            if (units >= LINE_MAX_UNITS) { lu[lc++] = units; units = 0; }
            units += 1; p++;
        } else {
            if (units + 2 > LINE_MAX_UNITS) { lu[lc++] = units; units = 0; }
            units += 2; p += 2;
        }
    }
    if (units > 0 || lc == 0)
        lu[lc++] = units;

    uint16_t total_h = lc * LINE_OFFSET_Y;
    uint16_t y = (LCD_Y_LENGTH - total_h) / 2;

    LCD_SetTextColor(COLOR_ICEBLUE);
    LCD_SetBackColor(BLACK);
    ILI9341_Clear(0, 0, LCD_X_LENGTH, LCD_Y_LENGTH);
    LCD_SetFont(&Font8x16);

    uint8_t li = 0;
    units = 0;

    while (*str != '\0' && li < lc)
    {
        if (units == 0)
            y = (LCD_Y_LENGTH - lc * LINE_OFFSET_Y) / 2 + li * LINE_OFFSET_Y;

        uint16_t x = (LCD_X_LENGTH - lu[li] * FONT_W_EN) / 2 + units * FONT_W_EN;

        if ((uint8_t)*str < 128) {
            ILI9341_DispChar_EN(x, y, *str);
            units += 1; str++;
        } else {
            uint16_t ch = *(uint16_t *)str;
            ch = (ch << 8) | (ch >> 8);
            ILI9341_DispChar_CH(x, y, ch);
            units += 2; str += 2;
        }
        Delay_us(1);
        if (units >= lu[li]) { li++; units = 0; }
    }
}


/**
  * Display_Append — 无闪烁逐字追加
  * 在光标位置绘制字符并前进，不清屏。
  * 用于硬件打字机模式，由 Python 端流式逐字推送。
  */
static void Display_Append(const char *str)
{
    LCD_SetTextColor(COLOR_ICEBLUE);
    LCD_SetBackColor(BLACK);
    LCD_SetFont(&Font8x16);

    while (*str)
    {
        /* Y 超出屏幕 → 回滚到顶部（简单滚动） */
        if (g_cy + FONT_W_CN > LCD_Y_LENGTH) {
            g_cy = CURSOR_Y_INIT;
            g_cx = CURSOR_X_INIT;
            g_line_units = 0;
        }

        if ((uint8_t)*str < 128) {
            if (g_line_units >= LINE_MAX_UNITS) {
                g_cx = CURSOR_X_INIT;
                g_cy += LINE_OFFSET_Y;
                g_line_units = 0;
            }
            ILI9341_DispChar_EN(g_cx, g_cy, *str);
            g_cx += FONT_W_EN;
            g_line_units += 1;
            str++;
        } else {
            if (g_line_units + 2 > LINE_MAX_UNITS) {
                g_cx = CURSOR_X_INIT;
                g_cy += LINE_OFFSET_Y;
                g_line_units = 0;
            }
            uint16_t ch = *(uint16_t *)str;
            ch = (ch << 8) | (ch >> 8);
            ILI9341_DispChar_CH(g_cx, g_cy, ch);
            g_cx += FONT_W_CN;
            g_line_units += 2;
            str += 2;
        }
    }
}


int main(void)
{
    ILI9341_Init();
    SPI_FLASH_Init();
    LED_GPIO_Config();
    Buzzer_GPIO_Config();
    USART_Config();
    SysTick_Init();

    ILI9341_GramScan(3);
    LCD_SetBackColor(BLACK);
    ILI9341_Clear(0, 0, LCD_X_LENGTH, LCD_Y_LENGTH);
    LCD_SetFont(&Font8x16);
    LCD_SetTextColor(COLOR_ICEBLUE);

    printf("\r\n[OK] DeepSeek AI Terminal Start\r\n");

    /* ========== 主循环：三态帧分发 ========== */
    while (1)
    {
        if (g_packet_ready == 1)
        {
            uint8_t emotion = g_emotion;
            uint8_t data_len = g_data_len;

            if (data_len == 0 && emotion == 0x00) {
                /* — 清屏指令：[0xAA][0x00][0x00][0x55] — */
                ILI9341_Clear(0, 0, LCD_X_LENGTH, LCD_Y_LENGTH);
                g_cx = CURSOR_X_INIT;
                g_cy = CURSOR_Y_INIT;
                g_line_units = 0;
            } else if (data_len == 0) {
                /* — 纯切灯帧：LED 已由 ISR 设置，无显示动作 — */
            } else {
                /* — 文本帧：无闪烁追加 — */
                Display_Append(g_ai_response);

                if (emotion == 0x01) {
                    GPIO_ResetBits(GPIOB, GPIO_Pin_0);   /* 绿灯 亮 */
                    GPIO_SetBits(GPIOB, GPIO_Pin_5);     /* 红灯 灭 */
                    GPIO_SetBits(GPIOB, GPIO_Pin_1);     /* 蓝灯 灭 */
                } else if (emotion == 0x02) {
                    GPIO_SetBits(GPIOB, GPIO_Pin_0);     /* 绿灯 灭 */
                    GPIO_ResetBits(GPIOB, GPIO_Pin_5);   /* 红灯 亮 */
                    GPIO_SetBits(GPIOB, GPIO_Pin_1);     /* 蓝灯 灭 */
                } else if (emotion == 0x03) {
                    GPIO_SetBits(GPIOB, GPIO_Pin_0);     /* 绿灯 灭 */
                    GPIO_SetBits(GPIOB, GPIO_Pin_5);     /* 红灯 灭 */
                    GPIO_ResetBits(GPIOB, GPIO_Pin_1);   /* 蓝灯 亮 */
                }
            }

            g_packet_ready = 0;
        }
    }
}
