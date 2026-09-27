const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let time = 2;
const rendered = [];
const sandbox = {
  window: {},
  document: {getElementById: () => ({value: time}), addEventListener: () => {}},
  _roundRect: () => {}, _drawCanvasSelection: () => {},
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/js/process/process-overlays.js', 'utf8'), sandbox);
sandbox.window._videoOverlays = [{id: 'text', type: 'text', text: 'Chữ trong preview',
  start_sec: 1, end_sec: 3, enabled: true}];
const ctx = {save() {}, restore() {}, measureText: text => ({width: text.length * 8}),
  fillText: text => rendered.push(text), beginPath() {}, fill() {}};
sandbox._drawVideoOverlaysOnCanvas(ctx, 0, 0, 500, 800);
assert.deepEqual(rendered, ['Chữ trong preview']);
assert.ok(sandbox.window._lastCanvasOverlayBoxes.text.w > 0);
time = 5;
sandbox._drawVideoOverlaysOnCanvas(ctx, 0, 0, 500, 800);
assert.equal(Object.keys(sandbox.window._lastCanvasOverlayBoxes).length, 0);
assert.equal(rendered.length, 1);
console.log('Text canvas rendering and timed hitboxes passed');
