"""
系统内置工具 - 获取当前时间/日期
"""
from datetime import datetime
from modules.tools.base_tool import system_tool


@system_tool
def get_current_time() -> str:
    """
    当用户问现在几点时，获取当前时间（24小时制）。

    Args:
        无

    Returns:
        当前时间字符串，格式如 "17:35"。

    Example:
        get_current_time()
    """
    return datetime.now().strftime("%H:%M")


@system_tool
def get_current_date() -> str:
    """
    当用户问今天几号时，获取当前日期。

    Args:
        无

    Returns:
        当前日期字符串，格式如 "2026-06-29"。

    Example:
        get_current_date()
    """
    return datetime.now().strftime("%Y-%m-%d")


@system_tool
def get_current_datetime() -> str:
    """
    获取当前日期、星期几和时间（24小时制）。

    Args:
        无

    Returns:
        当前日期时间字符串，格式如 "2026-05-01 周五 18:21"。

    Example:
        get_current_datetime()
    """
    now = datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekdays[now.weekday()]
    return now.strftime(f"%Y-%m-%d {weekday} %H:%M")

@system_tool
def get_current_weekday() -> str:
    """
    当用户问今天是星期几或者周几时，获取当前星期几或者周几。

    Args:
        无

    Returns:
        当前日期时间字符串，格式如 "周五"。

    Example:
        get_current_weekday()
    """
    now = datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekdays[now.weekday()]
    return weekday