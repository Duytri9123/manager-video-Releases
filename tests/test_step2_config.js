const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('templates/pages/process/script.js', 'utf8');
const collector = source.slice(source.indexOf('function collectProcessConfig('), source.indexOf('function _startProcessVideoInternal'));
const elements = {
  'proc-vol-orig': {value: '0'},
  'frame-enabled': {checked: true},
  'frame-title-enabled': {checked: false},
  'frame-logo-path': {value: 'logo.png', dataset: {serverPath: '/test/logo.png'}},
  'frame-logo-size': {value: '0'},
  'frame-logo-start': {value: '1.5'},
  'frame-logo-end': {value: '8.5'},
  'proc-preview-aspect': {value: '16x9'},
};
const sandbox = {
  document: {getElementById: id => elements[id], querySelector: () => null},
  window: {_procExtAudios: [{path: '/music.wav', vol: .25}], _procMode: 'ai'},
  _getProcessModel: () => 'test-model', _getProcessProvider: () => 'test-provider',
  _isProcTranslateSubsEnabled: () => false, _isProcVoiceConvertEnabled: () => false,
  _resolveTtsEngineVoice: () => ({tts_engine: 'vieneu'}), _sanitizeVoiceParam: value => value,
};
vm.createContext(sandbox);
vm.runInContext(collector, sandbox);
let config = sandbox.collectProcessConfig();
assert.equal(config.vol_orig, 0);
assert.equal(config.bg_volume, 0);
assert.equal(config.keep_bg_music, false);
assert.equal(config.frame_title_enabled, false);
assert.equal(config.frame_logo_size_pct, 0);
assert.equal(config.frame_logo_start_sec, 1.5);
assert.equal(config.frame_logo_end_sec, 8.5);
assert.equal(config.frame_logo_path, '/test/logo.png');
assert.equal(config.target_aspect, '16x9');
assert.equal(config.ext_audios[0].vol, .25);
elements['proc-vol-orig'].value = '200';
config = sandbox.collectProcessConfig();
assert.equal(config.vol_orig, 2);
assert.equal(config.bg_volume, 2);
assert.equal(config.keep_bg_music, true);
const profiles = fs.readFileSync('static/js/process/process-presets.js', 'utf8');
vm.runInContext(profiles.slice(profiles.indexOf('window.collectProfileProcessConfig =')), sandbox);
const original = JSON.stringify(elements);
const converted = sandbox.window.collectProfileProcessConfig({aspect:'9x16', settings:{'proc-vol-orig':'30', 'frame-title-enabled':true}});
assert.equal(converted.vol_orig, .3);
assert.equal(converted.target_aspect, '9x16');
assert.equal(JSON.stringify(elements), original, 'collecting a preset must not alter the editor');
const snapshot = {vol_orig: 0, frame_title_enabled: false};
const cloned = sandbox.window.collectProfileProcessConfig({processing:snapshot});
cloned.vol_orig = 1;
assert.equal(snapshot.vol_orig, 0);
console.log('Step 2 config regressions passed');
elements['frame-title'] = {value: '', dataset: {aiTitle: 'Tiêu đề video trước'}};
sandbox.window._procUseAiAnalysis = true;
sandbox.window._procVideoAiAnalysis = {video_path:'old.mp4', result:{title_suggestions:{short:'Tiêu đề cũ'}}};
config = sandbox.collectProcessConfig('new.mp4');
assert.equal(config.frame_title, '');
assert.equal(config.frame_title_auto, true);
assert.equal(config.ai_video_analysis, null);
elements['frame-title'].value = 'Tiêu đề video trước';
assert.equal(sandbox.collectProcessConfig('new.mp4').frame_title, '');
elements['frame-title'].value = 'Tiêu đề nhập tay';
assert.equal(sandbox.collectProcessConfig('new.mp4').frame_title, 'Tiêu đề nhập tay');
assert.equal(sandbox.collectProcessConfig('new.mp4').frame_title_auto, false);
console.log('Per-video automatic titles do not leak to the next video');

elements['proc-content-aspect'] = {value:'3x4'};
elements['proc-mask-mode'] = {value:'patch'};
elements['proc-mask-source-x'] = {value:'0'};
elements['proc-mask-source-y'] = {value:'75'};
config = sandbox.collectProcessConfig();
assert.equal(config.content_aspect, '3x4');
assert.equal(config.mask_config.mode, 'patch');
assert.equal(config.mask_config.source_x, 0);
assert.equal(config.mask_config.source_y, .75);
console.log('Inner aspect and sample region config passed');
