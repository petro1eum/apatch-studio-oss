"""Closed provider validation; actual namespaces/Landlock need the VM probe."""
import copy
import pytest
import qa_handoff as q
import qa_systemd_handoff as sd
from test_qa_handoff import admission


def native(root):
    old=admission(root)
    for name in ('container_id','container_created','image','container_env_sha256'):old.pop(name)
    return {**old,'schema':sd.SCHEMA,'unit':'tc-cowork-native-'+'1'*32+'.service',
        'root_directory':'/var/lib/trustchain-cowork-native-rootfs/test/root',
        'rootfs_image':'sha256:'+'2'*64,'environment':{'HOME':old['workspace']}}


def test_distinct_provider_never_claims_runsc(tmp_path):
    a=native(tmp_path);assert q.validate_admission(a)==a
    assert 'container_id' not in a and a['schema']!=q.SCHEMA


@pytest.mark.parametrize('change',[
    {'root_directory':'/'},{'unit':'sshd.service'},
    {'environment':{'HOME':'bad\0value'}},{'unexpected':'field'},
])
def test_rejects_foreign_unit_root_or_open_configuration(tmp_path,change):
    a=copy.deepcopy(native(tmp_path));a.update(change)
    with pytest.raises(q.StopUnavailable):q.validate_admission(a)
