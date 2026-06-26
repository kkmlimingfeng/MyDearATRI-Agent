"""
系统内置工具 - 天气查询工具
从 8_Agent.ipynb 提取
"""
import requests


def get_weather(city: str) -> str:
    """
    通过调用 wttr.in API 查询今天真实的天气信息。
    
    Args:
        city: 城市名称，如 "北京"、"苏州"
    
    Returns:
        天气信息字符串，格式如 "北京当前天气:Sunny，气温26摄氏度"
        如果出错，返回错误信息
    """
    # API端点，我们请求JSON格式的数据
    url = f"https://wttr.in/{city}?format=j1"
    
    try:
        # 发起网络请求
        response = requests.get(url)
        # 检查响应状态码是否为200 (成功)
        response.raise_for_status() 
        # 解析返回的JSON数据
        data = response.json()
            
        # 提取当前天气状况
        current_condition = data['current_condition'][0]
        weather_desc = current_condition['weatherDesc'][0]['value']
        temp_c = current_condition['temp_C']
        
        # 格式化成自然语言返回
        return f"{city}当前天气:{weather_desc}，气温{temp_c}摄氏度"
        
    except requests.exceptions.RequestException as e:
        # 处理网络错误
        return f"错误:查询天气时遇到网络问题 - {e}"
    except (KeyError, IndexError) as e:
        # 处理数据解析错误
        return f"错误:解析天气数据失败，可能是城市名称无效 - {e}"
