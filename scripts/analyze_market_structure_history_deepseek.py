#!/usr/bin/env python3
"""Prepare, call once, or recover the DeepSeek V4 Pro 400-day audit."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.index_market_history_llm import (  # noqa: E402
    prepare_deepseek_history_audit,
    recover_deepseek_history_audit,
    write_deepseek_history_audit,
)
from cli.common import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="准备或执行唯一一次 DeepSeek V4 Pro 400日市场结构审计")
    parser.add_argument("batch_dir", help="历史回填批次目录")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true", help="只做严格本地门禁并冻结提示词，绝不调用API")
    mode.add_argument("--recover-only", action="store_true", help="只从既有raw响应恢复报告，绝不调用API")
    args = parser.parse_args()
    batch_dir = Path(args.batch_dir)
    if args.prepare_only:
        paths, metadata = prepare_deepseek_history_audit(batch_dir)
        print("本地证据门禁: 通过（未调用API）")
        print(f"冻结提示词: {paths.prompt}")
        print(f"提示词SHA256: {metadata['prompt_sha256']}")
        return 0
    if args.recover_only:
        paths, metadata = recover_deepseek_history_audit(batch_dir)
    else:
        paths, metadata = write_deepseek_history_audit(batch_dir, load_config())
    print(f"DeepSeek 模型: {metadata.get('model_returned') or metadata.get('model_requested')}")
    print(f"结束原因: {metadata.get('finish_reason')}")
    print(f"本次是否调用API: {metadata.get('api_called_this_run')}")
    print(f"是否从raw恢复: {metadata.get('recovered_from_raw')}")
    print(f"审计报告: {paths.response}")
    print(f"HTML 报告: {paths.html}")
    print(f"raw响应: {paths.raw_response}")
    print(f"调用元数据: {paths.metadata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
