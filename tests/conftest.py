"""Pytest 配置：确保 src 在 sys.path。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))