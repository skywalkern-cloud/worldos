#!/usr/bin/env python3
"""
NaN 根治回归测试：_sanitize + write_json_strict 必须产出严格合法 JSON。

用法: python3 scripts/test_no_nan_json.py
"""
import importlib.util
import json
import math
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
MODULES = ("fetch_worldos_data", "generate_commentary_llm", "commentary_generator")


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def reject_constant(token):
    # 故意用异常打断：出现裸 NaN / Infinity 字面量即失败
    raise ZeroDivisionError(f"非法 JSON 常量: {token}")


def main():
    payload = {"a": float("nan"), "b": {"c": float("inf")}, "d": [float("-inf"), 1.5, None]}
    expected = {"a": None, "b": {"c": None}, "d": [None, 1.5, None]}

    for name in MODULES:
        mod = load_module(name)

        clean = mod._sanitize(payload)
        assert clean == expected, f"{name}._sanitize 结果错误: {clean!r}"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            mod.write_json_strict(out, payload)
            text = out.read_text(encoding="utf-8")

            assert "NaN" not in text, f"{name}: 输出含裸 NaN 字面量"
            assert "Infinity" not in text, f"{name}: 输出含裸 Infinity 字面量"

            # 严格回读：parse_constant 一旦被触发就抛异常
            parsed = json.loads(text, parse_constant=reject_constant)
            assert parsed == expected, f"{name}: 回读内容错误: {parsed!r}"

            # allow_nan=False 兜底验证：未清洗的 payload 必须无法序列化
            try:
                json.dumps(payload, allow_nan=False)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{name}: allow_nan=False 未拦截非法值")

        print(f"✅ {name}: _sanitize + write_json_strict 通过")

    print("\n全部通过：3 个模块均不会产出非法 JSON")


if __name__ == "__main__":
    main()
