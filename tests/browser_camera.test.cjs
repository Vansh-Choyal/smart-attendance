/* Isolated JavaScript component tests; no browser automation or real camera. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = name => fs.readFileSync(path.join(__dirname,'../static/js/',name),'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

function fixture({secure=true,denied=false,https=false}={}) {
  const elements = new Map(), storage = new Map(), timers = [], calls = [], events = new Map();
  let mediaCalls = 0, stoppedTracks = 0, acceptUpload;
  const video = {isConnected:true,videoWidth:1280,videoHeight:720,hidden:true,play:async()=>{},pause(){},addEventListener(){}};
  const element = id => {
    if (!elements.has(id)) elements.set(id,{hidden:true,content:'csrf',classList:{add(){},remove(){}},addEventListener(){},replaceChildren(){},append(){},focus(){}});
    return elements.get(id);
  };
  const A = {operator:true,ready:Promise.resolve(),csrf:'csrf',$:element,requireOperator:async()=>true,toast(){},
    async post(url) { calls.push({url}); if(url.endsWith('/start')) return {publisher_token:'publisher',capture_ticket:'ticket-1',sequence:1,fps:12}; return {}; },
    api(url,options) { calls.push({url,options}); return new Promise(resolve => {acceptUpload=resolve;}); }
  };
  const window = {Attend:A,isSecureContext:secure,addEventListener(name,handler){events.set(name,handler);},dispatchEvent(){}};
  const document = {hidden:false,body:{dataset:{httpsPort:'5443'},append(){}},querySelector(){return video;},createElement(name){
    if(name==='canvas') return {getContext:()=>({drawImage(){}}),toBlob:callback=>callback(new Blob(['jpeg'],{type:'image/jpeg'}))};
    return video;
  }};
  const context = vm.createContext({window,document,location:{href:https ? 'https://192.168.1.4:5443/setup' : 'http://192.168.1.4:5000/setup',protocol:https ? 'https:' : 'http:'},URL,Blob,
    navigator:{mediaDevices:{async getUserMedia(constraints){
      mediaCalls++; calls.push({constraints});
      if(denied) { const error=new Error('denied'); error.name='NotAllowedError'; throw error; }
      const track={stop(){stoppedTracks++;},addEventListener(){}};
      return {getTracks:()=>[track],getVideoTracks:()=>[track]};
    }}},
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    performance:{now:()=>0},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},
    setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length;},clearTimeout(){},fetch:async()=>({ok:true})});
  vm.runInContext(source('browser-camera.js'),context);
  return {C:window.BrowserCamera,A,document,calls,timers,storage,video,get mediaCalls(){return mediaCalls;},get stoppedTracks(){return stoppedTracks;},accept(value){acceptUpload(value);}};
}

test('insecure LAN capture stays blocked and supplies the secure local address',async()=>{
  const f=fixture({secure:false});
  assert.equal(await f.C.start(),false);
  assert.equal(f.mediaCalls,0);
  assert.equal(f.C.secureUrl(),'https://192.168.1.4:5443/setup#phone-camera');
  assert.match(f.C.error,/secure connection/);
});

test('denied permission starts no server publisher',async()=>{
  const f=fixture({denied:true});
  assert.equal(await f.C.start(),false);
  assert.equal(f.C.stream,null);
  assert.match(f.C.error,/denied/);
  assert.equal(f.calls.filter(call=>call.url?.endsWith('/start')).length,0);
});

test('an untrusted HTTPS context explains certificate trust instead of asking for the same redirect',async()=>{
  const f=fixture({secure:false,https:true});
  assert.equal(await f.C.start(),false);
  assert.equal(f.mediaCalls,0);
  assert.match(f.C.error,/trusts the local certificate/);
});

test('double clicks open one camera and allow only one in-flight frame upload',async()=>{
  const f=fixture();
  const results=await Promise.all([f.C.start(),f.C.start()]);
  assert.equal(results.filter(Boolean).length,1);
  assert.equal(f.mediaCalls,1);
  await settle();
  const upload=f.calls.find(call=>call.url?.endsWith('/frame'));
  assert.equal(upload.options.headers['Content-Type'],'image/jpeg');
  assert.equal(upload.options.headers['X-Camera-Session'],'publisher');
  assert.equal(upload.options.headers['X-Frame-Sequence'],'1');
  assert.equal(upload.options.body.type,'image/jpeg');
  assert.equal(f.timers.length,0,'a new frame cannot be scheduled until this request finishes');
  await f.C.stop();
  assert.equal(f.stoppedTracks,1);
  assert.equal(f.storage.size,0);
  f.accept({capture_ticket:'ticket-2',sequence:2});
  await settle();
  assert.equal(f.timers.length,0,'late request responses cannot restart a stopped stream');
});

test('hidden tabs pause uploads and require a fresh ticket on return',async()=>{
  const f=fixture(); f.document.hidden=true;
  await f.C.start(); await settle();
  assert.equal(f.C.phase,'paused');
  assert.equal(f.C.needTicket,true);
  assert.equal(f.calls.filter(call=>call.url?.endsWith('/frame')).length,0);
  await f.C.stop();
});

test('shared API helper preserves binary content type and adds CSRF',async()=>{
  const elements=new Map(),requests=[];
  const element=id=>{if(!elements.has(id))elements.set(id,{content:'csrf',addEventListener(){},classList:{add(){},remove(){}}});return elements.get(id);};
  const document={body:{dataset:{operator:'true',timezone:'Asia/Kolkata',page:'setup'}},getElementById:element,querySelector:()=>element('meta'),querySelectorAll:()=>[]};
  const window={dispatchEvent(){}};
  const context=vm.createContext({window,document,Intl,Date,AbortController,Blob,CustomEvent:class{},
    setTimeout:()=>1,clearTimeout(){},fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({ok:true,data:url.endsWith('/auth/status')?{operator:true,csrf:'new-csrf'}:{}})};}});
  vm.runInContext(source('app.js'),context);
  await window.Attend.ready;
  const body=new Blob(['jpeg'],{type:'image/jpeg'});
  await window.Attend.api('/api/camera/browser/frame',{method:'POST',body,headers:{'Content-Type':'image/jpeg'}});
  const request=requests.find(request=>request.url.endsWith('/frame'));
  assert.equal(request.options.headers['Content-Type'],'image/jpeg');
  assert.equal(request.options.headers['X-CSRF-Token'],'new-csrf');
  assert.equal(request.options.body,body);
});
