---
name: codex-workbuddy-wechat-bridge
description: 给已连接个人微信的 WorkBuddy 微信助理配置本机 Codex MCP 桥接，或排查列出、选取和继续现有 Codex 聊天的流程。用于用户明确提出微信桥接、WorkBuddy 调用 Codex 或调试这一桥接时。
---

# WorkBuddy 微信桥接

桥接是本机运行的 Python stdio MCP 服务。它使用 WorkBuddy 已连接的微信助理接受请求，再对用户指定的 Codex 聊天发起操作。

- 配置和排查先读 [桥接工具说明](README.md)。工作环境须有已登录的 Codex CLI、支持自定义 MCP 的 WorkBuddy 和 Python 3.10 或更新版本。
- 将说明里的 MCP 脚本路径换成此技能目录下 [实际脚本](src/codex_wechat_bridge.py) 的绝对路径。请用户自行完成客户端要求的账号授权。
- 聊天目标必须明确。带副作用的发消息操作仅在用户明确要求向指定聊天提交具体内容后执行。出现 `writer_busy` 时如实报告，让用户决定留在原聊天还是另外处理。
- 先用 `python -m unittest discover -s tests -v` 在仓库根目录验证本地协议。它不向任何真实聊天发送消息。状态、日志、真实聊天和本机配置留在运行环境中。

工具许可见 [MIT LICENSE](LICENSE)。
