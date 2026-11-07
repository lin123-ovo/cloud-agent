"""Import the bundled example graph into the project's local Neo4j database."""
import json
import re
from pathlib import Path

from test.build_kg import import_to_neo4j

source = Path('mock_data/ecs_product_info.json')
data = json.loads(source.read_text(encoding='utf-8'))
node_ids = {node['id'] for node in data['nodes']}
if len(node_ids) != len(data['nodes']):
    raise ValueError('图谱存在重复节点 ID')
for node in data['nodes']:
    label = node['label'].replace(' ', '_').replace('-', '_')
    if not re.fullmatch(r'[^\W\d]\w*', label):
        raise ValueError(f'无效的图谱节点标签: {label}')
for edge in data['edges']:
    label = edge['type'].replace(' ', '_').replace('-', '_').upper()
    if not re.fullmatch(r'[^\W\d]\w*', label):
        raise ValueError(f'无效的图谱关系类型: {label}')
valid_edges = [edge for edge in data['edges'] if edge['source'] in node_ids and edge['target'] in node_ids]
print(f"忽略端点缺失的关系: {len(data['edges']) - len(valid_edges)}")
import_to_neo4j({'nodes': data['nodes'], 'edges': valid_edges})
