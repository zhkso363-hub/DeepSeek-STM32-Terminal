"""
联网搜索 — Tavily API 封装
"""
import os
import requests

# 从 .env 读 key
_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.isfile(_env):
    for _line in open(_env, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"

_SEARCH_TRIGGERS = [
    # 时间/日期
    "时间", "几点", "日期", "今天星期", "现在", "当前", "目前", "实时",
    # 天气
    "天气", "温度", "下雨", "下雪", "台风", "空气质量",
    # 新闻/最新
    "新闻", "最新", "最近", "发生了什么", "热点",
    # 搜索动词
    "搜索", "查询", "查一下", "搜一下", "找一下",
    # 百科/知识
    "是什么", "是谁", "什么是", "谁是", "在哪里",
    "tell me about", "what is", "who is", "where is",
    "how to", "what's", "meaning of",
]


def should_search(query):
    q = query.lower().strip()
    if len(q) < 5:
        return False
    for kw in _SEARCH_TRIGGERS:
        if kw in q:
            return True
    return False


def search_web(query):
    if not TAVILY_API_KEY:
        return "[搜索不可用：未配置 TAVILY_API_KEY]"
    try:
        resp = requests.post(TAVILY_URL, json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": 2,
            "search_depth": "basic"
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return "未找到相关搜索结果。"
        lines = ["【搜索结果】"]
        for r in results[:2]:
            title = r.get("title", "")
            content = r.get("content", "")
            lines.append(f"- {title}: {content[:200]}")
        return "\n".join(lines)
    except Exception as e:
        return f"[搜索出错：{e}]"
