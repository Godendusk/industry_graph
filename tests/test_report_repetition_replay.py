import unittest

from report_generation.material_allocator import allocate_evidence_blocks


def _block(material_id, vector_id, rank, title):
    return {
        "library": "policy",
        "material_id": material_id,
        "vector_id": vector_id,
        "rank": rank,
        "title": title,
        "text": f"{title}片段",
    }


class ReportRepetitionReplayTest(unittest.TestCase):
    def test_replay_keeps_evidence_and_spreads_materials(self):
        sections = [
            {
                "outline_id": "S1.1",
                "parent_level1_id": "S1",
                "candidates": [
                    _block("m1", "v11", 1, "标准体系"),
                    _block("m2", "v12", 2, "产业报告"),
                ],
            },
            {
                "outline_id": "S2.1",
                "parent_level1_id": "S2",
                "candidates": [
                    _block("m1", "v21", 1, "标准体系"),
                    _block("m3", "v22", 2, "应用案例"),
                ],
            },
        ]

        allocated = allocate_evidence_blocks(sections, target_per_section=10)

        self.assertTrue(all(row["evidence_blocks"] for row in allocated))
        self.assertEqual(
            [row["material_id"] for row in allocated[1]["evidence_blocks"]],
            ["m3", "m1"],
        )
        for row in allocated:
            vectors = [block["vector_id"] for block in row["evidence_blocks"]]
            self.assertEqual(len(vectors), len(set(vectors)))

    def test_replay_reports_cross_level1_source_reuse_without_treating_it_as_error(self):
        sections = [
            {"outline_id": "S1.1", "parent_level1_id": "S1", "candidates": [_block("m1", "v1", 1, "权威政策")]},
            {"outline_id": "S2.1", "parent_level1_id": "S2", "candidates": [_block("m1", "v2", 1, "权威政策")]},
        ]

        allocated = allocate_evidence_blocks(sections, target_per_section=10)
        source_use = {
            block["material_id"]: set()
            for row in allocated
            for block in row["evidence_blocks"]
        }
        for row in allocated:
            for block in row["evidence_blocks"]:
                source_use[block["material_id"]].add(row["parent_level1_id"])

        self.assertEqual(source_use["m1"], {"S1", "S2"})
        self.assertEqual(allocated[1]["diagnostics"]["reused_material_ids"], ["policy:m1"])


if __name__ == "__main__":
    unittest.main()
