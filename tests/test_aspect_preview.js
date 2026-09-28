const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/js/process/process-frame-editor.js', 'utf8');
const start = source.indexOf('function procParseContentAspect(');
const end = source.indexOf('function procContentAspectInput(', start);
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);

const inner = sandbox.procParseContentAspect('16:9');
assert.deepEqual(JSON.parse(JSON.stringify(sandbox.procOutputFrameSize('9x16', 1920, 1080, inner))),
  {width:1080, height:1920}, 'a selected portrait frame must not be overridden by its inner ratio');
assert.deepEqual(JSON.parse(JSON.stringify(sandbox.procOutputFrameSize('16x9', 1080, 1920, 3 / 4))),
  {width:1920, height:1080});
assert.deepEqual(JSON.parse(JSON.stringify(sandbox.procOutputFrameSize('auto', 240, 320, 1))),
  {width:240, height:240});
assert.equal(sandbox.procLogoVisibleAtTime('1.5', '8.5', 1), false);
assert.equal(sandbox.procLogoVisibleAtTime('1.5', '8.5', 2), true);
assert.equal(sandbox.procLogoVisibleAtTime('1.5', '8.5', 9), false);
console.log('Preview output frame ratios passed');
