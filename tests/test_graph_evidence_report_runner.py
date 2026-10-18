"""Offline checks for the actual stage-four pipeline and saved-report export."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import run_graph_evidence_acceptance as runner


class ReportRunnerTests(unittest.TestCase):
    def test_report_uses_outline_agent_and_fixed_stage4_request(self):
        outline = [{'level1_id': f'S{i}', 'level1_title': str(i), 'subsections': [
            {'outline_id': f'S{i}.{j}', 'title': str(j)} for j in (1, 2)]} for i in (1, 2, 3)]
        tasks = {'status': 'success', 'writing_tasks': [], 'references': [], 'final_outline': outline}
        bodies = {'status': 'success', 'body_sections': [], 'references': []}
        summary = {'status': 'success', 'abstract_text': '摘要'}
        with tempfile.TemporaryDirectory() as directory, \
             patch('report_generation.outline_agent.generate_report_outline', return_value={'status': 'success', 'outline': outline}) as generate_outline, \
             patch('report_generation.coordinator_agent.generate_writing_tasks', return_value=tasks) as coordinator, \
             patch('report_generation.body_agent.generate_report_bodies', return_value=bodies), \
             patch('report_generation.summary_agent.generate_report_summary', return_value=summary), \
             patch('report_generation.word_export_agent.export_report_docx', return_value={'status': 'success', 'docx_path': str(Path(directory)/'report.docx') } ):
            root = Path(directory)
            runner.report(root)
            generate_outline.assert_called_once()
            self.assertEqual(generate_outline.call_args.args[0], '具身智能产业发展报告')
            self.assertTrue(generate_outline.call_args.kwargs['industry_confirmed'])
            self.assertEqual(coordinator.call_args.args[2], outline)
            self.assertEqual(coordinator.call_args.kwargs['industry'], 'embodied')
            self.assertEqual(json.loads((root/'report_outline.json').read_text())['outline'], outline)
            self.assertEqual(json.loads((root/'report_request.json').read_text())['title'], '具身智能产业发展报告')

    def test_outline_failure_saves_checkpoint_and_stops(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('report_generation.outline_agent.generate_report_outline', return_value={'status': 'error', 'message': 'model unavailable'}), \
             patch('report_generation.coordinator_agent.generate_writing_tasks') as coordinator:
            with self.assertRaises(RuntimeError):
                runner.report(Path(directory))
            coordinator.assert_not_called()
            self.assertEqual(json.loads((Path(directory)/'report_outline.json').read_text())['status'], 'error')

    def test_export_saved_report_does_not_regenerate_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in {
                'report_request.json': {'title': '具身智能产业发展报告'},
                'report_tasks.json': {'final_outline': [], 'references': []},
                'report_bodies.json': {'status': 'success', 'body_sections': [], 'references': []},
                'report_summary.json': {'status': 'success', 'abstract_text': '人工修订后的摘要'},
            }.items():
                (root/name).write_text(json.dumps(value))
            with patch('report_generation.outline_agent.generate_report_outline') as model, \
                 patch('report_generation.word_export_agent.export_report_docx', return_value={'status': 'success', 'docx_path': str(root/'report.docx')}) as exporter:
                runner.export_saved_report(root)
                model.assert_not_called()
                self.assertEqual(exporter.call_args.args[1], '人工修订后的摘要')
                self.assertTrue((root/'report_export.json').exists())
