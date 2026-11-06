import { expect, test } from 'vitest';
import { findMatches } from './find';

test('stops at the match limit instead of building a huge list', () => {
  expect(findMatches('a'.repeat(50), 'a', false, 10)).toHaveLength(10);
});

test('literal case-insensitive search with Polish whole-word boundaries', () => {
  const text = 'ŻÓŁĆ żółć żółci [x] a.b 😀żółć';
  expect(findMatches(text, 'żółć', true)).toHaveLength(3);
  expect(findMatches(text, '[x]')).toEqual([{ start: 16, end: 19 }]);
  expect(findMatches('a.b axb', 'a.b')).toEqual([{ start: 0, end: 3 }]);
  expect(findMatches(text, '')).toEqual([]);
});
