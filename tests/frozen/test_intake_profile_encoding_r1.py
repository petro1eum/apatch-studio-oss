"""Actual native HTTP/SDK intake with the two existing profile writers."""
import hashlib
import importlib.util
import json
from pathlib import Path

ORIGINAL = Path('/Users/edcher/Documents/GitHub/apatch-studio-oss/tests/frozen/test_intake_historical_parent_r1.py')
loader = importlib.util.spec_from_file_location('profile_encoding_original_fixture', ORIGINAL)
probe = importlib.util.module_from_spec(loader)
loader.loader.exec_module(probe)
c = probe.c


def native_writer_forms(c):
    # Studio writes the active profile with indentation and a trailing newline.
    # Core's immutable profile archive uses its flat JSON writer.
    active = (json.dumps(c.contract, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    archived = json.dumps(c.contract, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    probe.write(c.root, probe.core.PROFILE, active)
    probe.write(c.root, '.apatch/sdd/frozen/'+c.contract['document_hash'][7:]+'.json', archived)
    return active, archived


def test_actual_two_writer_history_allows_fresh_review(c):
    active, archived = native_writer_forms(c)
    assert hashlib.sha256(active).digest()!=hashlib.sha256(archived).digest()
    first = probe.completed(c)
    current = probe.grow(c)
    before = probe.snapshot(c.root)
    response = probe.propose(c, 'apsreq_fixture_writer_forms', 1)
    assert response.status_code==200, response.text
    value = response.json()
    assert value['status']=='awaiting_approval'
    assert value['functional_acceptance'] is False and value['implementation_allowed'] is False
    assert value['owner_freeze_required'] is True
    assert value['review']['active_contract_hash']==current['document_hash']
    assert value['snapshot']!=first['snapshot']
    assert len([v for v in probe.records(c) if v['tool']==probe.core.TOOL])==2
    for path, data in before.items():
        if path.startswith('.trustchain/') or path in c.protected or path==probe.core.PROFILE:
            assert (c.root/path).read_bytes()==data


def test_noncanonical_archive_newline_is_still_refused(c):
    native_writer_forms(c)
    probe.completed(c)
    probe.grow(c)
    archive = c.root/'.apatch/sdd/frozen'/(c.contract['document_hash'][7:]+'.json')
    archive.write_bytes(archive.read_bytes()+b'\n')
    probe.refusal_unchanged(c)


def test_changed_profile_values_are_still_refused(c):
    native_writer_forms(c)
    probe.completed(c)
    probe.grow(c)
    archive = c.root/'.apatch/sdd/frozen'/(c.contract['document_hash'][7:]+'.json')
    value = json.loads(archive.read_bytes())
    value.pop('document_hash')
    value['plan_hash']=probe.digest(b'foreign profile values')
    probe.write(c.root, archive.relative_to(c.root).as_posix(), probe._seal(value))
    probe.refusal_unchanged(c)


def test_corrupt_original_signature_is_still_refused(c):
    native_writer_forms(c)
    first = probe.completed(c)
    probe.grow(c)
    locator = json.loads((c.root/probe.core._folder(first['review'])/'completed.json').read_bytes())
    path=c.root/'.trustchain'/locator['object_path']
    value=json.loads(path.read_bytes())
    record=value.get('value',value)
    record['signature']=probe.base64.b64encode(b'\x00'*64).decode()
    probe.write(c.root, path.relative_to(c.root).as_posix(), value)
    probe.refusal_unchanged(c)
