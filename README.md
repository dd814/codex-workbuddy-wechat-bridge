# Codex ↔ WorkBuddy 微信桥接

通过 WorkBuddy 已连接的「微信助理」，在个人微信里列出、选择并继续本机现有的 Codex 聊天。桥接器是一个本地 MCP stdio 服务；它不直接登录微信，也不读取微信凭证。

## 能做什么

- 列出最近 20 条 Codex 聊天，按编号选择其中一条。
- 查看所选聊天的状态，向**同一个聊天 ID**提交消息并读取文字回复。
- 当另一进程占用该聊天的写入权时，明确返回 `writer_busy`；不会改发其他聊天或创建副本。

目前不能主动向个人微信推送后台事件。Codex 的权限请求也可能需要在桌面端处理。WorkBuddy 的助理模型可能改写用户消息，因此发送重要指令后应核对实际提交内容。

## 环境

- Windows 上的 WorkBuddy「微信助理」已由用户自行连接，并支持自定义 MCP 服务。
- 本机可运行、已登录的 Codex CLI（支持 `codex app-server`）。
- Python 3.10 或更新版本；桥接器仅使用标准库。
- 电脑和 WorkBuddy 保持运行及联网。

## 安装

克隆或下载此仓库，在 WorkBuddy 的自定义 MCP 配置中添加一个 stdio 服务。Windows 示例（将路径换成你自己的安装位置）：

```json
{
  "mcpServers": {
    "codex-wechat-bridge": {
      "type": "stdio",
      "command": "py",
      "args": ["C:/path/to/codex-workbuddy-wechat-bridge/src/codex_wechat_bridge.py"],
      "description": "在微信助理中列出、选择和继续本机 Codex 聊天",
      "disabled": false
    }
  }
}
```

如果 `codex` 不在 `PATH`，设置环境变量 `CODEX_BRIDGE_CODEX_EXE` 为 `codex.exe` 的绝对路径。若 Codex 使用非默认数据目录，设置 `CODEX_HOME`。配置后在 WorkBuddy 中启用这四个工具：`codex_list_tasks`、`codex_select_task`、`codex_task_status`、`codex_send_task`。

在微信助理中发送「Codex任务」，收到编号列表后回复编号，再明确说明「发给 Codex：……」。桥接器只接收 WorkBuddy 调用工具时传入的消息。

## 本地数据与发布安全

选中的聊天 ID 保存在用户级状态目录中：Windows 的 `%LOCALAPPDATA%/codex-workbuddy-wechat-bridge/state.json`，其他系统的 `$XDG_STATE_HOME/codex-workbuddy-wechat-bridge/state.json`（未设置时为 `~/.local/state/...`）。可用 `CODEX_WECHAT_BRIDGE_STATE_DIR` 改变位置。**不要把此状态文件、WorkBuddy 配置、Codex 会话文件、日志或微信凭证提交到公开仓库。**

本仓库采用文件白名单式 `.gitignore`，只允许公开的源码和文档进入 Git。发布前还应检查待提交文件和提交作者元数据。GitHub 的 secret scanning 主要识别凭证，不能代替姓名、邮箱、聊天标题和本机路径的人工审查。

## 验证

`py -m unittest discover -s tests -v` 验证 MCP 握手与工具清单，不向任何 Codex 聊天发送消息。完整微信链路需在自己的设备上使用无敏感内容的测试消息验证。

## 许可

MIT。见 [LICENSE](LICENSE)。
