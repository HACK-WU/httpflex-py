"""httpflex 端到端测试用的 Demo HTTP 服务器

使用 Python 标准库 ``http.server`` 实现一个零依赖、可真实监听的 HTTP 服务，
覆盖 httpflex 各组件需要真实流量验证的场景：

- 各 HTTP 方法（GET/POST/PUT/PATCH/DELETE）与查询参数 / JSON 请求体回显
- 路径变量（``/users/{user_id}``、``/users/{user_id}/posts/{post_id}``）
- 请求头 / 认证头回显与校验
- 404 / 500 / 任意状态码（用于错误与重试测试）
- 慢响应（用于超时测试）
- 分块流式响应（用于 StreamResponseParser）
- 文件下载（用于 FileWriteResponseParser）
- 自增计数器（用于缓存命中验证）

服务器通过 ``run_demo_server()`` 在后台线程启动，返回 ``ThreadingHTTPServer`` 实例；
其 ``server_address`` 提供动态端口，测试据此构造 ``base_url``。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# 自增计数器（多线程共享，仅用于缓存命中验证）
_COUNTER = {"n": 0}
# 不稳定端点：前 N 次返回 500，之后返回 200（用于验证重试确实生效）
_UNSTABLE = {"n": 0}
# 记录服务器收到的请求总数（仅用于调试 / 诊断）
_REQUEST_COUNT = {"n": 0}


class DemoRequestHandler(BaseHTTPRequestHandler):
    """Demo 服务器请求处理器，所有方法统一由 ``_handle`` 路由。"""

    # 使用 HTTP/1.1 以正确支持分块（chunked）流式响应
    protocol_version = "HTTP/1.1"

    # 关闭默认访问日志（避免刷屏），改用 logging 的 debug 级别
    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("DemoServer: " + fmt, *args)

    # ========== HTTP 方法入口 ==========
    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    # ========== 辅助方法 ==========
    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _send_json(self, code: int, payload: Any, extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        code: int,
        body: bytes,
        content_type: str = "application/octet-stream",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    # ========== 路由 ==========
    def _handle(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query, keep_blank_values=True)
        query = {k: (v[0] if len(v) == 1 else v) for k, v in qs.items()}
        method = self.command

        _REQUEST_COUNT["n"] += 1

        # --- 健康检查 ---
        if path == "/health" and method == "GET":
            return self._send_json(200, {"status": "ok", "method": method})

        # --- 通用 GET：回显查询参数 + 自定义请求头 ---
        if path == "/get" and method == "GET":
            return self._send_json(
                200,
                {
                    "method": method,
                    "query": query,
                    "echo_header": self.headers.get("X-Echo"),
                },
            )

        # --- POST/PUT/PATCH：回显 JSON 请求体 ---
        if path == "/post":
            if method in ("POST", "PUT", "PATCH"):
                raw = self._read_body()
                try:
                    data = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    data = {"raw": raw.decode("utf-8", "replace")}
                code = 201 if method == "POST" else 200
                return self._send_json(code, {"method": method, "received": data})

        # --- DELETE ---
        if path == "/delete" and method == "DELETE":
            return self._send_json(200, {"method": method, "deleted": True})

        # --- 路径变量 /users/{user_id} ---
        m = re.match(r"^/users/(\w+)$", path)
        if m and method == "GET":
            return self._send_json(200, {"user_id": m.group(1), "query": query})

        # --- 路径变量 /users/{user_id}/posts/{post_id} ---
        m = re.match(r"^/users/(\w+)/posts/(\w+)$", path)
        if m and method == "GET":
            return self._send_json(200, {"user_id": m.group(1), "post_id": m.group(2)})

        # --- 回显所有请求头 ---
        if path == "/echo-headers" and method == "GET":
            return self._send_json(200, {"headers": {k: v for k, v in self.headers.items()}})

        # --- 认证：要求 Authorization: Bearer secret-token ---
        if path == "/auth" and method == "GET":
            auth = self.headers.get("Authorization", "")
            if auth == "Bearer secret-token":
                return self._send_json(200, {"authenticated": True, "user": "demo"})
            return self._send_json(
                401,
                {"detail": "Unauthorized"},
                extra_headers={"WWW-Authenticate": "Bearer"},
            )

        # --- 404 ---
        if path == "/notfound" and method == "GET":
            return self._send_json(404, {"detail": "Not Found"})

        # --- 500（用于重试测试） ---
        if path == "/error" and method == "GET":
            return self._send_json(500, {"detail": "Internal Server Error"})

        # --- 慢响应（用于超时测试） ?delay=秒 ---
        if path == "/slow" and method == "GET":
            delay = float(query.get("delay", "2"))
            time.sleep(min(delay, 30))
            return self._send_json(200, {"slept": delay})

        # --- 自增计数器（用于缓存命中验证） ---
        if path == "/counter" and method == "GET":
            _COUNTER["n"] += 1
            return self._send_json(200, {"count": _COUNTER["n"]})

        # --- 分块流式响应（用于 StreamResponseParser） ---
        if path == "/stream" and method == "GET":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(5):
                chunk = f"chunk-{i}\n".encode()
                self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"0\r\n\r\n")
            return

        # --- 文件下载（用于 FileWriteResponseParser） ---
        if path == "/download" and method == "GET":
            content = b"httpflex-download-content\n" * 50
            return self._send_bytes(
                200,
                content,
                content_type="application/octet-stream",
                extra_headers={"Content-Disposition": 'attachment; filename="demo.bin"'},
            )

        # --- 任意状态码（用于响应验证器测试） /status/{code} ---
        m = re.match(r"^/status/(\d+)$", path)
        if m and method == "GET":
            code = int(m.group(1))
            return self._send_json(code, {"code": code})

        # --- 每次返回不同随机值（用于验证缓存 refresh / clear / 用户隔离） ---
        if path == "/nonce" and method == "GET":
            return self._send_json(200, {"nonce": uuid.uuid4().hex})

        # --- 不稳定端点：前 fail 次返回 500，之后返回 200（验证重试生效） ---
        if path == "/unstable" and method == "GET":
            _UNSTABLE["n"] += 1
            fail = int(query.get("fail", "1"))
            if _UNSTABLE["n"] <= fail:
                return self._send_json(500, {"detail": "temporarily unavailable", "attempt": _UNSTABLE["n"]})
            return self._send_json(200, {"status": "ok", "attempt": _UNSTABLE["n"]})

        # --- 未匹配路由 ---
        return self._send_json(404, {"detail": f"No route for {method} {path}"})


def run_demo_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """在后台守护线程启动 demo 服务器，返回 server 实例。

    参数:
        host: 监听地址，默认 127.0.0.1
        port: 监听端口，默认 0 表示由系统分配空闲端口

    返回:
        ThreadingHTTPServer 实例；通过 ``.server_address`` 获取 (host, port)
    """
    server = ThreadingHTTPServer((host, port), DemoRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("DemoServer started on %s:%s", host, server.server_address[1])
    return server


def reset_demo_state() -> None:
    """重置服务器全局状态（计数器等），便于测试间隔离。"""
    _COUNTER["n"] = 0
    _UNSTABLE["n"] = 0
    _REQUEST_COUNT["n"] = 0
