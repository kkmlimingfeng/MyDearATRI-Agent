import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeLive2dFolder } from './avatarImport.js';

test('normalizes a model folder into the pet live2d directory', () => {
  const files = [
    { file: 'model', path: 'Atri/model.model3.json' },
    { file: 'texture', path: 'Atri/textures/texture_00.png' },
  ];

  assert.deepEqual(normalizeLive2dFolder(files), [
    { file: 'model', path: 'live2d/model.model3.json' },
    { file: 'texture', path: 'live2d/textures/texture_00.png' },
  ]);
});

test('unwraps a model stored inside one live2d subdirectory', () => {
  const files = [
    { file: 'model', path: 'Atri/live2d/model.model3.json' },
    { file: 'texture', path: 'Atri/live2d/textures/texture_00.png' },
    { file: 'readme', path: 'Atri/README.txt' },
  ];

  assert.deepEqual(normalizeLive2dFolder(files), [
    { file: 'model', path: 'live2d/model.model3.json' },
    { file: 'texture', path: 'live2d/textures/texture_00.png' },
  ]);
});

test('rejects a collection folder and folders without a model3 file', () => {
  assert.equal(normalizeLive2dFolder([
    { file: 'first', path: 'collection/first/model.model3.json' },
    { file: 'second', path: 'collection/second/model.model3.json' },
  ]), null);
  assert.equal(normalizeLive2dFolder([
    { file: 'readme', path: 'model/README.txt' },
  ]), null);
});
