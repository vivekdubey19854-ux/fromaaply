// Lightweight UI safety bridge: when the backend cannot confidently discover a target,
// ask the user for the exact URL and resume the same workflow. It never submits a form.
const nativeFetch=window.fetch.bind(window);
window.fetch=async(input,init={})=>{
  const response=await nativeFetch(input,init);
  try{
    const url=typeof input==='string'?input:input.url;
    if(url.endsWith('/v1/workflows') && init.method==='POST'){
      const clone=response.clone();const data=await clone.json();
      if(data?.state==='awaiting_url' && data.workflow_id){
        const target=window.prompt('Formwise ko exact form/site link nahi mila. Kripya exact application URL paste karein:');
        if(target?.trim()){
          const uid=localStorage.getItem('formwise_user');
          await nativeFetch(`${url}/${data.workflow_id}/url`,{method:'POST',headers:{'Content-Type':'application/json','X-User-ID':uid||''},body:JSON.stringify({url:target.trim()})});
          window.location.reload();
        }
      }
    }
  }catch{ /* original response must remain untouched */ }
  return response;
};
