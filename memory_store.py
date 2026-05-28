"""
记忆管理 — JSON 长时记忆舱 + 环形短记忆
"""
import json
import os
import time

MEMORY_FILE = "desktop_assistant_memory.json"

# 5 轮环形短记忆（最多 10 条对话）
context_history = []


def load_long_term_memory():
    if not os.path.isfile(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("facts", [])
    except (json.JSONDecodeError, IOError):
        return []


def update_long_term_memory(new_fact):
    data = {"facts": []}
    if os.path.isfile(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            data = {"facts": []}

    data["facts"].append({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "content": new_fact.strip()
    })
    if len(data["facts"]) > 100:
        data["facts"] = data["facts"][-100:]

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return new_fact


def get_context_summary(limit=5):
    """返回长时记忆摘要字符串（最近 limit 条）"""
    facts = load_long_term_memory()
    if not facts:
        return ""
    recent = [f["content"] for f in facts[-limit:]]
    return "【记忆】" + "；".join(recent)


def add_to_short_term(role, content):
    context_history.append({"role": role, "content": content})
    if len(context_history) > 10:
        context_history.pop(0)


def check_remember_command(user_input):
    for kw in ["记住", "记下", "不要忘记", "别忘了"]:
        if kw in user_input:
            idx = user_input.find(kw) + len(kw)
            content = user_input[idx:].strip()
            if content and len(content) < 200:
                return update_long_term_memory(content)
    return None
