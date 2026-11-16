"""อ่าน/เขียน config.yaml แบบรักษาคอมเมนต์และลำดับบรรทัด (ใช้ ruamel.yaml, license MIT).

GUI และ keys เดิมใช้ yaml.safe_dump ซึ่งทำให้คอมเมนต์ในไฟล์หายทั้งหมดเมื่อกดปุ่มที่เขียน config
โมดูลนี้แทนที่จุดอ่าน/เขียน config ทั้งหมด เพื่อให้ไฟล์ที่ผู้ใช้เขียนไว้ยังอยู่ครบหลังบันทึก
"""
from __future__ import annotations

from io import StringIO
from typing import Any

from ruamel.yaml import YAML


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.allow_unicode = True
    y.width = 4096  # ไม่ตัดบรรทัดยาว
    # เขียน None เป็น null (ไม่ใช่ค่าว่าง) เหมือน safe_dump เดิม
    y.representer.add_representer(
        type(None), lambda rep, _data: rep.represent_scalar("tag:yaml.org,2002:null", "null"))
    return y


def load_text(text: str) -> Any:
    """คืน CommentedMap (dict-like) ที่จำคอมเมนต์ไว้; ไฟล์ว่างคืน None"""
    return _yaml().load(text)


def dump_text(data: Any) -> str:
    buf = StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()
