---
name: file_operations
description: "当需要创建、读取、覆盖或追加文件内容时使用。通过 exec_sandbox_cmd 工具安全地执行常见文件操作。"
version: "1.0"
---

# 文件操作技能

## 触发场景

当需要进行以下类型的文件操作时，使用本技能：

- 创建新文件或目录
- 读取文件内容
- 覆盖写入文件
- 追加内容到文件末尾
- 查看目录结构

## 可用命令

所有文件操作都通过 `exec_sandbox_cmd` 工具在沙箱中执行。
命令执行时的当前工作目录为项目根目录，因此请使用相对路径。

### 1. 读取文件

```bash
cat /path/to/file
```

示例：

```python
exec_sandbox_cmd(cmd='cat modules/mem/memory.md')
```

### 2. 创建/覆盖文件

```bash
echo "文件内容" > /path/to/file
```

示例：

```python
exec_sandbox_cmd(cmd='echo "# 记忆" > modules/mem/memory.md')
```

### 3. 追加内容到文件

```bash
echo "追加的内容" >> /path/to/file
```

示例：

```python
exec_sandbox_cmd(cmd='echo "- 喜欢晴天" >> modules/mem/memory.md')
```

### 4. 创建目录

```bash
mkdir -p /path/to/dir
```

示例：

```python
exec_sandbox_cmd(cmd='mkdir -p modules/mem')
```

### 5. 列出目录内容

```bash
ls -la modules/mem
```

示例：

```python
exec_sandbox_cmd(cmd='ls -la modules/mem')
```

## 记忆与用户画像写入

### 获取当前日期

```python
exec_sandbox_cmd(cmd="date '+%Y-%m-%d'")
```

### 追加记忆事件

memory.md 记录带时间戳的事件或事实：

```python
exec_sandbox_cmd(cmd='echo "- 2026-06-29 用户提到喜欢晴天" >> modules/mem/memory.md')
```

### 更新用户画像

USER.md 记录用户的静态信息，通常需要先读取再覆盖：

```python
# 1. 读取现有画像
exec_sandbox_cmd(cmd='cat modules/prompt/SystemPrompt/USER.md')

# 2. 覆盖写入更新后的完整画像
exec_sandbox_cmd(cmd="""cat <<'EOF' > modules/prompt/SystemPrompt/USER.md
# USER

## 基本信息
- 称呼：用户
- 常住地：北京

## 偏好
- 喜欢的天气：晴天

## 目标
- 旅行计划：想去故宫
EOF""")
```

## 重要规则

- memory 文件统一使用相对路径 `modules/mem/memory.md`。
- USER.md 统一使用相对路径 `modules/prompt/SystemPrompt/USER.md`。
- 写入前先读取文件检查是否存在，避免误覆盖。
- 删除文件前必须获得用户明确确认。
- 不要尝试访问 `SANDBOX_WRITE_PATH` 之外的目录。
- 多行内容写入时，优先使用 `cat <<'EOF' > file` 或 `printf`。
