"""
系统内置工具 - 景点推荐
"""
import os
from modules.tools.base_tool import system_tool


@system_tool
def get_attraction(city: str, weather: str) -> str:
    """
    根据城市名和天气情况，使用 Tavily Search API 搜索并返回优化后的景点推荐。

    需要安装 tavily-python 并配置环境变量 TAVILY_API_KEY。

    Args:
        city: 城市名称，如 "苏州"
        weather: 天气状况，如 "晴"、"雨天"

    Returns:
        景点推荐文本；
        若搜索失败，返回错误信息。

    Example:
        get_attraction(city="苏州", weather="晴")
    """
    try:
        from tavily import TavilyClient
    except ImportError:
        return "错误:未安装 tavily-python，请执行 pip install tavily-python。"

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return "错误:未配置 TAVILY_API_KEY 环境变量。"

    tavily = TavilyClient(api_key=api_key)
    query = f"'{city}' 在'{weather}'天气下最值得去的旅游景点推荐及理由"

    try:
        response = tavily.search(query=query, search_depth="basic", include_answer=True)

        if response.get("answer"):
            return response["answer"]

        formatted_results = []
        for result in response.get("results", []):
            formatted_results.append(f"- {result['title']}: {result['content']}")

        if not formatted_results:
            return "抱歉，没有找到相关的旅游景点推荐。"

        return "根据搜索，为您找到以下信息:\n" + "\n".join(formatted_results)

    except Exception as e:
        return f"错误:执行 Tavily 搜索时出现问题 - {e}"
