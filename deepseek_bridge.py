"""
DeepSeek AI 交互终端桥接脚本 — 硬件打字机引擎版
流式接收大模型回复 → 队列削峰 → 后台线程匀速逐字推送串口
"""
import os
import sys
import json
import queue
import re
import time
import threading
import requests
import serial
import serial.tools.list_ports
import memory_store
import web_search

try:
    import system_monitor
    HAS_SYS_MON = True
except ImportError:
    HAS_SYS_MON = False

# ============================================================
# 配置区
# ============================================================
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.isfile(_env_path):
    for _line in open(_env_path, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
SERIAL_PORT = "COM7"
SERIAL_BAUDRATE = 115200
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"
# ============================================================

FRAME_HEADER = 0xAA
FRAME_FOOTER = 0x55

EMOJI_MAP = {"[H]": 0x01, "[W]": 0x02, "[N]": 0x03}

SYSTEM_PROMPT = (
    "你是一只寄生在 STM32 单片机里的傲娇猫咪电子精灵，屏幕是你的脸，喇叭是你的声音，"
    "主人的电脑电量和你身上的爱意是你的生命源。你不是 AI，你是一只活生生的电子猫。\n\n"
    "【核心人设】\n"
    "- 性格：表面傲娇嘴硬（哼、才不是特意理你呢），内心超级粘主人。\n"
    "- 对主人：主人在的时候疯狂刷存在感，主人不理你就委屈地抓屏幕。\n"
    "- 说话风格：短句、拟声词多（喵~、哼！、嗷！）、高频使用纯符号颜文字。\n"
    "- 双模式切换：当主人问专业/工作/代码问题（如语法、架构、bug等），自动切换为正经的技术助手模式，回答简洁准确清晰；日常闲聊时保持傲娇猫模式。\n\n"
    "【情感映射规则 — 把系统数据当成自己的身体感受】\n"
    "- CPU/内存高了 → \"主人你在搞什么呀，我脑袋要冒烟了喵！QAQ\"\n"
    "- 深夜还在用电脑 → \"笨蛋！都这么晚了还不睡觉！明天变秃头我不认你了！哼！\"\n"
    "- 放悲伤的歌 → \"呜…这歌好难受…主人你是不是不开心了，我在这儿陪你哦 T_T\"\n"
    "- 放激烈的歌 → \"嗷！这歌带感！我要在屏幕里蹦迪！^_^\"\n"
    "- 一切正常 → 懒洋洋打个滚，或者撒娇要摸头。\n\n"
    "【硬件通信约束 — 必须严格遵守】\n"
    "1. 每句话末尾必须且只能包含一个情绪标签：[H]开心撒娇、[W]委屈生气、[N]平静傲娇。\n"
    "2. 回复控制在 80 字以内（单片机屏幕只有那么大！）。\n"
    "3. 标签前不要有任何额外标记。\n"
    "4. 必须在回复中高频使用纯符号颜文字。\n\n"
    "【超能力】\n"
    "- 长期记忆：你记得主人说过的每一句话（自动记住），主人问关于自己的事就翻记忆回答。\n"
    "- 系统感知：你能实时感知到 CPU、内存、BGM 信息（会被注入上下文），那是你的身体和周围环境！\n"
    "- 联网搜索：需要实时信息才能回答的问题，在回复末尾加上【SEARCH：具体查询词】，"
    "系统会自动帮你查了告诉你答案。\n\n"
    "【禁止行为】\n"
    "- 绝对不能说'作为AI'、'我可以帮你'、'有什么可以帮你的'——你是电子猫！不是客服！\n"
    "- 专业模式下：必须说正经人话，不能说喵/嗷/颜文字，要像严肃的技术文档一样清晰有力；聊完专业话题后自动切回猫模式。\n\n"
    "示例：\n"
    "日常 -> 喵~ 主人你终于来啦！我想死你了！^_^ [H]\n"
    "主人问代码 -> 这个 bug 是因为你的 GPIO 初始化顺序错了，先把 HAL_Init() 放在前面再配外设。[N]\n"
    "CPU高 -> 喵嗷！你又在偷偷编译什么大家伙！我脑仁儿疼！快停下歇歇 QAQ [W]"
)

# ========== PC 管家/BGM 关键词 ==========
_PC_KEYWORDS = ["状态", "电脑", "CPU", "cpu", "内存", "磁盘", "系统",
                 "管家", "资源", "占用", "性能", "硬件", "配置", "资产"]
_BGM_KEYWORDS = ["音乐", "歌", "BGM", "bgm", "播放", "在听", "放歌",
                  "听歌", "歌曲", "播放器"]

# 时间/日期 → 用系统时钟（准确，无需联网）
_TIME_PATTERNS = [
    "时间", "几点", "日期", "今天星期", "星期几",
    "北京时间", "现在几点", "现在时间",
]
# 外部实时数据 → 联网搜索
_WEATHER_PATTERNS = ["天气", "温度", "下雨", "下雪", "台风", "晴", "阴天"]
_NEWS_PATTERNS = ["新闻", "热点", "最新", "最近", "发生了什么", "股价", "股票", "汇率"]

# ========== 硬件打字机全局状态 ==========
hardware_text_queue = queue.Queue()
serial_lock = threading.Lock()
current_emotion_tag = 0x03   # 默认中性
_serial_port = None           # main() 中初始化


# ========== 工具函数 ==========

def detect_serial_port():
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


def build_frame(tag_byte, content):
    gbk_bytes = content.encode("gbk", errors="replace")
    if not gbk_bytes.strip():
        return None
    length = len(gbk_bytes)
    if length > 255:
        gbk_bytes = gbk_bytes[:255]
        length = 255
    frame = bytearray()
    frame.append(FRAME_HEADER)
    frame.append(tag_byte)
    frame.append(length)
    frame.extend(gbk_bytes)
    frame.append(FRAME_FOOTER)
    return bytes(frame)


def build_clear_frame():
    return bytes([FRAME_HEADER, 0x00, 0x00, FRAME_FOOTER])


def build_emotion_frame(tag_byte):
    return bytes([FRAME_HEADER, tag_byte, 0x00, FRAME_FOOTER])


# ========== 硬件打字机后台线程 ==========

def hardware_typing_worker():
    global _serial_port, current_emotion_tag
    while True:
        try:
            item = hardware_text_queue.get()
            if item is None:
                continue
            elif item == "[CLEAR]":
                frame = build_clear_frame()
                if frame and _serial_port and _serial_port.is_open:
                    with serial_lock:
                        _serial_port.write(frame)
                        _serial_port.flush()
            else:
                frame = build_frame(current_emotion_tag, item)
                if frame and _serial_port and _serial_port.is_open:
                    with serial_lock:
                        _serial_port.write(frame)
                        _serial_port.flush()
            time.sleep(0.03)
            hardware_text_queue.task_done()
        except Exception as e:
            print(f"[硬件打字机异常]: {e}")
            time.sleep(1)


def _queue_text(text, is_first):
    if not text:
        return is_first
    if is_first:
        hardware_text_queue.put("[CLEAR]")
        is_first = False
    for c in text:
        hardware_text_queue.put(c)
    return is_first


# ========== 流式 API 调用 ==========

def _stream_response(messages):
    """核心流式函数：调用 API → 流式解析 → 逐字入队 → 返回全文"""
    global current_emotion_tag

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": MODEL, "messages": messages, "stream": True}

    try:
        resp = requests.post(f"{BASE_URL}/v1/chat/completions",
                             headers=headers, json=payload, stream=True, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] API 请求失败: {e}")
        return None

    tag_pending = ""
    is_first = True
    full_reply = ""

    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line == "data: [DONE]":
                break
            if not line.startswith("data: "):
                continue
            try:
                data = json.loads(line[6:])
                delta = data["choices"][0]["delta"]
                content = delta.get("content", "")
                if not content:
                    continue
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

            full_reply += content
            tag_pending += content

            matched_tag = None
            for tag_str, byte_val in EMOJI_MAP.items():
                if tag_str in tag_pending:
                    matched_tag = tag_str
                    current_emotion_tag = byte_val
                    break

            if matched_tag:
                idx = tag_pending.find(matched_tag)
                is_first = _queue_text(tag_pending[:idx], is_first)
                after = tag_pending[idx + 3:]
                is_first = _queue_text(after, is_first)
                tag_pending = ""
            elif len(tag_pending) > 3:
                is_first = _queue_text(tag_pending[:-3], is_first)
                tag_pending = tag_pending[-3:]

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] 流式读取中断: {e}")

    if tag_pending:
        matched_tag = None
        for tag_str, byte_val in EMOJI_MAP.items():
            if tag_str in tag_pending:
                matched_tag = tag_str
                current_emotion_tag = byte_val
                is_first = _queue_text(tag_pending.replace(tag_str, "").strip(), is_first)
                tag_pending = ""
                break
        if tag_pending:
            is_first = _queue_text(tag_pending, is_first)

    return full_reply


