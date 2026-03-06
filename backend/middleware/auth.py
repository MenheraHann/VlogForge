"""
API Key 认证中间件
环境变量 VLOGFORGE_API_KEY 设了就启用认证，没设就跳过（开发无感）
"""

import os
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

VLOGFORGE_API_KEY = os.getenv("VLOGFORGE_API_KEY", "")


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    API Key 认证中间件:
    - VLOGFORGE_API_KEY 为空时完全跳过认证
    - OPTIONS 请求放行（CORS preflight）
    - /health, /assets/*, /artifacts/*, / (前端) 放行
    - /api/* 路由要求 Authorization: Bearer <key>
    """

    async def dispatch(self, request: Request, call_next):
        # 未配置 API Key 则跳过认证
        if not VLOGFORGE_API_KEY:
            return await call_next(request)

        # OPTIONS 放行（CORS preflight）
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # 公开路由放行
        if path == "/health" or path == "/":
            return await call_next(request)
        if path.startswith("/assets/") or path.startswith("/artifacts/"):
            return await call_next(request)
        # 前端静态资源放行
        if not path.startswith("/api/"):
            return await call_next(request)

        # /api/* 路由需要认证
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token == VLOGFORGE_API_KEY:
                return await call_next(request)

        logger.warning(f"[Auth] 认证失败: {request.method} {path}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key"},
        )
