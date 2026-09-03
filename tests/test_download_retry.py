import unittest
from pathlib import Path

from data.download_retry import build_retry_commands, is_retryable_download_error, retry_symbols


class DownloadRetryTest(unittest.TestCase):
    def test_is_retryable_download_error(self):
        self.assertFalse(is_retryable_download_error("无数据: 000001.SZ"))
        self.assertTrue(is_retryable_download_error("network timeout"))
        self.assertTrue(is_retryable_download_error("频率超限"))

    def test_retry_symbols_filters_and_sorts(self):
        failed = {
            "600519.SH": "timeout",
            "000001.SZ": "无数据",
            "300750.SZ": "频率超限",
        }

        self.assertEqual(retry_symbols(failed), ["300750.SZ", "600519.SH"])

    def test_build_retry_commands_keeps_existing_format(self):
        commands = build_retry_commands(
            ["000001.SZ", "600519.SH"],
            "20260101",
            "20260131",
            Path("output/download_failures/final.csv"),
        )

        self.assertEqual(commands.symbols_csv, "000001.SZ,600519.SH")
        self.assertEqual(
            commands.cli_symbol_command,
            'python main.py data download --symbol "000001.SZ,600519.SH" --start 20260101 --end 20260131',
        )
        self.assertEqual(
            commands.cli_failed_file_command,
            'python main.py data download --failed-file "output/download_failures/final.csv" --start 20260101 --end 20260131',
        )
        self.assertEqual(
            commands.repl_symbol_command,
            'download --symbol "000001.SZ,600519.SH" --start 20260101 --end 20260131',
        )
        self.assertEqual(
            commands.repl_failed_file_command,
            'download --failed-file "output/download_failures/final.csv" --start 20260101 --end 20260131',
        )

    def test_build_retry_commands_allows_missing_failure_file(self):
        commands = build_retry_commands(["000001.SZ"], "20260101", "20260131")

        self.assertIsNone(commands.cli_failed_file_command)
        self.assertIsNone(commands.repl_failed_file_command)


if __name__ == "__main__":
    unittest.main()