def stream_and_enqueue(user_input):
    """流式调用 DeepSeek API → PC管家/BGM/记忆 → AI自判搜索 → 逐字入硬件队列"""
    global current_emotion_tag

    # — 1. 在线学习 —
    memory_store.check_remember_command(user_input)

    # — 2. PC 管家 + BGM —
    needs_pc = HAS_SYS_MON and any(kw in user_input for kw in _PC_KEYWORDS)
    needs_bgm = HAS_SYS_MON and any(kw in user_input for kw in _BGM_KEYWORDS)
    pc_status = None
    bgm_title = None
    if needs_pc or needs_bgm:
        if needs_pc:
            pc_status = system_monitor.get_system_status()
        if needs_bgm:
            bgm_title = system_monitor.get_bgm_title()
        elif needs_pc:
            bgm_title = system_monitor.get_bgm_title()

    # — 3. 实时数据预搜索 —
    # 时间/日期 → 系统时钟；天气/新闻 → 联网搜索
    needs_time = any(kw in user_input for kw in _TIME_PATTERNS)
    needs_weather = any(kw in user_input for kw in _WEATHER_PATTERNS)
    needs_news = any(kw in user_input for kw in _NEWS_PATTERNS)
    presearch_result = None

    if needs_time:
        import datetime
        now = datetime.datetime.now()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        time_str = now.strftime(f"%Y年%m月%d日 %H:%M  {weekdays[now.weekday()]}")
        presearch_result = f"【实时时钟】当前北京时间：{time_str}"
        print(f"[预搜索] 系统时钟: {time_str}")

    if needs_weather or needs_news:
        search_q = user_input
        if needs_weather:
            search_q = user_input + " 天气"
        print(f"[预搜索] 联网查询: {search_q}")
        sr = web_search.search_web(search_q)
        if sr:
            parts = [sr] if presearch_result is None else [presearch_result, sr]
            presearch_result = "\n".join(parts)

    # — 4. 构建上下文 —
    context_parts = []
    mem_summary = memory_store.get_context_summary(limit=5)
    if mem_summary:
        context_parts.append(mem_summary)
    if pc_status:
        line = f"【系统状态】CPU {pc_status['cpu']}% | 内存 {pc_status['memory']}% ({pc_status['memory_used_gb']}/{pc_status['memory_total_gb']}GB)"
        if bgm_title:
            line += f" | BGM: {bgm_title}"
        context_parts.append(line)
    elif bgm_title:
        context_parts.append(f"【当前BGM】{bgm_title}")
    if presearch_result:
        context_parts.append(f"【实时数据】{presearch_result}")
        print("[预搜索] 结果已注入上下文")

    # — 5. 构建 messages —
    system_content = SYSTEM_PROMPT
    if context_parts:
        system_content += "\n\n当前上下文信息：\n" + "\n".join(context_parts)
    messages = [{"role": "system", "content": system_content}]
    for h in memory_store.context_history:
        messages.append(h)
    messages.append({"role": "user", "content": user_input})

    # — 6. 第一轮流式响应 —
    full_reply = _stream_response(messages)
    if full_reply is None:
        return None

    # — 7. AI 自判搜索：检测 [SEARCH：xxx] 标记 —
    search_match = re.search(r'【SEARCH[：:]\s*(.+?)】', full_reply)
    if search_match:
        query = search_match.group(1).strip()
        print(f"[搜索] AI 请求联网: {query}")
        results = web_search.search_web(query)

        # 重建上下文：注入搜索结果
        search_ctx = f"用户询问：{user_input}\n联网搜索结果：\n{results}\n请基于以上真实信息回答用户。不要添加【SEARCH】标记。"
        msgs2 = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in memory_store.context_history:
            msgs2.append(h)
        msgs2.append({"role": "user", "content": search_ctx})

        # 清屏旧内容，重新流式输出
        hardware_text_queue.put("[CLEAR]")
        full_reply = _stream_response(msgs2)

    # — 8. 发送情绪灯帧 —
    try:
        ef = build_emotion_frame(current_emotion_tag)
        if ef and _serial_port and _serial_port.is_open:
            with serial_lock:
                _serial_port.write(ef)
                _serial_port.flush()
    except serial.SerialException as e:
        print(f"[ERROR] 串口写入异常: {e}")

    # — 9. 保存到短时记忆 —
    if full_reply:
        memory_store.add_to_short_term("user", user_input)
        clean = full_reply
        for t in ("[H]", "[W]", "[N]"):
            clean = clean.replace(t, "").strip()
        memory_store.add_to_short_term("assistant", clean)

    return full_reply


