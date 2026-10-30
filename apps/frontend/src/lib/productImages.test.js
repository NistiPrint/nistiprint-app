import assert from 'node:assert/strict';
import test from 'node:test';
import { productImages } from './productImages.js';

test('normalizes imported URLs and ignores invalid or unsafe sources', () => {
  assert.deepEqual(productImages({ atributos: { images: [
    'https://example.com/a.jpg', { url: 'https://example.com/a.jpg' },
    { url: 'https://example.com/b.jpg' }, 'javascript:alert(1)',
    'https://user:password@example.com/private.jpg', null, 'invalid',
  ] } }), ['https://example.com/a.jpg', 'https://example.com/b.jpg']);
  assert.deepEqual(productImages({}), []);
});
