import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run


def test_scoped_worker_never_requests_legacy_identity_transfer():
    with patch.object(run, 'previous_device_id', return_value='legacy-device'):
        assert run.registration_alias(SimpleNamespace(scoped_credential=True)) is None
        assert run.registration_alias(SimpleNamespace(scoped_credential=False)) == 'legacy-device'
        assert run.registration_alias(SimpleNamespace()) == 'legacy-device'


def test_missing_scoped_key_stops_before_model_or_installation_lock():
    with patch.dict(os.environ, {}, clear=True), patch.object(run, 'lock_worker') as lock:
        with pytest.raises(RuntimeError, match='Set API_TOKEN privately'):
            asyncio.run(run.run(SimpleNamespace(scoped_credential=True)))
        lock.assert_not_called()
