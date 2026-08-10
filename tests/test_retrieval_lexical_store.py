import gc
import sqlite3
import tempfile
import unittest
import warnings
from dataclasses import replace
from pathlib import Path

from retrieval_core.lexical_store import LexicalStore
from retrieval_core.schemas import ChunkRecord


def chunk(
    chunk_id,
    document_id,
    index,
    text,
    *,
    library="policy",
    title="测试资料",
    entities=(),
    section_path=("建设进展",),
):
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_index=index,
        text=text,
        embedding_text="embedding " + text,
        search_text=text,
        token_count=len(text),
        content_hash="hash-" + chunk_id,
        metadata={
            "library": library,
            "material_id": document_id,
            "title": title,
            "entities": entities,
            "section_path": section_path,
            "content_type": "text",
            "nested": {"labels": ("甲", "乙")},
        },
    )


class LexicalStoreTests(unittest.TestCase):
    def make_store(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return LexicalStore(Path(directory.name) / "nested" / "lexical.sqlite3")

    def test_initializes_persistent_fts_schema(self):
        store = self.make_store()

        self.assertTrue(store.path.exists())
        with sqlite3.connect(store.path) as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
            fts_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'chunks_fts'"
            ).fetchone()[0]
            chunk_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(chunks)")
            }

        self.assertTrue({"documents", "chunks", "chunks_fts", "index_metadata"} <= names)
        self.assertIn("fts5", fts_sql.lower())
        self.assertTrue(
            {"title_tokens", "entity_tokens", "section_tokens", "body_tokens"}
            <= chunk_columns
        )

    def test_searches_exact_chinese_term_and_reopens(self):
        store = self.make_store()
        store.replace_document("d1", [chunk("c1", "d1", 0, "中国移动 建设 智算中心")])

        results = store.search("中国移动", limit=3)
        reopened = LexicalStore(store.path).search("中国移动", limit=3)

        self.assertEqual([result.chunk_id for result in results], ["c1"])
        self.assertEqual([result.chunk_id for result in reopened], ["c1"])
        self.assertEqual(results[0].bm25_rank, 1)
        self.assertIsInstance(results[0].bm25_score, float)

    def test_title_and_entity_matches_outweigh_body_match(self):
        store = self.make_store()
        store.replace_document(
            "d1",
            [
                chunk("body", "d1", 0, "新能源"),
                chunk("title", "d1", 1, "普通正文", title="新能源"),
                chunk("entity", "d1", 2, "普通正文", entities=("新能源",)),
            ],
        )

        results = store.search("新能源", limit=3)

        self.assertEqual([result.chunk_id for result in results], ["title", "entity", "body"])

    def test_filters_by_library_and_parameterizes_values(self):
        store = self.make_store()
        store.replace_document("d1", [chunk("policy", "d1", 0, "算力", library="policy")])
        store.replace_document(
            "d2", [chunk("expert", "d2", 0, "算力", library="expert_view")]
        )

        self.assertEqual(
            [row.chunk_id for row in store.search("算力", 10, libraries={"policy"})],
            ["policy"],
        )
        self.assertEqual(store.search("算力", 10, libraries=set()), [])
        self.assertEqual(store.search("算力", 10, libraries={"' OR 1=1 --"}), [])

    def test_fts_syntax_and_punctuation_are_literal_terms(self):
        store = self.make_store()
        store.replace_document("d1", [chunk("c1", "d1", 0, "安全 算力")])

        self.assertEqual(store.search('" OR * NEAR', 10), [])
        self.assertEqual(store.search("' OR 1=1 --", 10), [])
        self.assertEqual([row.chunk_id for row in store.search("安全", 10)], ["c1"])

    def test_empty_query_returns_no_results_and_invalid_limit_is_clear(self):
        store = self.make_store()
        store.replace_document("d1", [chunk("c1", "d1", 0, "安全")])

        self.assertEqual(store.search(" \t\n ", 1), [])
        for invalid in (0, -1, 1.5, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "limit"):
                    store.search("安全", invalid)

    def test_ties_are_deterministic_by_chunk_id(self):
        store = self.make_store()
        store.replace_document(
            "d1", [chunk("z-last", "d1", 0, "相同词"), chunk("a-first", "d1", 1, "相同词")]
        )

        self.assertEqual(
            [row.chunk_id for row in store.search("相同词", 10)], ["a-first", "z-last"]
        )

    def test_neighbors_include_hit_and_do_not_cross_document_boundary(self):
        store = self.make_store()
        store.replace_document(
            "d1",
            [
                chunk("c0", "d1", 0, "零"),
                replace(chunk("c1", "d1", 1, "一"), previous_chunk_id="c0", next_chunk_id="c2"),
                chunk("c2", "d1", 2, "二"),
            ],
        )
        store.replace_document("d2", [chunk("other", "d2", 0, "另一个")])

        rows = store.neighbors("c1", before=1, after=2)

        self.assertEqual([row.chunk_id for row in rows], ["c0", "c1", "c2"])
        self.assertEqual(store.neighbors("missing"), [])
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            store.neighbors("c1", before=-1)

    def test_replacement_removes_stale_rows_and_is_atomic_on_constraint_failure(self):
        store = self.make_store()
        old = chunk("old", "d1", 0, "旧词")
        store.replace_document("d1", [old])
        store.replace_document("d2", [chunk("owned", "d2", 0, "另词")])

        with self.assertRaises(sqlite3.IntegrityError):
            store.replace_document("d1", [chunk("owned", "d1", 0, "新词")])

        self.assertEqual([row.chunk_id for row in store.search("旧词", 10)], ["old"])
        with sqlite3.connect(store.path) as connection:
            self.assertEqual(
                {
                    row[0]
                    for row in connection.execute("SELECT chunk_id FROM chunks_fts")
                },
                {"old", "owned"},
            )
        store.replace_document("d1", [chunk("new", "d1", 0, "新词")])
        self.assertEqual(store.search("旧词", 10), [])
        self.assertEqual([row.chunk_id for row in store.search("新词", 10)], ["new"])
        self.assertEqual(store.ids_for_document("d1"), {"new"})
        with sqlite3.connect(store.path) as connection:
            self.assertEqual(
                {
                    row[0]
                    for row in connection.execute("SELECT chunk_id FROM chunks_fts")
                },
                {"new", "owned"},
            )

    def test_delete_metadata_ids_count_and_metadata_roundtrip(self):
        store = self.make_store()
        row = chunk("c1", "d1", 0, "内容")
        store.replace_document("d1", [row])
        store.set_index_metadata("version", "v1")

        result = store.search("内容", 10)[0]
        self.assertEqual(result.metadata["section_path"], ("建设进展",))
        self.assertEqual(result.metadata["nested"], {"labels": ("甲", "乙")})
        self.assertEqual(store.get_index_metadata("version"), "v1")
        store.set_index_metadata("version", None)
        self.assertIsNone(store.get_index_metadata("version"))
        self.assertEqual(store.all_chunk_ids(), {"c1"})
        self.assertEqual(store.count(), 1)
        store.delete_document("does-not-exist")
        store.delete_document("d1")
        self.assertEqual(store.count(), 0)
        self.assertEqual(store.all_chunk_ids(), set())
        with sqlite3.connect(store.path) as connection:
            self.assertEqual(
                list(connection.execute("SELECT chunk_id FROM chunks_fts")), []
            )

    def test_validates_replacement_and_custom_query_tokenizer(self):
        store = self.make_store()
        row = chunk("c1", "d1", 0, "中国移动")
        with self.assertRaisesRegex(ValueError, "nonempty list"):
            store.replace_document("d1", [])
        with self.assertRaisesRegex(ValueError, "document_id"):
            store.replace_document("wrong", [row])

        tokenized = LexicalStore(store.path, query_tokenizer=lambda query: ["中国移动"])
        tokenized.replace_document("d1", [row])
        self.assertEqual([candidate.chunk_id for candidate in tokenized.search("任意问题", 2)], ["c1"])

    def test_closes_each_operation_connection(self):
        store = self.make_store()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            store.count()
            gc.collect()

        self.assertEqual([warning for warning in caught if issubclass(warning.category, ResourceWarning)], [])


if __name__ == "__main__":
    unittest.main()
