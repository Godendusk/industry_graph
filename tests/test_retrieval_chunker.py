import hashlib
import unittest

from retrieval_core.chunker import ChunkingConfig, build_report_chunks
from report_generation.external_rag.text_utils import (
    html_to_paragraphs,
    html_to_structured_blocks,
    normalize_text,
    split_plain_paragraphs,
)


class FakeTokenizer:
    """Count one token per character plus deterministic special tokens."""

    def encode(self, text, add_special_tokens=True):
        extra = 2 if add_special_tokens else 0
        return list(range(len(text) + extra))


def make_chunks(blocks, **overrides):
    arguments = {
        "blocks": blocks,
        "library": "company_case",
        "material_id": "m1",
        "title": "央企案例",
        "metadata": {"classification_name": "企业案例", "source": "api"},
        "tokenizer": FakeTokenizer(),
        "config": ChunkingConfig(
            min_chars=20,
            target_chars=40,
            soft_max_chars=60,
            hard_max_chars=80,
            overlap_chars=12,
            max_tokens=120,
        ),
    }
    arguments.update(overrides)
    return build_report_chunks(**arguments)


class StructuredHtmlTests(unittest.TestCase):
    def test_extracts_headings_text_and_table_rows_without_cell_duplicates(self):
        raw_html = """
        <script>ignored()</script><style>.ignored {}</style><noscript>ignored</noscript>
        <h2>智算布局</h2>
        <p>表格前的说明。</p>
        <table>
          <tr><th>企业</th><th>规模</th></tr>
          <tr><td><p>中国移动</p></td><td>10 EFLOPS</td></tr>
        </table>
        <blockquote>表格后的结论。</blockquote>
        """

        blocks = html_to_structured_blocks(raw_html)

        self.assertEqual(
            blocks,
            [
                {"kind": "heading", "text": "智算布局", "level": 2},
                {"kind": "paragraph", "text": "表格前的说明。"},
                {"kind": "table", "text": "企业：中国移动；规模：10 EFLOPS。"},
                {"kind": "blockquote", "text": "表格后的结论。"},
            ],
        )
        self.assertEqual(sum("中国移动" in block["text"] for block in blocks), 1)
        self.assertNotIn("ignored", " ".join(block["text"] for block in blocks))

    def test_nested_list_text_is_not_duplicated(self):
        blocks = html_to_structured_blocks(
            "<ul><li>一级条目<ul><li>二级条目</li></ul></li></ul>"
        )

        self.assertEqual(
            blocks,
            [
                {"kind": "list_item", "text": "一级条目"},
                {"kind": "list_item", "text": "二级条目"},
            ],
        )

    def test_blockquote_with_nested_paragraph_keeps_content_once(self):
        blocks = html_to_structured_blocks(
            "<blockquote><p>这是引用中的正文。</p></blockquote>"
        )

        self.assertEqual(
            blocks,
            [{"kind": "blockquote", "text": "这是引用中的正文。"}],
        )

    def test_existing_text_helpers_keep_their_public_behavior(self):
        self.assertEqual(normalize_text(" A\u00a0 B \n\n\n C "), "A B \n\n C")
        self.assertEqual(
            split_plain_paragraphs("short\n\nlong enough", min_len=8),
            ["long enough"],
        )
        self.assertEqual(
            html_to_paragraphs("<h2>Heading text</h2><p>Body text</p>", min_len=8),
            ["Heading text", "Body text"],
        )


class ChunkingConfigTests(unittest.TestCase):
    def test_defaults_match_the_v2_design(self):
        config = ChunkingConfig()

        self.assertEqual(config.min_chars, 80)
        self.assertEqual(config.target_chars, 320)
        self.assertEqual(config.soft_max_chars, 400)
        self.assertEqual(config.hard_max_chars, 450)
        self.assertEqual(config.overlap_chars, 60)
        self.assertEqual(config.max_tokens, 480)
        with self.assertRaises(AttributeError):
            config.target_chars = 300

    def test_rejects_nonpositive_and_incoherent_limits(self):
        invalid_values = (
            {"min_chars": 0},
            {"min_chars": 30, "target_chars": 20},
            {"target_chars": 50, "soft_max_chars": 40},
            {"soft_max_chars": 70, "hard_max_chars": 60},
            {"overlap_chars": -1},
            {"overlap_chars": 81, "hard_max_chars": 80},
            {"max_tokens": 0},
        )
        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, "ChunkingConfig"):
                    ChunkingConfig(**values)


