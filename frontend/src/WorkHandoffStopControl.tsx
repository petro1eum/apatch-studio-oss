import { useEffect, useRef, useState } from 'react';
import { stopExactWorkForReassignment } from './exactContractDeliveryApi';

/** Local confirmation only; the owner creates the request on the site. */
export function WorkHandoffStopControl({ handoffId, workspaceId }: { handoffId:string; workspaceId:string }) {
  const ru=document.documentElement.lang.startsWith('ru');
  const [message,setMessage]=useState(''),[busy,setBusy]=useState(false);
  const context=`${workspaceId}/${handoffId}`,current=useRef(context);current.current=context;
  const pending=useRef(false);
  useEffect(()=>{setMessage('');setBusy(false);pending.current=false;return()=>{current.current='';};},[context]);
  async function stop(){
    if(pending.current)return;
    pending.current=true;setBusy(true);setMessage('');
    try {
      const state=await stopExactWorkForReassignment(handoffId,workspaceId);
      if(current.current!==context)return;
      setMessage(state==='stop_requested'
        ? (ru?'Эта среда остановлена; подтверждения других сред ещё ожидаются. Новый исполнитель не назначен.':'This environment stopped; other environments have not confirmed yet. No new performer has been assigned.')
        : (ru?'Независимая остановка подтверждена сервером. Дальнейшую передачу согласует заказчик на сайте.':'The server confirmed the independent stop. The customer arranges the next assignment on the site.'));
    } catch {
      if(current.current===context)setMessage(ru?'Остановка не подтверждена. Нужны запрос заказчика и независимо допущенная среда остановки.':'Stop is not confirmed. A customer request and an independently admitted stop environment are required.');
    } finally {if(current.current===context){pending.current=false;setBusy(false);}}
  }
  return <div style={{marginTop:16}} data-testid="work-handoff-stop-control">
    <p>{ru?'Если заказчик запросил замену исполнителя, остановите эту работу перед передачей.':'If the customer requested a new performer, stop this work before handing it over.'}</p>
    <button type="button" disabled={busy} className="oi-button oi-button-secondary" onClick={()=>void stop()}>
      {ru?'Подтвердить безопасную остановку':'Confirm safe stop'}
    </button>
    {message&&<p role="status">{message}</p>}
  </div>;
}
