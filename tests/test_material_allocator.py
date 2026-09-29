import unittest

from report_generation.material_allocator import allocate_evidence_blocks


def block(material_id, vector_id, rank, title="资料"):
    return {
        "library": "policy",
        "material_id": material_id,
        "vector_id": vector_id,
        "rank": rank,
        "title": title,
        "text": f"{title}-{vector_id}",
    }


class MaterialAllocatorTest(unittest.TestCase):
    def test_prefers_unassigned_materials_but_keeps_best_candidate(self):
        sections = [
            {"outline_id": "S1.1", "candidates": [
                block("m1", "v11", 1, "甲"), block("m2", "v12", 2, "乙")
            ]},
            {"outline_id": "S2.1", "candidates": [
                block("m1", "v21", 1, "甲"), block("m3", "v22", 2, "丙")
            ]},
        ]

        allocated = allocate_evidence_blocks(sections, target_per_section=2)

        self.assertEqual(
            [row["material_id"] for row in allocated[0]["evidence_blocks"]],
            ["m1", "m2"],
        )
        self.assertEqual(
            [row["material_id"] for row in allocated[1]["evidence_blocks"]],
            ["m3", "m1"],
        )

    def test_deduplicates_same_material_within_section_and_allows_second_chunk_only_after_distinct_sources(self):
        sections = [{"outline_id": "S1.1", "candidates": [
            block("m1", "v1", 1), block("m1", "v2", 2), block("m2", "v3", 3)
        ]}]

        allocated = allocate_evidence_blocks(sections, target_per_section=3)

        self.assertEqual([row["vector_id"] for row in allocated[0]["evidence_blocks"]], ["v1", "v3", "v2"])

    def test_candidate_count_reports_all_valid_input_candidates(self):
        sections = [{"outline_id": "S1.1", "candidates": [
            block("m1", "v1", 1), block("m2", "v2", 2), block("m3", "v3", 3)
        ]}]

        allocated = allocate_evidence_blocks(sections, target_per_section=1)

        self.assertEqual(len(allocated[0]["evidence_blocks"]), 1)
        self.assertEqual(allocated[0]["diagnostics"]["candidate_count"], 3)

    def test_returns_available_candidates_without_filling_with_duplicates(self):
        sections = [{"outline_id": "S1.1", "candidates": [block("m1", "v1", 1)]}]

        allocated = allocate_evidence_blocks(sections, target_per_section=3)

        self.assertEqual(len(allocated[0]["evidence_blocks"]), 1)
        self.assertEqual(allocated[0]["diagnostics"]["distinct_material_count"], 1)


if __name__ == "__main__":
    unittest.main()
