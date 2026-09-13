import test from 'node:test';
import assert from 'node:assert/strict';
import {api,sendPending,effectiveMode,ApiError} from '../src/engine-api.ts';
import {originalExtension,sourceLabel,runProgress,initialDraft} from '../src/domain.ts';

function json(data,status=200){return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}})}
const pending={path:'/batches',body:{requestId:'request-1',draft:structuredClone(initialDraft),resolvedSeeds:['9007199254740993']}};

test('cancel without a body sends the JSON contract and accepts cancelling',async t=>{
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    assert.equal(url,'/api/v1/runs/run-1/cancel');assert.equal(options.method,'POST');
    assert.equal(options.headers['Content-Type'],'application/json');assert.equal(options.body,'{}');
    return json({id:'run-1',state:'cancelling'},202);
  });
  assert.equal((await api('/runs/run-1/cancel','POST')).state,'cancelling');
});
test('all empty writes use JSON while GET keeps an absent body',async t=>{
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    if(options.method==='GET'){assert.equal(options.body,undefined);assert.equal(options.headers['Content-Type'],undefined)}
    else{assert.equal(options.headers['Content-Type'],'application/json');assert.equal(options.body,'{}')}
    return json({});
  });
  for(const method of ['POST','PATCH','PUT','DELETE','GET'])await api('/contract',method);
});

test('lost POST response reconciles accepted batch without generating a second request',async t=>{
  let accepted=false,posts=0;
  t.mock.method(globalThis,'fetch',async(url,options)=>{assert.ok(url.startsWith('/api/v1/'));if(options.method==='POST'){posts++;accepted=true;assert.equal(JSON.parse(options.body).resolvedSeeds[0],'9007199254740993');throw new TypeError('lost response')};return accepted?json({requestId:'request-1',batchId:'batch-1',runs:[],replayed:true}):json({detail:'Not found'},404)});
  assert.equal((await sendPending(pending)).batchId,'batch-1');assert.equal(posts,1);
  await sendPending(pending);assert.equal(posts,1);
});
test('unaccepted disconnected request remains uncertain and retry uses identical ID/body',async t=>{
  const posted=[];let connected=false;
  t.mock.method(globalThis,'fetch',async(url,options)=>{if(options.method==='POST'){posted.push(options.body);if(!connected)throw new TypeError('offline');return json({requestId:'request-1',batchId:'batch-2',runs:[],replayed:false},201)}return json({detail:'Not found'},404)});
  await assert.rejects(sendPending(pending));connected=true;await sendPending(pending);
  assert.equal(posted.length,2);assert.equal(posted[0],posted[1]);
});
test('retry request follows same acceptance reconciliation and preserves retry route',async t=>{
  t.mock.method(globalThis,'fetch',async(url,options)=>{if(options.method==='GET')return json({detail:'missing'},404);assert.equal(url,'/api/v1/runs/run-1/retry');assert.deepEqual(JSON.parse(options.body),{requestId:'retry-1'});return json({requestId:'retry-1',batchId:'b',runs:[],replayed:false})});
  assert.equal((await sendPending({path:'/runs/run-1/retry',body:{requestId:'retry-1'}})).requestId,'retry-1');
});
test('server failures never become empty successful state',async t=>{
  t.mock.method(globalThis,'fetch',async()=>json({detail:'输入无效'},422));
  await assert.rejects(api('/state'),e=>e instanceof ApiError&&e.status===422&&e.message==='输入无效');
});
test('health reconnection preserves deliberate demo mode',()=>{
  assert.equal(effectiveMode('live',true),'live');assert.equal(effectiveMode('live',false),'offline');
  assert.equal(effectiveMode('demo',false),'demo');assert.equal(effectiveMode('demo',true),'demo');
});
test('server snapshot is read without browser interruption recovery',async t=>{
  const state={runs:[{state:'generating_tokens',snapshot:{runtime:'local-yue2',seed:'9007199254740993'}}],tracks:[],queuePaused:false,eventCursor:11};
  t.mock.method(globalThis,'fetch',async()=>json(state));
  assert.deepEqual(await api('/state'),state);
});
test('generated FLAC retains extension and source; browser-associated files retain their own format',()=>{
  assert.equal(originalExtension({audioKind:'generated',audioFormat:'flac'}),'flac');
  assert.equal(sourceLabel({audioKind:'generated'}),'本机生成');
  assert.equal(originalExtension({audioKind:'official-demo'}),'mp3');
  assert.equal(originalExtension({audioKind:'local',sourceTitle:'录音.wav'}),'wav');
});
test('token count is shown as count, never fabricated percent',()=>{
  assert.equal(runProgress({elapsed:60,progress:{detail:'生成音乐',completed:128,total:null,unit:'tokens'}}),'生成音乐 · 128 tokens · 已用时 01:00');
});
