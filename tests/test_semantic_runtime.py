import importlib.util
import json
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec('sentence_transformers') is None, reason='Optional inference runtime')
def test_real_offline_encoder_and_vector_search_roundtrip(tmp_path):
    code = '''import json,sys
from pathlib import Path
from unittest.mock import patch
from sociolit.semantic_smoke import verify
output,error=sys.stdout,sys.stderr
try:
    sys.stdout=sys.stderr=None
    with patch('socket.socket.connect', side_effect=AssertionError('Offline inference attempted network access')):
        result=verify(Path(sys.argv[1]))
finally:
    sys.stdout,sys.stderr=output,error
print(json.dumps(result))
'''
    child = subprocess.run([sys.executable, '-c', code, str(tmp_path)], timeout=90, capture_output=True,
                           text=True, encoding='utf-8', errors='replace', env=dict(os.environ, PYTHONUTF8='1'))
    assert child.returncode == 0, child.stderr[-4000:]
    assert json.loads(child.stdout.strip().splitlines()[-1]) == {'semantic_roundtrip': True, 'embedding_dimensions': 16}
