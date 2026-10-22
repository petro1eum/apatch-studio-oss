"""Pin checks at the fixed root CLI boundary; no root/server calls."""
import io
import sys
from types import SimpleNamespace

import pytest
import qa_handoff_cli as cli
from qa_handoff import digest
from test_qa_handoff import admission


@pytest.fixture
def boundary(tmp_path,monkeypatch):
    a=admission(tmp_path);started=[];signed=[]
    core=SimpleNamespace(trusted=lambda *a,**k:None,LinuxKernel=lambda *a:None,DockerEngine=lambda:None,
        digest=digest,ContainerControl=lambda *a: SimpleNamespace(spawn=lambda *a:started.append(a)))
    monkeypatch.setattr(cli,'public_admission',lambda:(core,a))
    return SimpleNamespace(a=a,core=core,started=started,signed=signed)


@pytest.mark.parametrize('change',['run','admission','missing','stop_pin'])
def test_start_requires_current_native_run_and_complete_root_admission(boundary,monkeypatch,change):
    b=boundary
    args=['start','--run-id',b.a['observer']['expected_run_ids'][0],'--admission-sha256',digest(b.a)]
    if change=='run':args[2]='apr_'+'f'*32
    elif change=='admission':args[4]='sha256:'+'f'*64
    elif change=='missing':args=['start']
    else:args+=['--request-id','tcwh_'+'1'*32]
    monkeypatch.setattr(sys,'argv',['qa_handoff_cli.py',*args])
    with pytest.raises(RuntimeError):cli.main()
    assert b.started==[]


def test_public_admission_is_read_only_before_container_control(boundary,monkeypatch,capsys):
    b=boundary;b.core.ContainerControl=lambda *a:pytest.fail('Public read cannot inspect or launch container')
    monkeypatch.setattr(sys,'argv',['qa_handoff_cli.py','admission'])
    cli.main()
    import json
    assert json.loads(capsys.readouterr().out)==b.a
    assert not b.started


def test_changed_current_query_pin_cannot_reach_signer(boundary,monkeypatch):
    b=boundary;request={'request_id':'tcwh_'+'1'*32,'scope':b.a['scope']}
    envelope={'schema':'trustchain.cowork.qa-handoff-authority-query.v1','request':request,'acknowledgement_hash':None}
    b.core.load_json=lambda _:envelope
    monkeypatch.setattr(cli,'signer',lambda _:pytest.fail('Changed query must not reach signer'))
    for request_pin,ack_pin in [('sha256:'+'f'*64,digest(None)),(digest(request),'sha256:'+'f'*64)]:
        monkeypatch.setattr(sys,'argv',['qa_handoff_cli.py','stop','--request-id',request['request_id'],
            '--request-sha256',request_pin,'--acknowledgement-sha256',ack_pin])
        with pytest.raises(RuntimeError,match='Native query differs'):cli.main()
    assert not b.started


def test_native_prompt_is_forwarded_as_data_to_fixed_process(boundary,monkeypatch,capsys):
    b=boundary
    class Input(io.StringIO):
        def close(self):self.saved=self.getvalue();super().close()
    sink=Input();process=SimpleNamespace(stdin=sink,stdout=iter(['heartbeat\n']),wait=lambda:143)
    def spawn(scope,run_id,start):
        assert scope==b.a['scope'] and run_id==b.a['observer']['expected_run_ids'][0]
        b.started.append(run_id);return start()
    control=SimpleNamespace(spawn=spawn,popen=lambda argv,**kw:process)
    b.core.ContainerControl=lambda *a:control
    monkeypatch.setattr(sys,'stdin',io.StringIO('untrusted $(data), never a command'))
    monkeypatch.setattr(sys,'argv',['qa_handoff_cli.py','start','--run-id',b.a['observer']['expected_run_ids'][0],
        '--admission-sha256',digest(b.a)])
    with pytest.raises(SystemExit) as err:cli.main()
    assert err.value.code==143 and sink.saved=='untrusted $(data), never a command'
    assert capsys.readouterr().out=='heartbeat\n' and len(b.started)==1
