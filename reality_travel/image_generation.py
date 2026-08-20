"""Optional adapter for a configured postcard image generator module."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Awaitable, Callable

from .config import IMAGE_GENERATOR_FUNCTION, IMAGE_GENERATOR_MODULE, POSTCARD_IMAGE_DIR


ImageGenerator = Callable[[str], Awaitable[Path]]


def _load_generator():
    if IMAGE_GENERATOR_MODULE is None:
        raise RuntimeError(
            "明信片生图未配置；可只保存文字，或设置 REALITY_TRAVEL_IMAGE_GENERATOR_MODULE。"
        )
    module_path = IMAGE_GENERATOR_MODULE.resolve()
    if not module_path.is_file():
        raise RuntimeError(f"找不到已配置的明信片生图模块：{module_path}")
    spec = importlib.util.spec_from_file_location("kpax_codex_image_gen", module_path)
    if not spec or not spec.loader:
        raise RuntimeError("无法加载已配置的明信片生图模块")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generator = getattr(module, IMAGE_GENERATOR_FUNCTION, None)
    if not callable(generator):
        raise RuntimeError(f"生图模块未提供可调用函数：{IMAGE_GENERATOR_FUNCTION}")
    return generator


async def generate_postcard_image(prompt: str) -> Path:
    generator = _load_generator()
    return await generator(prompt, POSTCARD_IMAGE_DIR, filename_prefix="postcard")
