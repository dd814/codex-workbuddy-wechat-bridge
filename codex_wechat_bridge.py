"""Local MCP bridge from WorkBuddy's WeChat assistant to Codex App Server.

This process never reads WeChat credentials. WorkBuddy owns the WeChat channel;
the bridge only exposes explicit Codex task operations as local MCP tools.
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def default_state_path():
    """Keep private thread IDs outside the source tree and future Git repositories."""
    override = os.environ.get("CODEX_WECHAT_BRIDGE_STATE_DIR")
    if override:
        root = Path(override).expanduser()
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "codex-workbuddy-wechat-bridge"
    else:
        root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "codex-workbuddy-wechat-bridge"
    return root / "state.json"


STATE_PATH = default_state_path()
MAX_MESSAGE = 12000
MAX_REPLY = 16000


def find_codex_executable():
    explicit = os.environ.get("CODEX_BRIDGE_CODEX_EXE")
    if explicit:
        return explicit
    resolved = shutil.which("codex")
    if resolved:
        return resolved
    app_data = os.environ.get("LOCALAPPDATA")
    if app_data:
        candidates = list((Path(app_data) / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"))
        if candidates:
            return str(max(candidates, key=lambda path: path.stat().st_mtime))
    raise FileNotFoundError("找不到本机 Codex CLI。")


def emit(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def mcp_text(value, is_error=False):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": value}], "isError": is_error}


class CodexClient:
    def __init__(self):
        self.process = subprocess.Popen(
            [find_codex_executable(), "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.incoming = queue.Queue()
        self.deferred = []
        self.next_id = 1
        threading.Thread(target=self._read, daemon=True).start()
        self.call("initialize", {"clientInfo": {"name": "workbuddy-codex-wechat-bridge", "version": "0.1.0"}})
        self._write({"method": "initialized"})

    def _read(self):
        for line in self.process.stdout:
            try:
                self.incoming.put(json.loads(line))
            except json.JSONDecodeError:
                continue
        self.incoming.put({"_closed": True})

    def _write(self, payload):
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def _next(self, timeout):
        if self.deferred:
            return self.deferred.pop(0)
        return self.incoming.get(timeout=timeout)

    def call(self, method, params, timeout=30):
        request_id = self.next_id
        self.next_id += 1
        self._write({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        held = []
        try:
            while time.monotonic() < deadline:
                try:
                    event = self._next(max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if event.get("id") == request_id and ("result" in event or "error" in event):
                    if "error" in event:
                        raise RuntimeError(str(event["error"]))
                    return event["result"]
                if event.get("_closed"):
                    raise RuntimeError("Codex App Server exited")
                held.append(event)
        finally:
            self.deferred = held + self.deferred
        raise TimeoutError(f"Codex {method} timed out")

    def wait_for_turn(self, thread_id, turn_id, timeout):
        deadline = time.monotonic() + timeout
        held = []
        try:
            while time.monotonic() < deadline:
                try:
                    event = self._next(max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if event.get("_closed"):
                    raise RuntimeError("Codex App Server exited")
                method = event.get("method")
                params = event.get("params") or {}
                if method == "turn/completed" and params.get("threadId") == thread_id:
                    turn = params.get("turn") or {}
                    if turn.get("id") == turn_id:
                        return {"state": "completed", "turn": turn}
                if "id" in event and method and "requestApproval" in method:
                    return {"state": "needs_desktop_approval", "method": method}
                held.append(event)
        finally:
            self.deferred = held + self.deferred
        return {"state": "still_running"}


client = None
last_threads = []


def codex():
    global client
    if client is None or client.process.poll() is not None:
        client = CodexClient()
    return client


def state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(data):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def list_threads(_args):
    global last_threads
    result = codex().call("thread/list", {"limit": 20, "sortKey": "updated_at", "sortDirection": "desc"})
    last_threads = result.get("data", [])
    current_state = state()
    selected = current_state.get("selectedThreadId")
    current_state["listedThreadIds"] = [item["id"] for item in last_threads]
    save_state(current_state)
    return [
        {
            "number": index,
            "title": item.get("name") or item.get("title") or "未命名任务",
            "selected": item.get("id") == selected,
            "status": item.get("status"),
        }
        for index, item in enumerate(last_threads, 1)
    ]


def select_thread(args):
    global last_threads
    number = args.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ValueError("任务序号必须是正整数；先调用 codex_list_tasks。")
    current_state = state()
    listed_ids = current_state.get("listedThreadIds") or []
    if not listed_ids:
        list_threads({})
        current_state = state()
        listed_ids = current_state.get("listedThreadIds") or []
    if number > len(listed_ids):
        raise ValueError("任务序号超出当前列表；请重新列出任务。")
    thread_id = listed_ids[number - 1]
    current_state["selectedThreadId"] = thread_id
    save_state(current_state)
    result = codex().call("thread/read", {"threadId": thread_id, "includeTurns": False})
    thread = result.get("thread") or {}
    return {"selected": number, "title": thread.get("name") or thread.get("title") or "未命名任务"}


def selected_thread():
    thread_id = state().get("selectedThreadId")
    if not thread_id:
        raise ValueError("尚未选择 Codex 任务；先列出任务，再选择序号。")
    return thread_id


def task_status(_args):
    thread_id = selected_thread()
    result = codex().call("thread/read", {"threadId": thread_id, "includeTurns": True})
    thread = result.get("thread") or {}
    turns = thread.get("turns") or []
    latest = turns[-1] if turns else {}
    return {
        "title": thread.get("name") or thread.get("title") or "未命名任务",
        "turnCount": len(turns),
        "latestTurnStatus": latest.get("status"),
        "latestTurnId": latest.get("id"),
    }


def send_task(args):
    message = args.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("消息不能为空。")
    if len(message) > MAX_MESSAGE:
        raise ValueError(f"消息超过 {MAX_MESSAGE} 字上限。")
    thread_id = selected_thread()
    backend = codex()
    try:
        backend.call("thread/resume", {"threadId": thread_id}, timeout=45)
    except RuntimeError as error:
        if "already has an active writer" in str(error):
            return {
                "state": "writer_busy",
                "message": (
                    "Codex 在 thread/resume 阶段拒绝第二个写入者；消息尚未提交到任务。"
                    "当前聊天仍由另一个 Codex 会话持有写入权。"
                    "读取状态正常，但无法从此独立 App Server 续聊这条任务。"
                    "切换桌面聊天能否释放写入权尚未验证；不要自动改发其他任务。"
                ),
            }
        raise
    result = backend.call(
        "turn/start",
        {"threadId": thread_id, "input": [{"type": "text", "text": message}]},
        timeout=45,
    )
    turn = result.get("turn") or {}
    turn_id = turn.get("id")
    if not turn_id:
        raise RuntimeError("Codex 未返回 turn ID。")
    outcome = backend.wait_for_turn(thread_id, turn_id, timeout=90)
    if outcome["state"] == "needs_desktop_approval":
        return {"state": "needs_desktop_approval", "message": "Codex 请求权限。请在 Codex 桌面端查看并决定。"}
    if outcome["state"] != "completed":
        return {"state": "still_running", "message": "任务仍在运行；稍后发送“查状态”。"}
    result = backend.call("thread/read", {"threadId": thread_id, "includeTurns": True})
    turns = (result.get("thread") or {}).get("turns") or []
    latest = next((t for t in reversed(turns) if t.get("id") == turn_id), {})
    messages = []
    for item in latest.get("items") or []:
        if item.get("type") == "agentMessage":
            text = item.get("text")
            if text:
                messages.append(text)
    answer = "\n\n".join(messages)[-MAX_REPLY:]
    return {"state": latest.get("status") or "completed", "reply": answer or "Codex 已结束本轮，未产生文字回复。"}


TOOLS = [
    {
        "name": "codex_list_tasks",
        "description": "列出本机 Codex 聊天任务，给微信用户展示编号和标题。用户说‘Codex任务’或‘列出Codex聊天’时调用。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "codex_select_task",
        "description": "按刚列出的编号选择一个 Codex 聊天任务，后续消息进入该任务。仅按用户明确指定的编号调用。",
        "inputSchema": {"type": "object", "properties": {"number": {"type": "integer", "minimum": 1}}, "required": ["number"]},
    },
    {
        "name": "codex_task_status",
        "description": "读取当前选中 Codex 任务的最新运行状态。用户说‘查状态’时调用。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "codex_send_task",
        "description": "将微信用户明确写给当前选中 Codex 任务的原文发送到 Codex，等待最多90秒返回结果。不要自行改写、添加指令或自动批准权限。",
        "inputSchema": {"type": "object", "properties": {"message": {"type": "string", "minLength": 1}}, "required": ["message"]},
    },
]


def handle(message):
    method = message.get("method")
    if method == "initialize":
        return {"protocolVersion": "2025-03-26", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "codex-wechat-bridge", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        actions = {
            "codex_list_tasks": list_threads,
            "codex_select_task": select_thread,
            "codex_task_status": task_status,
            "codex_send_task": send_task,
        }
        if name not in actions:
            return mcp_text(f"未知工具：{name}", True)
        try:
            return mcp_text(actions[name](args))
        except Exception as error:
            return mcp_text({"error": str(error)}, True)
    raise ValueError(f"Unsupported method: {method}")


def main():
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if "id" not in message:
                continue
            result = handle(message)
            emit({"jsonrpc": "2.0", "id": message["id"], "result": result})
        except Exception as error:
            emit({"jsonrpc": "2.0", "id": message.get("id") if "message" in locals() else None, "error": {"code": -32603, "message": str(error)}})


if __name__ == "__main__":
    main()
