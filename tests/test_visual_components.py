import tempfile
import unittest
from pathlib import Path

import numpy as np

from visual.components import (
    echarts_script_tag,
    html_document,
    inline_script,
    json_script_data,
    safe_json,
    script_src,
    to_compact_json,
)


class VisualComponentsTest(unittest.TestCase):
    def test_script_src_escapes_url(self):
        self.assertEqual(
            script_src('https://example.test/a?x="1"'),
            '<script src="https://example.test/a?x=&quot;1&quot;"></script>',
        )

    def test_echarts_script_prefers_existing_local_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "echarts.min.js"
            path.write_text("window.echarts={};", encoding="utf-8")

            self.assertEqual(echarts_script_tag("https://cdn.test/e.js", path), "<script>window.echarts={};</script>")

    def test_echarts_script_falls_back_to_cdn(self):
        self.assertEqual(
            echarts_script_tag("https://cdn.test/e.js", Path("/missing/echarts.min.js")),
            '<script src="https://cdn.test/e.js"></script>',
        )

    def test_html_document_escapes_title_and_wraps_body(self):
        document = html_document(
            title='A < B',
            body="<main>body</main>",
            styles="body{}",
            head_extra=script_src("https://cdn.test/e.js"),
            scripts=inline_script("window.ok=true;"),
        )

        self.assertIn("<title>A &lt; B</title>", document)
        self.assertIn("<style>body{}</style>", document)
        self.assertIn("<main>body</main>", document)
        self.assertIn("<script>window.ok=true;</script>", document)

    def test_safe_json_escapes_closing_script(self):
        self.assertEqual(safe_json({"x": "</script>"}), '{"x": "<\\/script>"}')

    def test_safe_json_can_reject_nan(self):
        with self.assertRaises(ValueError):
            safe_json({"x": float("nan")}, allow_nan=False)

    def test_json_script_data_wraps_safe_json(self):
        tag = json_script_data({"x": "</script>"}, 'data"id')

        self.assertEqual(
            tag,
            '<script type="application/json" id="data&quot;id">{"x": "<\\/script>"}</script>',
        )

    def test_to_compact_json_serializes_numpy_values(self):
        self.assertEqual(
            to_compact_json(
                {
                    "int": np.int64(3),
                    "float": np.float64(1.23456789),
                    "nan": np.float64(np.nan),
                    "arr": np.array([1, 2]),
                    "label": "日K",
                }
            ),
            '{"int":3,"float":1.234568,"nan":null,"arr":[1,2],"label":"日K"}',
        )

    def test_to_compact_json_rejects_python_nan(self):
        with self.assertRaises(ValueError):
            to_compact_json({"x": float("nan")})


if __name__ == "__main__":
    unittest.main()
