import sys
import os
from pathlib import Path

import pytest


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(autouse=True)
def isolate_local_credentials(monkeypatch, tmp_path):
	import checkin

	monkeypatch.setattr(checkin, 'ENV_PATH', tmp_path / '.env')
	for key in os.environ:
		if key.startswith(('GLADOS_', 'FEISHU_', 'CHECKIN_')):
			monkeypatch.delenv(key)
