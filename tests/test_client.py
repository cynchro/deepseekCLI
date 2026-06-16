import unittest
from unittest.mock import patch

from core.client import DeepSeekClient, MAX_OUTPUT_TOKENS


def _resp(content, finish_reason, tokens=10):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": tokens, "completion_tokens": tokens,
                  "total_tokens": tokens * 2},
    }


class ChatContinuationTests(unittest.TestCase):
    def test_single_stop_no_continuation(self):
        client = DeepSeekClient(api_key="x")
        with patch.object(client, "_call_api", return_value=_resp("hola", "stop")) as m:
            out = client.chat("hi", auto_continue=True)
        self.assertEqual(out["content"], "hola")
        self.assertFalse(out["truncated"])
        self.assertEqual(out["continuations"], 0)
        self.assertEqual(m.call_count, 1)

    def test_length_triggers_continuation_until_stop(self):
        client = DeepSeekClient(api_key="x")
        responses = [_resp("parte1", "length"),
                     _resp("parte2", "length"),
                     _resp("parte3", "stop")]
        with patch.object(client, "_call_api", side_effect=responses) as m:
            out = client.chat("hi", auto_continue=True, max_continuations=4)
        self.assertEqual(out["content"], "parte1parte2parte3")
        self.assertFalse(out["truncated"])
        self.assertEqual(out["continuations"], 2)
        self.assertEqual(m.call_count, 3)
        # el contenido parcial se reenvía como mensaje assistant para continuar
        sent_messages = m.call_args.args[0]["messages"]
        self.assertTrue(any(msg["role"] == "assistant" for msg in sent_messages))

    def test_continuation_capped_marks_truncated(self):
        client = DeepSeekClient(api_key="x")
        with patch.object(client, "_call_api",
                          return_value=_resp("x", "length")) as m:
            out = client.chat("hi", auto_continue=True, max_continuations=2)
        # 1 inicial + 2 continuaciones = 3 llamadas, y sigue truncado
        self.assertEqual(m.call_count, 3)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["continuations"], 2)

    def test_no_auto_continue_keeps_legacy_behavior(self):
        client = DeepSeekClient(api_key="x")
        with patch.object(client, "_call_api",
                          return_value=_resp("corto", "length")) as m:
            out = client.chat("hi")  # auto_continue=False por defecto
        self.assertEqual(m.call_count, 1)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["content"], "corto")

    def test_max_tokens_clamped_to_hard_limit(self):
        client = DeepSeekClient(api_key="x")
        with patch.object(client, "_call_api", return_value=_resp("ok", "stop")) as m:
            client.chat("hi", max_tokens=99999)
        self.assertEqual(m.call_args.args[0]["max_tokens"], MAX_OUTPUT_TOKENS)


if __name__ == "__main__":
    unittest.main()
