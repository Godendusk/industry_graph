"""Delivery status derives from completed work, independently of report length."""


def delivery_state(sections, review, summary_review=None, report_scope=None):
    reasons = []
    if not sections or any(not isinstance(s, dict) or s.get('status') != 'success'
                           or not str(s.get('body_text') or '').strip() for s in sections):
        reasons.append('正文未完整生成')
    if not review or review.get('status') in ('failed', 'not_started', None):
        reasons.append('正文审查执行未完成')
    elif review.get('status') != 'completed':
        prior_reason_count = len(reasons)
        if review.get('execution_status') in ('partial', 'failed'):
            reasons.append('部分审查调用或结果解析未完成，尚未完成全部核对执行')
        if review.get('failed_outline_ids'):
            reasons.append('部分正文修正未通过复核或未能采用')
        if (review.get('claim_verification') or {}).get('pending_outline_ids'):
            reasons.append('关键事实仍有待确认项')
        verification = review.get('verification') or {}
        if verification.get('status') == 'failed':
            reasons.append('修改结果复核执行未完成')
        elif verification.get('status') == 'partial':
            reasons.append('跨节重复仍有未解决项')
        if review.get('evidence_warning_count'):
            reasons.append('来源口径或跨节一致性仍有待核实项')
        if len(reasons) == prior_reason_count:
            reasons.append('正文审查仍有未完成或未解决项')
    if any((s.get('claim_verification') or {}).get('invalidated')
           or ((s.get('claim_verification') or {}).get('body_text') is not None
               and s['claim_verification']['body_text'] != s.get('body_text'))
           for s in sections if isinstance(s, dict)):
        reasons.append('正文已变化，原事实核对失效')
    if summary_review is None or summary_review.get('status') != 'completed':
        reasons.append('摘要一致性核对未完成')
    if report_scope and report_scope.get('status', 'completed') != 'completed':
        reasons.append('研究范围确认未完成')
    return {'delivery_status': 'incomplete' if reasons else 'completed',
            'deliverable_type': (report_scope or {}).get('deliverable_type', 'report'),
            'delivery_reasons': reasons}
