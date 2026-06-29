"""
系统内置工具 - 天气查询
从 8_Agent.ipynb 提取
"""
import requests
from modules.tools.base_tool import system_tool


@system_tool
def get_weather(city: str) -> str:
    """
    查询指定城市的实时天气信息。

    Args:
        city: 城市名称，如 "北京"、"苏州"

    Returns:
        天气信息字符串，格式如 "苏州当前天气:晴，气温26摄氏度"。
        如果查询失败，返回错误信息。

    Example:
        get_weather(city="苏州")
    """
    url = f"https://wttr.in/{city}?format=j1&lang=zh-cn"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        current_condition = data['current_condition'][0]
        weather_desc = current_condition['lang_zh-cn'][0]['value'] # 中文返回
        temp_c = current_condition['temp_C']

        return f"{city}当前天气:{weather_desc}，气温{temp_c}摄氏度"

    except requests.exceptions.RequestException as e:
        return f"错误:查询天气时遇到网络问题 - {e}"
    except (KeyError, IndexError) as e:
        return f"错误:解析天气数据失败，可能是城市名称无效 - {e}"
