"""
DeepSeek AI 交互终端桥接脚本
通过串口连接 STM32 硬件终端，调用 DeepSeek API 获取回复并封包发送。
"""

import os
import sys
import requests
import serial
import serial.tools.list_ports
import time

# ============================================================
# 配置区（请根据实际情况手动修改）
# ============================================================
# === 优先从 .env 文件读取，其次从环境变量读取 ===
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.isfile(_env_path):
    for _line in open(_env_path, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
SERIAL_PORT = "COM7"            # STM32 串口号（可在设备管理器中查看）
SERIAL_BAUDRATE = 115200        # 波特率，与单片机一致
# ============================================================

# DeepSeek API 配置
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"

# 协议常量
FRAME_HEADER = 0xAA
FRAME_FOOTER = 0x55

# 情感标签映射
EMOJI_MAP = {
    "[H]": 0x01,  # 积极/开心
    "[W]": 0x02,  # 严肃/警告
    "[N]": 0x03,  # 平静/中性
}

SYSTEM_PROMPT = (
    "你是一个大语言模型交互终端，与嵌入式设备进行文字对话。"
    "请严格遵守以下规则：\n"
    "1. 回复字数必须控制在80个字以内（适合屏幕显示）。\n"
    "2. 在回复的绝对开头必须带有情感标签：[H]代表积极/开心，[W]代表严肃/警告，[N]代表平静/中性。\n"
    "3. 标签后的正文不要包含额外标签或元信息。\n"
    "4. 必须在回复中高频使用颜文字（如 ^_^、QAQ、T_T、:-D、:-(、\^_^/ 等纯符号颜文字），让情绪表达非常拟人化，像一个桌面 AI 宠物。\n"
    "例如：[H]收到你的消息，今天心情不错呢 ^_^"
)


def detect_serial_port():
    """自动检测可用的串口并提示用户选择。"""
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("[ERROR] 未检测到任何串口设备，请检查连接。")
        sys.exit(1)

    print("检测到以下串口：")
    for i, p in enumerate(ports):
        print(f"  [{i}] {p.device} - {p.description}")

    while True:
        try:
            idx = int(input("请选择串口号: "))
            if 0 <= idx < len(ports):
                return ports[idx].device
        except (ValueError, IndexError):
            pass
        print("输入无效，请重新选择。")


def query_deepseek(user_input):
    """调用 DeepSeek API 获取回复。"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
        "stream": False,
    }

    try:
        resp = requests.post(f"{BASE_URL}/v1/chat/completions",
                             headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] API 请求失败: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"[ERROR] 解析 API 响应失败: {e}")
        return None


def parse_emotion_tag(reply):
    """从回复开头解析情感标签，返回 (tag_byte, clean_text)。"""
    for tag, byte_val in EMOJI_MAP.items():
        if reply.startswith(tag):
            return byte_val, reply[len(tag):].strip()
    # 未匹配到标签，默认中性
    print("[WARN] 回复未识别情感标签，默认使用 [N]")
    return 0x03, reply.strip()


def build_frame(tag_byte, content):
    """构建 16 进制数据帧（非 GBK 字符自动替换为 ?）。"""
    gbk_bytes = content.encode("gbk", errors="replace")
    if not gbk_bytes.strip():
        return None
    length = len(gbk_bytes)
    if length > 255:
        print(f"[WARN] GBK 编码长度 {length} 超过 255，将被截断")
        gbk_bytes = gbk_bytes[:255]
        length = 255

    frame = bytearray()
    frame.append(FRAME_HEADER)
    frame.append(tag_byte)
    frame.append(length)
    frame.extend(gbk_bytes)
    frame.append(FRAME_FOOTER)
    return bytes(frame)


def hex_dump(data):
    """将字节流格式化为可读的 16 进制字符串。"""
    hex_str = data.hex(" ").upper()
    # 每 16 字节换行，便于阅读
    lines = []
    for i in range(0, len(hex_str), 48):
        lines.append(hex_str[i:i + 48])
    return "\n       ".join(lines)


def main():
    # --- API key 检查 ---
    if not API_KEY:
        print("[ERROR] 请在环境变量 DEEPSEEK_API_KEY 中设置 API Key")
        sys.exit(1)

    # --- 串口连接 ---
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=5)
        print(f"[INFO] 串口 {SERIAL_PORT} 已打开 (波特率 {SERIAL_BAUDRATE})")
    except serial.SerialException:
        print(f"[ERROR] 无法打开串口 {SERIAL_PORT}")
        ans = input("是否自动检测可用串口? (y/n): ").strip().lower()
        if ans == "y":
            port = detect_serial_port()
            ser = serial.Serial(port, SERIAL_BAUDRATE, timeout=5)
            print(f"[INFO] 串口 {port} 已打开")
        else:
            sys.exit(1)

    print("\n--- DeepSeek AI 交互终端 ---")
    print("输入消息后回车发送，输入 'exit' 退出程序。\n")

    while True:
        try:
            user_input = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] 退出程序")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            ser.close()
            break

        # 1. 调用 DeepSeek API
        reply = query_deepseek(user_input)
        if reply is None:
            continue

        print(f"\n[AI 原始回复]\n{reply}\n")

        # 2. 解析情感标签
        tag_byte, raw_text = parse_emotion_tag(reply)

        try:
            # 3. 封包（非 GBK 字符自动替换为 ?）
            frame = build_frame(tag_byte, raw_text)
            if frame is None:
                print("[WARN] GBK 编码后文本为空，跳过发送\n")
                continue

            # 4. 打印调试信息
            gbk_content = frame[3:-1]  # 从封包中提取实际发送的 GBK 正文
            print(f"[GBK 字节] {gbk_content.hex(' ').upper()}")
            print(f"[封包数据]\n       {hex_dump(frame)}")
            print(f"       解析: HEADER=0x{FRAME_HEADER:02X} "
                  f"TAG=0x{frame[1]:02X} "
                  f"LEN={frame[2]} "
                  f"CONTENT={gbk_content.decode('gbk', errors='replace')} "
                  f"FOOTER=0x{frame[-1]:02X}\n")

            # 5. 发送到串口
            ser.write(frame)
            ser.flush()
            print("[SENT] 数据帧已发送到串口\n")
        except Exception as e:
            print(f"出错啦: {e}")


if __name__ == "__main__":
    main()
