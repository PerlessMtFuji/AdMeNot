import { expect, test } from 'vitest';
import { findMatches } from './find';

test('literal case-insensitive search with Polish whole-word boundaries', () => {
  const text = 'ŻÓŁĆ żółć żółci [x] a.b 😀żółć';
  expect(findMatches(text, 'żółć', true)).toHaveLength(3);
  expect(findMatches(text, '[x]')).toEqual([{ start: 16, end: 19 }]);
  expect(findMatches('a.b axb', 'a.b')).toEqual([{ start: 0, end: 3 }]);
  expect(findMatches(text, '')).toEqual([]);
});
