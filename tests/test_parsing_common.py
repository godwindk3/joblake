import unittest

from bs4 import BeautifulSoup

from joblake.parsing.common import (
    clean_text,
    html_fragment_items,
    html_fragment_to_text,
    tag_text,
)


class TextCleaningTests(unittest.TestCase):

    def test_removes_invisible_whitespace_characters(self) -> None:
        self.assertEqual(
            clean_text("  Senior\u00a0\u200b  Python\ufeff Engineer  "),
            "Senior Python Engineer",
        )

    def test_joins_inline_markup_without_sparse_newlines(self) -> None:
        tag = BeautifulSoup(
            "<p>Chăm sóc toàn diện với <strong>BH tai nạn 24/7</strong>"
            ", khám sức khỏe định kỳ.</p>",
            "html.parser",
        ).p

        self.assertEqual(
            tag_text(tag),
            "Chăm sóc toàn diện với BH tai nạn 24/7, khám sức khỏe định kỳ.",
        )

    def test_keeps_block_and_explicit_breaks(self) -> None:
        text = html_fragment_to_text(
            "<p>Build <span>reliable</span> APIs.</p>"
            "<ul><li>Health <strong>insurance</strong></li>"
            "<li>Remote<br>work</li></ul>"
        )

        self.assertEqual(
            text,
            "Build reliable APIs.\nHealth insurance\nRemote\nwork",
        )

    def test_extracts_compact_list_items(self) -> None:
        self.assertEqual(
            html_fragment_items(
                "<ul><li>Health <strong>insurance</strong></li>"
                "<li>Remote\u00a0work</li></ul>"
            ),
            ("Health insurance", "Remote work"),
        )


if __name__ == "__main__":
    unittest.main()
