const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = {};
for (const id of ['proc-reuse-video', 'proc-reuse-ass', 'proc-reuse-status',
  'proc-reuse-prepare', 'p-autopub-enabled', 'step1-autopub-toggle']) elements[id] = {};
elements['proc-reuse-video'].value = 'video.mp4';
elements['proc-reuse-ass'].value = 'voice_sync.ass';
let uploaded = 0, analyzed = 0, fail = false;
const sandbox = {
  window: {}, document: {getElementById: id => elements[id]},
  fetch: async (url, options) => {
    assert.equal(url, '/api/proc_read_ass');
    assert.equal(JSON.parse(options.body).path, 'voice_sync.ass');
    return {ok: true, json: async () => ({content: 'correct ASS'})};
  },
  pPubAnalyzeFromAss: async (content, options) => {
    analyzed++;
    assert.equal(content, 'correct ASS');
    assert.equal(options.ignoreVideoAnalysis, true);
    return fail ? null : {title: 'Title'};
  },
  pPubAutoUploadAll: async path => {assert.equal(path, 'video.mp4'); uploaded++;},
};
vm.createContext(sandbox);
const source = fs.readFileSync('templates/pages/process/script.js', 'utf8');
vm.runInContext(source.slice(source.indexOf('async function procLoadReusableVideos()')), sandbox);
(async () => {
  await sandbox.procPrepareReusableVideo();
  assert.equal(analyzed, 1);
  assert.equal(uploaded, 0, 'preparation must not publish');
  assert.equal(elements['proc-reuse-video'].disabled, false);
  await sandbox.procPublishReusableVideo();
  assert.equal(uploaded, 1);
  fail = true;
  await sandbox.procPrepareReusableVideo();
  assert.equal(sandbox.window._procReusePrepared, null);
  await sandbox.procPublishReusableVideo();
  assert.equal(uploaded, 1, 'failed generation must not reuse stale metadata');
  console.log('Reusable video/ASS metadata and explicit publish flow passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
