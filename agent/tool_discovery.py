"""Small callable surface for discovering tools before exposing their schemas."""

LIST_TOOLS = "atri_list_available_tools"
GET_TOOL_USAGE = "atri_get_tool_usage"

TOOL_DISCOVERY_TEXT = (
    "本轮可用工具的名称、参数和用途已通过工具定义提供；需要工具时直接调用对应工具。"
    "技能说明按需读取，只有在技能与当前请求相关时才加载。"
)


def discovery_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": LIST_TOOLS,
                "description": "列出当前已启用的工具及其简短用途。",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": GET_TOOL_USAGE,
                "description": "读取一个已启用工具的完整参数定义，并将它加入下一轮可调用工具。",
                "parameters": {
                    "type": "object",
                    "properties": {"tool_name": {"type": "string", "description": "工具列表中的准确名称"}},
                    "required": ["tool_name"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def merge_schemas(*groups: list[dict]) -> list[dict]:
    merged = {}
    for group in groups:
        for schema in group:
            function = schema.get("function") or {}
            name = function.get("name")
            if name:
                merged[name] = schema
    return list(merged.values())