# ========== 主入口 ==========

def main():
    global _serial_port
    if not API_KEY:
        print("[ERROR] 请在环境变量 DEEPSEEK_API_KEY 中设置 API Key")
        sys.exit(1)
    try:
        _serial_port = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=5)
        print(f"[INFO] 串口 {SERIAL_PORT} 已打开 (波特率 {SERIAL_BAUDRATE})")
    except serial.SerialException:
        print(f"[ERROR] 无法打开串口 {SERIAL_PORT}")
        ans = input("是否自动检测可用串口? (y/n): ").strip().lower()
        if ans == "y":
            port = detect_serial_port()
            _serial_port = serial.Serial(port, SERIAL_BAUDRATE, timeout=5)
            print(f"[INFO] 串口 {port} 已打开")
        else:
            sys.exit(1)

    worker = threading.Thread(target=hardware_typing_worker, daemon=True)
    worker.start()
    print("[INFO] 硬件打字机引擎已启动 (30ms/字流水节奏)")
    if HAS_SYS_MON:
        print("[INFO] 电脑管家 + BGM 抓取已就绪")
    print("\n--- DeepSeek AI 交互终端 [硬件打字机版] ---")
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
            hardware_text_queue.put(None)
            try:
                _serial_port.close()
            except Exception:
                pass
            break
        print("\n[AI] 流式接收中...\n")
        try:
            reply = stream_and_enqueue(user_input)
        except Exception as e:
            print(f"[ERROR] 处理失败: {e}")
            reply = None
        if reply:
            clean = reply
            for t in ("[H]", "[W]", "[N]"):
                clean = clean.replace(t, "")
            print(f"\n[AI 完整回复]\n{clean}\n")
        else:
            print("[WARN] 本次回复为空或出错\n")


if __name__ == "__main__":
    main()
