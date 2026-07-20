"""Tests del retry de core/client.py: 4xx no-transitorios deben fallar rápido,
429/5xx sí deben reintentar (core/client.py APIStatusError)."""
from unittest.mock import patch, MagicMock

from core.client import DeepSeekClient


def _make_client():
    c = DeepSeekClient(api_key="sk-test")
    c.retry_delay = 0  # no dormir en el test
    return c


def _fake_response(status_code, body='{"error": {"message": "boom"}}'):
    r = MagicMock()
    r.status_code = status_code
    r.text = body
    r.json.return_value = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    return r


def test_401_fails_without_retrying():
    client = _make_client()
    with patch("core.client._requests.post", return_value=_fake_response(401)) as mock_post:
        result = client.complete([{"role": "user", "content": "hola"}])
    assert result["success"] is False
    assert mock_post.call_count == 1  # ni un reintento: error garantizado


def test_400_fails_without_retrying():
    client = _make_client()
    with patch("core.client._requests.post", return_value=_fake_response(400)) as mock_post:
        result = client.complete([{"role": "user", "content": "hola"}])
    assert result["success"] is False
    assert mock_post.call_count == 1


def test_402_fails_without_retrying():
    client = _make_client()
    with patch("core.client._requests.post", return_value=_fake_response(402)) as mock_post:
        result = client.complete([{"role": "user", "content": "hola"}])
    assert result["success"] is False
    assert mock_post.call_count == 1


def test_429_retries_up_to_max():
    client = _make_client()
    with patch("core.client._requests.post", return_value=_fake_response(429)) as mock_post:
        result = client.complete([{"role": "user", "content": "hola"}])
    assert result["success"] is False
    assert mock_post.call_count == client.max_retries


def test_500_retries_up_to_max():
    client = _make_client()
    with patch("core.client._requests.post", return_value=_fake_response(500)) as mock_post:
        result = client.complete([{"role": "user", "content": "hola"}])
    assert result["success"] is False
    assert mock_post.call_count == client.max_retries


def test_success_returns_content():
    client = _make_client()
    with patch("core.client._requests.post", return_value=_fake_response(200)):
        result = client.complete([{"role": "user", "content": "hola"}])
    assert result["success"] is True
    assert result["content"] == "ok"


def _fake_curl_run(stdout, returncode=0):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = ""
    return r


def test_curl_fallback_detects_http_error_status():
    """Sin requests instalado, el fallback de curl debe leer el status real (-w
    agregado al comando) y fallar rápido en un 401, en vez de reventar más adelante
    con un KeyError al indexar choices[0] de un body de error."""
    client = _make_client()
    body = '{"error": {"message": "Invalid API key"}}'
    fake_result = _fake_curl_run(f"{body}\n401")
    with patch("core.client._HAS_REQUESTS", False), \
         patch("core.client.subprocess.run", return_value=fake_result) as mock_run:
        result = client.complete([{"role": "user", "content": "hola"}])
    assert result["success"] is False
    assert "401" in result["error"]
    assert mock_run.call_count == 1  # 401 no es transitorio: no reintenta


def test_curl_fallback_success_still_parses_body():
    client = _make_client()
    body = '{"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}'
    fake_result = _fake_curl_run(f"{body}\n200")
    with patch("core.client._HAS_REQUESTS", False), \
         patch("core.client.subprocess.run", return_value=fake_result):
        result = client.complete([{"role": "user", "content": "hola"}])
    assert result["success"] is True
    assert result["content"] == "ok"


def test_curl_fallback_retries_on_500():
    client = _make_client()
    fake_result = _fake_curl_run('{"error": {"message": "boom"}}\n500')
    with patch("core.client._HAS_REQUESTS", False), \
         patch("core.client.subprocess.run", return_value=fake_result) as mock_run:
        result = client.complete([{"role": "user", "content": "hola"}])
    assert result["success"] is False
    assert mock_run.call_count == client.max_retries
