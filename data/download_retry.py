"""Pure helpers for retrying failed downloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass(frozen=True)
class RetryCommands:
    symbols_csv: str
    cli_symbol_command: str
    cli_failed_file_command: Optional[str]
    repl_symbol_command: str
    repl_failed_file_command: Optional[str]


def is_retryable_download_error(error_text: str) -> bool:
    if "无数据" in str(error_text):
        return False
    return True


def retry_symbols(
    failed: dict[str, str],
    is_retryable: Callable[[str], bool] = is_retryable_download_error,
) -> list[str]:
    return [sym for sym, err in sorted(failed.items()) if is_retryable(err)]


def build_retry_commands(
    symbols: list[str],
    start: str,
    end: str,
    failed_file: str | Path | None = None,
) -> RetryCommands:
    symbols_csv = ",".join(symbols)
    cli_symbol_command = (
        f'python main.py data download --symbol "{symbols_csv}" '
        f"--start {start} --end {end}"
    )
    repl_symbol_command = f'download --symbol "{symbols_csv}" --start {start} --end {end}'

    cli_failed_file_command = None
    repl_failed_file_command = None
    if failed_file is not None:
        cli_failed_file_command = (
            f'python main.py data download --failed-file "{failed_file}" '
            f"--start {start} --end {end}"
        )
        repl_failed_file_command = f'download --failed-file "{failed_file}" --start {start} --end {end}'

    return RetryCommands(
        symbols_csv=symbols_csv,
        cli_symbol_command=cli_symbol_command,
        cli_failed_file_command=cli_failed_file_command,
        repl_symbol_command=repl_symbol_command,
        repl_failed_file_command=repl_failed_file_command,
    )
