"""Build inspectable entity-mention links from existing report chunks.

Only literal entity names are bound. This tool never infers relationship
support from co-occurrence or from model-generated category reasons.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from report_generation.industry_config import get_industry_config
from report_generation.external_rag.graph_evidence_retrieval import index_path, _news_record, _news_segment

ALLOWED_TOPICS = (
    'motor', 'controller_driver', 'force_tactile_sensor',
    'battery', 'humanoid_robot', 'application_case',
)

_TOPIC_TERMS = {
    'motor': ('电机', '伺服', '力矩', '空心杯'),
    'controller_driver': ('控制器', '驱动器', '控制系统', '编码器'),
    'force_tactile_sensor': ('触觉', '力觉', '力矩传感器', '六维力', '传感器'),
    'battery': ('动力电池', '电池', '电芯'),
    'humanoid_robot': ('人形机器人', '人形', '具身智能'),
    'application_case': ('应用', '巡检', '场景', '服务', '工业'),
}


def classify_node_topics(node, graph):
    """Classify a graph node from its own name and attached segment names.

    This is a routing hint for candidate review only. It never changes the
    evidence kind: a literal mention remains an entity mention.
    """
    node_id = node.get('id')
    names = [str((node.get('properties') or {}).get('name') or '')]
    for rel in graph.get('relationships', []):
        if rel.get('source') != node_id:
            continue
        target = next((item for item in graph.get('nodes', []) if item.get('id') == rel.get('target')), None)
        if target:
            names.append(str((target.get('properties') or {}).get('name') or ''))
    text = ' '.join(names)
    return [topic for topic in ALLOWED_TOPICS
            if any(term in text for term in _TOPIC_TERMS[topic])]


def match_entity_mentions(graph, chunks, *, per_node=2, topics=None):
    requested_topics = None if topics is None else set(topics)
    nodes = {}
    for node in graph.get('nodes', []):
        if set(node.get('labels', [])) & {'Root', '环节'}:
            continue
        name = str((node.get('properties') or {}).get('name') or '').strip()
        if len(name) < 4:
            continue
        node_topics = classify_node_topics(node, graph)
        if requested_topics is not None and not requested_topics.intersection(node_topics):
            continue
        nodes.setdefault(name, []).append(node)
    if not nodes:
        return []
    pattern = re.compile('|'.join(re.escape(name) for name in sorted(nodes,key=lambda name:-len(name))))
    links, seen = {}, set()
    for chunk in chunks:
        text = chunk['text']
        for match in pattern.finditer(text):
            name = match.group()
            for node in nodes[name]:
                key = (node['id'],chunk['chunk_id'])
                if key in seen:
                    continue
                seen.add(key)
                link = links.setdefault(node['id'], {'element_type':'node','id':node['id'],'name':name,
                    'topic': classify_node_topics(node, graph)[0] if classify_node_topics(node, graph) else 'humanoid_robot',
                    'evidence_kind':'entity_mention','verification_status':'pending','evidence_refs':[],
                    'evidence_excerpt':text[max(0,match.start()-100):match.end()+200],
                    'review_note':'待人工阅读原文后确认实体指向和可用范围。',
                    'title':chunk['metadata'].get('title','')})
                if len(link['evidence_refs']) < per_node:
                    metadata=chunk['metadata']
                    link['evidence_refs'].append({'chunk_id':chunk['chunk_id'],'document_id':chunk['document_id'],
                        'material_id':metadata.get('material_id',''),'library':metadata.get('library',''),
                        'evidence_excerpt':text[max(0,match.start()-100):match.end()+200],
                        'title':chunk['metadata'].get('title','')})
    return list(links.values())


def source_chunks(industry, limit):
    path=index_path(industry)
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='chunks' AND type='table'").fetchone():
            for row in c.execute('SELECT chunk_id,document_id,text,metadata_json FROM chunks ORDER BY rowid LIMIT ?', (limit,)):
                yield {'chunk_id':row['chunk_id'],'document_id':row['document_id'],'text':row['text'],'metadata':json.loads(row['metadata_json'])}
        else:
            segment=_news_segment(c,industry)
            ids=c.execute('SELECT embedding_id FROM embeddings WHERE segment_id=? ORDER BY id LIMIT ?', (segment,limit)).fetchall()
            for row in ids:
                record=_news_record(c,industry,segment,row['embedding_id'])
                yield {'chunk_id':record['chunk_id'],'document_id':record['document_id'],'text':record['text'],'metadata':json.loads(record['metadata_json'])}


def build(industry, output, scan_limit=5000, topics=None):
    output=Path(output)
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}; choose another path to preserve reviewed links')
    config=get_industry_config(industry)
    graph=json.loads(Path(config['graph_path']).read_text(encoding='utf8'))
    count=0
    def counted():
        nonlocal count
        for row in source_chunks(industry,scan_limit):
            count+=1
            yield row
    links=match_entity_mentions(graph,counted(),topics=topics)
    payload={'version':1,'industry':industry,'topics':sorted(topics or ALLOWED_TOPICS),
             'scan_limit':scan_limit,'scanned_chunks':count,
             'description':'Entity mentions only; these links do not prove any graph relationship.','links':links}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    lines=['# 图谱实体证据候选', '',f'产业：{config["name"]}；扫描 {count} 个真实片段；命中 {len(links)} 个实体。', '',
           '这些记录仅表示原文中出现了实体全名，不证明参与环节、生产、供应或政策影响关系。',
           '检查名称是否指向同一个实体和原文是否适合检索后，可把该条 verification_status 改为 approved。', '']
    for link in links:
        lines.extend([f'## {link["name"]}（节点 {link["id"]}）','',f'资料：{link["title"]}', '',link['evidence_excerpt'],'',
                      '证据标识：'+', '.join(ref['chunk_id'] for ref in link['evidence_refs']),''])
    output.with_suffix('.md').write_text('\n'.join(lines),encoding='utf8')
    return {'industry':industry,'scanned_chunks':count,'matched_nodes':len(links),'references':sum(len(link['evidence_refs']) for link in links),'output':str(output.resolve())}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--industry',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scan-limit',type=int,default=5000)
    parser.add_argument('--topics', default=','.join(ALLOWED_TOPICS),
                        help='Comma-separated topic filters')
    args=parser.parse_args()
    if args.scan_limit <= 0:
        parser.error('--scan-limit must be positive')
    topics = [item.strip() for item in args.topics.split(',') if item.strip()]
    unknown = sorted(set(topics) - set(ALLOWED_TOPICS))
    if unknown:
        parser.error(f'unknown topics: {", ".join(unknown)}')
    print(json.dumps(build(args.industry,args.output,args.scan_limit,topics),ensure_ascii=False))
