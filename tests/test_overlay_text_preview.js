const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let time = 2;
const rendered = [];
const sandbox = {
  window: {},
  document: {getElementById: id => id === 'pe2-video-player' ? null : ({value: time}), addEventListener: () => {}},
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

const editor = fs.readFileSync('static/js/process/process-frame-editor.js','utf8');
vm.runInContext(editor.slice(editor.indexOf('function ovUpdateLayer('), editor.indexOf("  window.addEventListener('resize'")), sandbox);
sandbox.ovUpdateLayer('text','text_opacity',.25,true);
assert.equal(sandbox.window._videoOverlays[0].text_opacity,.25);
time=2;
sandbox._drawVideoOverlaysOnCanvas(ctx,0,0,500,800);
assert.equal(ctx.globalAlpha,.25);
console.log('Text opacity editing and canvas alpha passed');

const diamond = {x_pct:.5,y_pct:.5,motion:'diamond',motion_amp_pct:1,motion_period_sec:4,start_sec:0};
for (const [second, expectedX, expectedY] of [[0,.5,.1],[1,.9,.5],[2,.5,.9],[3,.1,.5]]) {
  time = second;
  const point = sandbox._ovMotionPosition(diamond,.2,.2);
  assert.ok(Math.abs(point.x - expectedX) < 1e-6 && Math.abs(point.y - expectedY) < 1e-6);
}
console.log('Diamond text motion passed');
