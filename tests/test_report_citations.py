import unittest

from report_generation.citations import (
    collect_used_references,
    register_evidence_blocks,
    validate_body_citations,
)


class ReportCitationRegistryTests(unittest.TestCase):
    def test_registers_sources_in_order_and_merges_chunks_from_same_material(self):
        blocks = [
            {
                "library": "policy",
                "material_id": "m1",
                "vector_id": "v1",
                "title": "政策甲",
                "text": "片段一",
                "retrieved_at": "2026-09-21T14:30:00+08:00",
            },
            {
                "library": "policy",
                "material_id": "m1",
                "vector_id": "v2",
                "title": "政策甲",
                "text": "片段二",
            },
            {
                "library": "company_case",
                "material_id": "m2",
                "vector_id": "v3",
                "title": "案例乙",
                "text": "片段三",
            },
        ]

        mapped, references = register_evidence_blocks(blocks, [])

        self.assertEqual([row["citation_id"] for row in mapped], ["C1", "C1", "C2"])
        self.assertEqual(references[0]["vector_ids"], ["v1", "v2"])
        self.assertEqual(references[0]["evidence_excerpt"], "片段一")
        self.assertEqual(references[0]["retrieved_at"], "2026-09-21T14:30:00+08:00")
        self.assertEqual(references[1]["title"], "案例乙")

    def test_reuses_existing_ids_and_appends_after_highest_id(self):
        existing = [
            {"citation_id": "C4", "library": "policy", "material_id": "m1", "vector_ids": ["v1"]}
        ]
        blocks = [
            {"library": "policy", "material_id": "m1", "vector_id": "v2"},
            {"library": "speech", "material_id": "m2", "vector_id": "v3"},
        ]

        mapped, references = register_evidence_blocks(blocks, existing)

        self.assertEqual([row["citation_id"] for row in mapped], ["C4", "C5"])
        self.assertEqual(references[0]["vector_ids"], ["v1", "v2"])

    def test_falls_back_to_vector_id_when_material_id_is_missing(self):
        blocks = [
            {"library": "policy", "vector_id": "v1", "title": "片段甲"},
            {"library": "policy", "vector_id": "v1", "title": "片段甲"},
            {"library": "policy", "vector_id": "v2", "title": "片段乙"},
        ]

        mapped, references = register_evidence_blocks(blocks, [])

        self.assertEqual([row["citation_id"] for row in mapped], ["C1", "C1", "C2"])
        self.assertEqual([row["citation_id"] for row in references], ["C1", "C2"])

    def test_backfills_retrieved_at_when_reusing_legacy_reference(self):
        mapped, references = register_evidence_blocks(
            [{
                "library": "policy",
                "material_id": "m1",
                "vector_id": "v2",
                "retrieved_at": "2026-09-21T14:30:00+08:00",
            }],
            [{"citation_id": "C4", "library": "policy", "material_id": "m1", "vector_ids": ["v1"]}],
        )
        self.assertEqual(mapped[0]["citation_id"], "C4")
        self.assertEqual(references[0]["retrieved_at"], "2026-09-21T14:30:00+08:00")


class ReportCitationValidationTests(unittest.TestCase):
    def test_keeps_allowed_ids_in_first_occurrence_order_and_removes_unknown_marker(self):
        text, citation_ids, warnings = validate_body_citations(
            "政策已发布[C2]，随后落地[C1]，重复说明[C2]，错误引用[C9]。",
            [{"citation_id": "C1"}, {"citation_id": "C2"}],
        )
        self.assertEqual(text, "政策已发布[C2]，随后落地[C1]，重复说明[C2]，错误引用。")
        self.assertEqual(citation_ids, ["C2", "C1"])
        self.assertEqual(warnings[0]["invalid_citation_ids"], ["C9"])

    def test_collects_only_references_used_by_successful_sections(self):
        references = [{"citation_id": "C1"}, {"citation_id": "C2"}, {"citation_id": "C3"}]
        sections = [
            {"status": "success", "citation_ids": ["C2", "C1"]},
            {"status": "error", "citation_ids": ["C3"]},
        ]
        self.assertEqual(
            [row["citation_id"] for row in collect_used_references(sections, references)],
            ["C1", "C2"],
        )


if __name__ == "__main__":
    unittest.main()
