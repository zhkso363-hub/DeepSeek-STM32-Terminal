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
#define LINE_OFFSET_Y   20      /* 换行Y偏移(px)，16点阵+4间距 */
#define FONT_W_EN        8      /* 英文字符宽度(px) */
#define FONT_W_CN       16      /* 中文字符宽度(px) */
#define DISP_X_START     0
#define DISP_Y_START     0

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




static void Display_Text(const char *str)
{
    uint16_t x = DISP_X_START;
    uint16_t y = DISP_Y_START;
    uint16_t units = 0;

    /* 清屏为白色 */
    LCD_SetTextColor(BLACK);
    LCD_SetBackColor(WHITE);
    ILI9341_Clear(0, 0, LCD_X_LENGTH, LCD_Y_LENGTH);

    /* 设置英文字体为 8x16，与中文 16x16 高度对齐 */
    LCD_SetFont(&Font8x16);

    /* 调试打印原始 GBK 字节流 */
    printf("[DBG] GBK bytes:");
    for (const char *p = str; *p; p++)
        printf(" %02X", (uint8_t)*p);
    printf("\r\n");

    while (*str != '\0')
    {
        if ((uint8_t)*str < 128)
        {
            /* 英文字符 — 预检查换行 */
            if (units >= LINE_MAX_UNITS)
            {
                x = DISP_X_START;
                y += LINE_OFFSET_Y;
                units = 0;
            }
            if (y + FONT_W_CN > LCD_Y_LENGTH)
                y = DISP_Y_START;

            ILI9341_DispChar_EN(x, y, *str);
            x += FONT_W_EN;
            units += 1;
            str++;
        }
        else
        {
            /* 中文字符（GBK 双字节）— 需 2 units，若剩余不足则提前换行 */
            if (units + 2 > LINE_MAX_UNITS)
            {
                x = DISP_X_START;
                y += LINE_OFFSET_Y;
                units = 0;
            }
            if (y + FONT_W_CN > LCD_Y_LENGTH)
                y = DISP_Y_START;

            uint16_t ch = *(uint16_t *)str;
            ch = (ch << 8) | (ch >> 8);     /* 大小端转换 */
            ILI9341_DispChar_CH(x, y, ch);
            x += FONT_W_CN;
            units += 2;
            str += 2;
        }
    }
}


int main(void)
{
    /* ====== 硬件初始化 ====== */
    ILI9341_Init();                     /* ILI9341 液晶屏 */
    SPI_FLASH_Init();                   /* SPI Flash（中文字库） */
    LED_GPIO_Config();                  /* RGB LED */
    Buzzer_GPIO_Config();               /* 蜂鸣器 PA8 */
    USART_Config();                     /* USART1 串口 */
    SysTick_Init();                     /* SysTick 毫秒延时 */

    /* 清屏为全白 */
    ILI9341_GramScan(3);                /* 竖屏模式：X=320, Y=240 */
    LCD_SetBackColor(WHITE);
    ILI9341_Clear(0, 0, LCD_X_LENGTH, LCD_Y_LENGTH);

    /* 默认字体 */
    LCD_SetFont(&Font8x16);
    LCD_SetTextColor(BLACK);

    printf("\r\n[OK] DeepSeek AI Terminal Start\r\n");

    /* ========== 主循环：全速轮询 g_packet_ready ========== */
    while (1)
    {
        if (g_packet_ready == 1)
        {
            /* 【第一步：立即刷新屏幕显示文字】 */
            Display_Text(g_ai_response);

            /* 【第二步：灯光长亮驻留控制（严格互斥）】 */
            if (g_emotion == 0x01 || g_emotion == '1')
            {
                /* 正面情绪：只亮绿灯（PB0拉低），红灯（PB5拉高）蓝灯（PB1拉高）灭 */
                GPIO_ResetBits(GPIOB, GPIO_Pin_0);   /* 绿灯 亮 */
                GPIO_SetBits(GPIOB, GPIO_Pin_5);    /* 红灯 灭 */
                GPIO_SetBits(GPIOB, GPIO_Pin_1);    /* 蓝灯 灭 */
            }
            else if (g_emotion == 0x02 || g_emotion == '2')
            {
                /* 负面情绪：只亮红灯（PB5拉低），绿灯（PB0拉高）蓝灯（PB1拉高）灭 */
                GPIO_SetBits(GPIOB, GPIO_Pin_0);    /* 绿灯 灭 */
                GPIO_ResetBits(GPIOB, GPIO_Pin_5);   /* 红灯 亮 */
                GPIO_SetBits(GPIOB, GPIO_Pin_1);    /* 蓝灯 灭 */
            }
            else if (g_emotion == 0x03 || g_emotion == '3')
            {
                /* 中立情绪：只亮蓝灯（PB1拉低），绿灯（PB0拉高）红灯（PB5拉高）灭 */
                GPIO_SetBits(GPIOB, GPIO_Pin_0);    /* 绿灯 灭 */
                GPIO_SetBits(GPIOB, GPIO_Pin_5);    /* 红灯 灭 */
                GPIO_ResetBits(GPIOB, GPIO_Pin_1);   /* 蓝灯 亮 */
            }

            /* 【第三步：最后清零标志，严禁提前】 */
            g_packet_ready = 0;
        }
    }
}
