import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_config import CONFIG_ENV_VAR, PROJECT_ROOT, load_project_config, resolve_config_path


class ProjectConfigTest(unittest.TestCase):
    def test_default_path_is_project_config(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_config_path(), PROJECT_ROOT / "config.yaml")

    def test_environment_can_select_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.yaml"
            path.write_text("defaults:\n  start_date: '20200101'\n", encoding="utf-8")
            with patch.dict(os.environ, {CONFIG_ENV_VAR: str(path)}, clear=True):
                self.assertEqual(load_project_config()["defaults"]["start_date"], "20200101")

    def test_empty_yaml_is_an_empty_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.yaml"
            path.write_text("", encoding="utf-8")
            self.assertEqual(load_project_config(path), {})

    def test_non_mapping_yaml_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.yaml"
            path.write_text("- one\n- two\n", encoding="utf-8")
            with self.assertRaisesRegex(TypeError, "顶层必须是映射"):
                load_project_config(path)


if __name__ == "__main__":
    unittest.main()
