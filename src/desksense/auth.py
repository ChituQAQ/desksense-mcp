"""DeskSense 鉴权模块。

使用 Bearer Token，安全字符串比较（hmac.compare_digest）。
API Key 只从环境变量或 .secrets/API_KEY.txt 读取，绝不写进代码。
"""
from __future__ import annotations

import hmac
import secrets

from .config import Config, api_key_from_env_or_file


def get_api_key(cfg: Config) -> str | None:
    """读取当前生效的 API Key（环境变量优先，其次 .secrets/API_KEY.txt）。"""
    return api_key_from_env_or_file(cfg)


def check_token(token: str | None, cfg: Config) -> bool:
    """使用安全比较判断 Bearer Token 是否正确。"""
    if not token:
        return False
    key = get_api_key(cfg)
    if not key:
        return False
    return hmac.compare_digest(token.strip(), key)


def extract_bearer(header: str | None) -> str | None:
    """从 Authorization header 中提取 Bearer token。"""
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip()


def generate_api_key() -> str:
    """生成 32 bytes 随机 -> 64 位 hex。"""
    return secrets.token_hex(32)