import { describe, expect, test } from 'vitest';
import { highlight } from './highlight';

const joined = (text: string, kind: 'json' | 'xml') => highlight(text, kind).map((t) => t.text).join('');
const find = (tokens: { cls: string; text: string }[], text: string) => tokens.find((t) => t.text === text);

describe('highlight', () => {
  test('JSON: keys, strings, numbers and literals get their own classes', () => {
    const tokens = highlight('{"imię": "Zażółć", "wiek": -12.5e2, "ok": true, "brak": null}', 'json');
    expect(find(tokens, '"imię"')?.cls).toBe('tok-key');
    expect(find(tokens, '"Zażółć"')?.cls).toBe('tok-str');
    expect(find(tokens, '-12.5e2')?.cls).toBe('tok-num');
    expect(find(tokens, 'true')?.cls).toBe('tok-lit');
    expect(find(tokens, 'null')?.cls).toBe('tok-lit');
  });

  test('JSON: a string containing a colon or an escaped quote stays one string token', () => {
    const tokens = highlight('{"a": "x: \\"y\\""}', 'json');
    expect(find(tokens, '"x: \\"y\\""')?.cls).toBe('tok-str');
    expect(find(tokens, '"a"')?.cls).toBe('tok-key');
  });

  test('JSON: tokens always add up to the original text, whitespace included', () => {
    const text = '{\n  "a": [1, 2, {"b": false}]\n}\n';
    expect(joined(text, 'json')).toBe(text);
  });

  test('broken JSON falls back to plain text', () => {
    const text = '{"a": 1,, nope';
    expect(highlight(text, 'json')).toEqual([{ cls: '', text }]);
  });

  test('XML: tags, attributes, values and comments', () => {
    const text = '<?xml version="1.0"?>\n<a id="7" b=\'x\'><!-- uwaga --><b/>tekst</a>';
    const tokens = highlight(text, 'xml');
    expect(joined(text, 'xml')).toBe(text);
    expect(find(tokens, '<a')?.cls).toBe('tok-tag');
    expect(find(tokens, '</a')?.cls).toBe('tok-tag');
    expect(find(tokens, 'id')?.cls).toBe('tok-attr');
    expect(find(tokens, '"7"')?.cls).toBe('tok-val');
    expect(find(tokens, "'x'")?.cls).toBe('tok-val');
    expect(find(tokens, '<!-- uwaga -->')?.cls).toBe('tok-com');
    expect(find(tokens, 'tekst')?.cls).toBe('');
  });

  test('empty input gives no tokens', () => {
    expect(highlight('', 'json')).toEqual([]);
    expect(highlight('', 'xml')).toEqual([]);
  });
});
