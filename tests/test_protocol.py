"""The public package responds to MCP discovery without touching a Codex chat."""

import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "src" / "codex_wechat_bridge.py"


class ProtocolTest(unittest.TestCase):
    def test_handshake_and_tools(self):
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            for request_id, method in ((1, "initialize"), (2, "tools/list")):
                process.stdin.write(json.dumps({"id": request_id, "method": method, "params": {}}) + "\n")
                process.stdin.flush()
                response = json.loads(process.stdout.readline())
                self.assertEqual(response["id"], request_id)
                self.assertIn("result", response)
                if method == "tools/list":
                    self.assertEqual(len(response["result"]["tools"]), 4)
        finally:
            process.terminate()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
