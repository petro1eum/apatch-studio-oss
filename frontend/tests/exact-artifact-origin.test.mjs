import assert from 'node:assert/strict';
import test from 'node:test';
import {previewExactArtifacts} from '../src/exactContractDeliveryApi.ts';

const handoff='tceh_'+'a'.repeat(32),run='apr_'+'b'.repeat(32);
globalThis.document={querySelector:()=>null};
async function preview(origin){
  globalThis.fetch=async()=>({ok:true,json:async()=>({schema:'apatch.studio.exact-artifact-preview.v1',
    handoff_id:handoff,run_id:run,customer_accepted:false,package_hash:'sha256:'+'c'.repeat(64),
    project_group_id:'tcpg_'+'d'.repeat(32),platform_origin:origin,
    files:[{path:'result.json',sha256:'sha256:'+'e'.repeat(64)}]})});
  return previewExactArtifacts(handoff,run);
}
test('permits HTTPS and local HTTP origins used by the exact trusted handoff',async()=>{
  for(const origin of ['https://company.example','http://127.0.0.1:62502','http://localhost:5000','http://[::1]:5000'])
    assert.equal((await preview(origin)).platform_origin,origin);
});
test('rejects remote HTTP, deceptive loopback hosts and non-origin URLs',async()=>{
  for(const origin of ['http://192.0.2.4','http://127.0.0.1.attacker.example','http://alice@localhost',
      'http://localhost/path','http://localhost/?q=1','http://localhost/#part'])
    await assert.rejects(()=>preview(origin));
});
