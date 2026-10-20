"""Qualify released Core bytes; reject unsupported runtimes before publication."""
from types import SimpleNamespace
import pytest
from apatch_studio import selected_governed_work_delivery as delivery

def test_installed_core_0855_source_and_private_abi_are_supported():
    assert delivery.importlib.metadata.version('apatch') == '0.8.55'
    delivery.qualify_native_delivery()

def test_unknown_version_cannot_touch_queue_or_sign(monkeypatch):
    original=delivery.importlib.metadata.distribution('apatch')
    monkeypatch.setattr(delivery.importlib.metadata,'distribution',lambda name:SimpleNamespace(version='0.8.56',locate_file=original.locate_file))
    with pytest.raises(delivery.SelectedDeliveryError) as exc:
        delivery.dispatch_selected('/nonexistent',entry_id='not-opened',request_hash='not-read',key_provider=None,expected_scope={})
    assert exc.value.code=='publication_runtime_unsupported'

def test_changed_module_bytes_cannot_reach_queue_or_sign(monkeypatch,tmp_path):
    altered=tmp_path/'governed_work_mcp.py';altered.write_text('changed source')
    monkeypatch.setattr(delivery.M,'__file__',str(altered))
    with pytest.raises(delivery.SelectedDeliveryError) as exc:
        delivery.dispatch_selected('/nonexistent',entry_id='not-opened',request_hash='not-read',key_provider=None,expected_scope={})
    assert exc.value.code=='publication_runtime_unsupported'

def test_changed_private_helper_abi_is_refused(monkeypatch):
    monkeypatch.setattr(delivery.D,'_ack_source_binding',lambda unrelated:None)
    with pytest.raises(delivery.SelectedDeliveryError) as exc:
        delivery.qualify_native_delivery()
    assert exc.value.code=='publication_runtime_unsupported'
