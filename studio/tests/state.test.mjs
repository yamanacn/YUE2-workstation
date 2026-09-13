import test from 'node:test';
import assert from 'node:assert/strict';
import {createBatch,cloneDraft,initialDraft,validateDraft,resolveSeeds,transitionRun,recoverState} from '../src/domain.ts';

test('queued snapshots retain original lyrics and deep parameter values',()=>{
  const draft=cloneDraft(initialDraft);const [run]=createBatch(draft,'request-test',['831001']);
  draft.lyrics='changed';draft.config.temperature=3;
  assert.equal(run.snapshot.draft.lyrics,initialDraft.lyrics);
  assert.equal(run.snapshot.draft.config.temperature,1);
  assert.ok(Object.isFrozen(run.snapshot.draft.config));
});
test('long seeds preserve precision and reject increment overflow',()=>{
  const draft={...cloneDraft(initialDraft),seedMode:'increment',seed:'9007199254740993',count:2};
  assert.deepEqual(resolveSeeds(draft),['9007199254740993','9007199254740994']);
  draft.seed='9223372036854775807';assert.ok(validateDraft(draft).some(e=>e.field==='seed'));
});
test('cancellation acknowledgement and late callbacks cannot reverse terminal state',()=>{
  let [run]=createBatch(cloneDraft(initialDraft),'request-cancel',['831001']);
  run=transitionRun(run,'checking');run=transitionRun(run,'cancelling');
  assert.equal(transitionRun(run,'succeeded'),run);
  run=transitionRun(run,'cancelled');assert.equal(transitionRun(run,'checking'),run);
});
test('out of order progress does not skip directly to success',()=>{
  const [run]=createBatch(cloneDraft(initialDraft),'request-order',['831001']);
  assert.equal(transitionRun(run,'succeeded'),run);
});
test('restart preserves queued work but interrupts unfinished runs and pauses scheduling',()=>{
  const [run]=createBatch(cloneDraft(initialDraft),'request-recover',['831001']);
  const next=recoverState({version:1,draft:initialDraft,tracks:[],runs:[transitionRun(run,'checking')],paused:false});
  assert.equal(next.runs[0].state,'interrupted');assert.equal(next.paused,true);
});

test('music sequence budget matches the local engine upper boundary',()=>{
  const draft=cloneDraft(initialDraft);
  draft.config.maxTokens=24575;
  assert.equal(validateDraft(draft).some(e=>e.field==='config'),false);
  draft.config.maxTokens=24576;
  assert.equal(validateDraft(draft).some(e=>e.field==='config'),true);
});