class ReportChunkingTests(unittest.TestCase):
    def test_rejects_lossy_embedding_prefix_when_context_exhausts_token_budget(self):
        with self.assertRaisesRegex(ValueError, "embedding prefix.*token budget"):
            build_report_chunks(
                blocks=[{"kind": "paragraph", "text": "正文"}],
                library="company_case",
                material_id="m1",
                title="很长的资料标题用于验证上下文绝不能被静默截断",
                metadata={"classification_name": "很长的分类名称用于验证上下文绝不能被静默截断"},
                tokenizer=FakeTokenizer(),
                config=ChunkingConfig(
                    min_chars=1,
                    target_chars=2,
                    soft_max_chars=3,
                    hard_max_chars=4,
                    overlap_chars=0,
                    max_tokens=12,
                ),
            )

    def test_short_blocks_merge_inside_same_heading(self):
        chunks = make_chunks(
            [
                {"kind": "heading", "text": "建设进展", "level": 2},
                {"kind": "paragraph", "text": "中国移动建设智算中心。"},
                {"kind": "paragraph", "text": "中国电信扩大智能算力供给。"},
            ]
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(
            chunks[0].text,
            "中国移动建设智算中心。\n中国电信扩大智能算力供给。",
        )
        self.assertIn("企业案例", chunks[0].embedding_text)
        self.assertIn("央企案例", chunks[0].embedding_text)
        self.assertIn("建设进展", chunks[0].embedding_text)

    def test_changed_heading_flushes_short_blocks_and_tracks_heading_levels(self):
        chunks = make_chunks(
            [
                {"kind": "heading", "text": "上篇", "level": 1},
                {"kind": "heading", "text": "建设", "level": 2},
                {"kind": "paragraph", "text": "第一部分很短。"},
                {"kind": "heading", "text": "应用", "level": 2},
                {"kind": "paragraph", "text": "第二部分也短。"},
            ]
        )

        self.assertEqual([chunk.text for chunk in chunks], ["第一部分很短。", "第二部分也短。"])
        self.assertEqual(chunks[0].metadata["section_path"], ("上篇", "建设"))
        self.assertEqual(chunks[1].metadata["section_path"], ("上篇", "应用"))

    def test_long_paragraph_splits_with_bounded_sentence_overlap_and_token_cap(self):
        sentence_1 = "第一句说明建设背景。"
        sentence_2 = "第二句说明项目进展。"
        sentence_3 = "第三句说明算力规模。"
        sentence_4 = "第四句说明应用效果。"
        text = sentence_1 + sentence_2 + sentence_3 + sentence_4
        config = ChunkingConfig(
            min_chars=8,
            target_chars=15,
            soft_max_chars=24,
            hard_max_chars=28,
            overlap_chars=12,
            max_tokens=55,
        )

        chunks = make_chunks(
            [{"kind": "paragraph", "text": text}],
            library="research_report",
            material_id="m2",
            title="研究报告",
            metadata={"classification_name": "研究报告"},
            config=config,
        )

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk.token_count <= config.max_tokens for chunk in chunks))
        self.assertTrue(all(len(chunk.text) <= config.hard_max_chars for chunk in chunks))
        overlaps = []
        for previous, current in zip(chunks, chunks[1:]):
            overlap = next(
                (
                    sentence
                    for sentence in (sentence_1, sentence_2, sentence_3, sentence_4)
                    if previous.text.endswith(sentence) and current.text.startswith(sentence)
                ),
                "",
            )
            overlaps.append(overlap)
        self.assertTrue(any(overlaps))
        self.assertTrue(all(len(overlap) <= config.overlap_chars for overlap in overlaps))

    def test_natural_blocks_do_not_receive_mechanical_overlap(self):
        first = "甲" * 22 + "。"
        second = "乙" * 22 + "。"
        chunks = make_chunks(
            [
                {"kind": "paragraph", "text": first},
                {"kind": "paragraph", "text": second},
            ],
            config=ChunkingConfig(
                min_chars=10,
                target_chars=20,
                soft_max_chars=25,
                hard_max_chars=30,
                overlap_chars=8,
                max_tokens=80,
            ),
        )

        self.assertEqual([chunk.text for chunk in chunks], [first, second])
        self.assertFalse(chunks[1].text.startswith(first[-8:]))

    def test_zero_overlap_preserves_spaces_across_hard_and_sentence_splits(self):
        config = ChunkingConfig(
            min_chars=1,
            target_chars=5,
            soft_max_chars=5,
            hard_max_chars=6,
            overlap_chars=0,
            max_tokens=40,
        )
        for source in ("one two three", "One. Two. Three."):
            with self.subTest(source=source):
                chunks = make_chunks(
                    [{"kind": "paragraph", "text": source}], config=config
                )
                self.assertGreater(len(chunks), 1)
                self.assertEqual("".join(chunk.text for chunk in chunks), normalize_text(source))

    def test_tiny_hard_split_budget_makes_bounded_nonempty_progress(self):
        config = ChunkingConfig(
            min_chars=1,
            target_chars=1,
            soft_max_chars=1,
            hard_max_chars=1,
            overlap_chars=0,
            max_tokens=7,
        )
        chunks = build_report_chunks(
            blocks=[{"kind": "paragraph", "text": "abcdef"}],
            library="l",
            material_id="m",
            title="T",
            metadata={"classification_name": "C"},
            tokenizer=FakeTokenizer(),
            config=config,
        )

        self.assertEqual("".join(chunk.text for chunk in chunks), "abcdef")
        self.assertEqual(len(chunks), len("abcdef"))
        self.assertTrue(all(chunk.text and chunk.token_count <= config.max_tokens for chunk in chunks))

    def test_tables_and_sections_are_preserved_in_metadata(self):
        blocks = html_to_structured_blocks(
            "<h1>总体</h1><h3>智算布局</h3>"
            "<table><tr><th>企业</th><th>规模</th></tr>"
            "<tr><td>中国移动</td><td>10 EFLOPS</td></tr></table>"
        )

        chunks = make_chunks(blocks)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "企业：中国移动；规模：10 EFLOPS。")
        self.assertEqual(chunks[0].metadata["content_type"], "table")
        self.assertEqual(chunks[0].metadata["section_path"], ("总体", "智算布局"))
        self.assertEqual(chunks[0].metadata["source"], "api")

    def test_ids_are_stable_and_neighbor_links_are_correct(self):
        blocks = [
            {"kind": "heading", "text": "进展", "level": 2},
            {"kind": "paragraph", "text": "甲" * 22 + "。"},
            {"kind": "paragraph", "text": "乙" * 22 + "。"},
        ]
        config = ChunkingConfig(
            min_chars=10,
            target_chars=20,
            soft_max_chars=25,
            hard_max_chars=30,
            overlap_chars=8,
            max_tokens=80,
        )

        first_run = make_chunks(blocks, config=config)
        second_run = make_chunks(blocks, config=config)

        self.assertEqual([chunk.chunk_id for chunk in first_run], [chunk.chunk_id for chunk in second_run])
        for index, chunk in enumerate(first_run):
            digest = hashlib.sha256(normalize_text(chunk.text).encode("utf-8")).hexdigest()
            self.assertEqual(
                chunk.chunk_id,
                f"external:v2:company_case:m1:c:{index}:{digest[:8]}",
            )
            self.assertEqual(chunk.chunk_index, index)
            self.assertEqual(
                chunk.previous_chunk_id,
                first_run[index - 1].chunk_id if index else None,
            )
            self.assertEqual(
                chunk.next_chunk_id,
                first_run[index + 1].chunk_id if index + 1 < len(first_run) else None,
            )

    def test_injected_search_tokenizer_and_fallback_are_deterministic(self):
        blocks = [{"kind": "paragraph", "text": "中国移动AI平台"}]

        injected = make_chunks(
            blocks,
            search_tokenizer=lambda value: ["CUSTOM", str(len(value))],
        )
        fallback_1 = make_chunks(blocks)
        fallback_2 = make_chunks(blocks)

        self.assertRegex(injected[0].search_text, r"^CUSTOM \d+$")
        self.assertEqual(fallback_1[0].search_text, fallback_2[0].search_text)
        self.assertIn("中 国 移 动", fallback_1[0].search_text)

    def test_invalid_inputs_and_impossible_token_budget_raise_clear_errors(self):
        base = {
            "blocks": [{"kind": "paragraph", "text": "有效正文"}],
            "library": "company_case",
            "material_id": "m1",
            "title": "标题",
            "metadata": {},
            "tokenizer": FakeTokenizer(),
            "config": ChunkingConfig(
                min_chars=1,
                target_chars=2,
                soft_max_chars=3,
                hard_max_chars=4,
                overlap_chars=1,
                max_tokens=20,
            ),
        }
        for field in ("blocks", "library", "material_id", "title"):
            arguments = dict(base)
            arguments[field] = [] if field == "blocks" else ""
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, field):
                    build_report_chunks(**arguments)

        impossible = dict(base)
        impossible["config"] = ChunkingConfig(
            min_chars=1,
            target_chars=2,
            soft_max_chars=3,
            hard_max_chars=4,
            overlap_chars=1,
            max_tokens=3,
        )
        with self.assertRaisesRegex(ValueError, "token budget"):
            build_report_chunks(**impossible)


if __name__ == "__main__":
    unittest.main()
