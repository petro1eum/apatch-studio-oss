"""Native stop command uses only the imported exact task and authenticated server request.

No HTTP caller supplies an observer identity, key, signature or stopped boolean.
The qualified restricted host service must inject the observer before startup.
"""
from apatch import governed_work_delivery as D
from apatch import governed_work_transport as T
from apatch_studio.work_handoff_stop import StopUnavailable, canonical
from apatch_studio.security import _normalized_origin

class WorkHandoffDelivery:
    def __init__(self, manager, observer):
        self.manager, self.observer = manager, observer

    def stop(self,handoff_id,confirmation):
        m,o=self.manager,self.observer
        if (o is None or o.qualification is None or o.containment is None
                or getattr(m.run_manager,'_handoff_process_control',None) is not o.control):
            raise StopUnavailable('Independent contained stop observation is not configured')
        if confirmation != {'workspace_id':m.workspace_id} or o.qualification['workspace_id']!=m.workspace_id:
            raise StopUnavailable('Exact local workspace confirmation is required')
        row=m._update(lambda records:m._find(records,handoff_id))
        bundle=m._read_bundle(row,historical=True)
        h=bundle['handoff']
        scope={name:h[name] for name in ('tenant_id','project_group_id','work_item_id')}
        config=D.load_config(str(m.workspace))
        origin=_normalized_origin(config['platform_url'])
        if (origin is None or origin not in m.trust.trusted_origins
                or config['platform_url'].rstrip('/')!=origin
                or o.qualification['request_key_id']!=config['service_request_key_id']):
            raise StopUnavailable('Stop authority does not match the configured origin and enrolled key')
        provider=m.gateway._workspace_key_provider()
        def exchange(operation,extra=None):
            path=f"/api/internal/client/project-groups/{scope['project_group_id']}/work-items/{scope['work_item_id']}/handoff/{operation}"
            body={'subject':config['client_id'],'tenant_id':scope['tenant_id'],**(extra or {})}
            raw=canonical(body)
            headers={'Content-Type':'application/json',**T.signed_service_headers(str(m.workspace),method='POST',
                path=path,raw_body=raw,tenant_id=scope['tenant_id'],subject=config['client_id'],
                expected_key_id=config['service_request_key_id'],key_provider=provider)}
            with m.http_client_factory() as client:
                response=client.post(origin+path,content=raw,headers=headers)
            if response.status_code!=200:
                raise StopUnavailable('The current server stop authority rejected the operation')
            return response.json()
        result=exchange('query')
        if (not isinstance(result,dict) or set(result)!={'schema','requests'}
                or result['schema']!='trustchain.cowork.work-handoff.v1' or not isinstance(result['requests'],list)):
            raise StopUnavailable('Stop request response is invalid')
        selected=[r for r in result['requests'] if isinstance(r,dict) and r.get('observer_id')==o.qualification['observer_id']]
        if len(selected)!=1 or set(selected[0])!={'observer_id','request','acknowledgement_hash'} or selected[0]['request'].get('scope')!=scope:
            raise StopUnavailable('Server stop request is for another observer or task')
        acknowledgement=o.stop(selected[0]['request'],accepted_ack_hash=selected[0]['acknowledgement_hash'])
        return exchange('ack',{'acknowledgement':acknowledgement})
