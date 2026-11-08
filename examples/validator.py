"""Example trusted validator: require an actually computed result."""
import json
from pathlib import Path
data = json.loads(Path('result.json').read_text())
assert data['sum'] == sum(range(1, 101)), 'Expected the verified sum 5050'
