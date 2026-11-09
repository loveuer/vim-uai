import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

from support import FakeAPI


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKER = ROOT / "python" / "vim_uai_request.py"
sys.path.insert(0, str(ROOT / "python"))
spec = importlib.util.spec_from_file_location("vim_uai_request", WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI().__enter__()
        self.addCleanup(self.api.__exit__)
        self.config = {
            "provider": "openai", "api_base": self.api.base, "api_key": "test-secret",
            "model": "test-model", "timeout": 2, "max_tokens": 2048,
            "edit": {"instruction": "实现 TODO", "selection": {"text": "    # TODO"}},
        }

    def test_openai_request_and_indentation(self):
        self.assertEqual(worker.generate(self.config), ["    value = 42", "    return value"])
        request = self.api.requests[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer test-secret")
        self.assertEqual(request["body"]["model"], "test-model")
        self.assertFalse(request["body"]["stream"])
        self.assertEqual([m["role"] for m in request["body"]["messages"]], ["system", "user"])
        self.assertEqual(json.loads(request["body"]["messages"][1]["content"]), self.config["edit"])

    def test_anthropic_request(self):
        self.config["provider"] = "anthropic"
        self.assertEqual(worker.generate(self.config), ["    value = 42", "    return value"])
        request = self.api.requests[0]
        self.assertEqual(request["path"], "/v1/messages")
        self.assertEqual(request["headers"]["x-api-key"], "test-secret")
        self.assertEqual(request["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(request["body"]["max_tokens"], 2048)
        self.assertIn("system", request["body"])
        self.assertEqual([m["role"] for m in request["body"]["messages"]], ["user"])

    def test_local_endpoint_without_key(self):
        self.config["api_key"] = ""
        worker.generate(self.config)
        self.assertIsNone(self.api.requests[0]["headers"].get("Authorization"))

    def test_fences_crlf_and_blank_lines(self):
        self.api.text = "```python\r\n    a = 1\r\n\r\n    return a\r\n```\r\n"
        self.assertEqual(worker.generate(self.config), ["    a = 1", "", "    return a"])

    def test_anthropic_text_blocks(self):
        self.config["provider"] = "anthropic"
        self.api.response = {"content": [{"type": "thinking", "thinking": "hidden"},
                                         {"type": "text", "text": "one"},
                                         {"type": "text", "text": "two"}], "stop_reason": "end_turn"}
        self.assertEqual(worker.generate(self.config), ["one", "two"])

    def test_truncated_and_tool_responses_rejected(self):
        for reason in ("length", "tool_calls", "content_filter"):
            self.api.response = {"choices": [{"message": {"content": "partial"}, "finish_reason": reason}]}
            with self.assertRaises(worker.RequestError):
                worker.generate(self.config)
        self.config["provider"] = "anthropic"
        for reason in ("max_tokens", "tool_use", "refusal"):
            self.api.response = {"content": [{"type": "text", "text": "partial"}], "stop_reason": reason}
            with self.assertRaises(worker.RequestError):
                worker.generate(self.config)

    def test_http_error_redacts_key_in_worker_output(self):
        self.api.status = 401
        self.api.response = {"error": {"message": "bad key test-secret"}}
        result = subprocess.run([sys.executable, str(WORKER)], input=json.dumps(self.config),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("test-secret", result.stdout + result.stderr)
        self.assertIn("HTTP 401", json.loads(result.stdout)["error"])

    def test_invalid_and_empty_responses(self):
        for response in (b"not json", [], {}, {"choices": []},
                         {"choices": [{"message": {"content": "  "}}]},
                         {"choices": [{"message": {"content": "```\n```"}}]},
                         {"choices": [{"message": {"content": "x\x00y"}}]}):
            self.api.response = response
            with self.subTest(response=response), self.assertRaises(worker.RequestError):
                worker.generate(self.config)

    def test_timeout(self):
        self.api.delay = 0.1
        self.config["timeout"] = 0.01
        with self.assertRaisesRegex(worker.RequestError, "timed out"):
            worker.generate(self.config)

    def test_configuration_validation(self):
        for field, value in (("provider", "unknown"), ("model", ""),
                             ("api_base", "file:///tmp/test"), ("timeout", 0)):
            config = dict(self.config, **{field: value})
            with self.subTest(field=field), self.assertRaises(worker.RequestError):
                worker.generate(config)


if __name__ == "__main__":
    unittest.main()
