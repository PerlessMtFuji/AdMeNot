import { describe, expect, it } from 'vitest';
import { highlight } from './highlight';
import { rowAt, rowSegments, textRows, tokenStarts } from './textrows';

const plain = (text: string) => [{ cls: '', text }];
const rendered = (text: string, limit?: number) => {
  const rows = textRows(text, limit);
  const tokens = plain(text);
  return rowSegments(text, rows, tokens, tokenStarts(tokens), 0, rows.count, [], 0).map((s) => s.text).join('');
};

describe('textRows', () => {
  it('liczy linie jak edytor: końcowy \\n nie dodaje pustej linii, puste linie zostają', () => {
    expect(textRows('').count).toBe(0);
    expect(textRows('a').total).toBe(1);
    expect(textRows('a\n').total).toBe(1);
    expect(textRows('a\n\nb\n').total).toBe(3);
    expect(textRows('\n').total).toBe(1);
  });

  it('dzieli za długą linię, numer ma tylko pierwszy wiersz', () => {
    const rows = textRows('abcdefg\nh', 3);
    expect(rows.count).toBe(4);
    expect(Array.from(rows.lines.slice(0, 4))).toEqual([1, 0, 0, 2]);
    expect(rows.total).toBe(2);
    expect(rows.width).toBe(3);
  });

  it('rośnie ponad początkowy rozmiar', () => {
    const rows = textRows('x\n'.repeat(5000));
    expect(rows.count).toBe(5000);
    expect(rows.starts[4999]).toBe(9998);
  });

  it('znajduje wiersz po miejscu w tekście', () => {
    const rows = textRows('ab\ncd\nef');
    expect([0, 1, 2, 3, 5, 6, 7].map((o) => rowAt(rows, o))).toEqual([0, 0, 0, 1, 1, 2, 2]);
  });
});

describe('rowSegments', () => {
  it('oddaje cały tekst wiersz po wierszu', () => {
    expect(rendered('ab\n\ncd')).toBe('ab\n\ncd\n');
  });

  it('podział długiej linii nie gubi znaków', () => {
    expect(rendered('abcdefg', 3).replaceAll('\n', '')).toBe('abcdefg');
  });

  it('zachowuje kolory tokenów, także tych przez kilka wierszy', () => {
    const text = '<!-- a\nb --><x>';
    const tokens = highlight(text, 'xml');
    const rows = textRows(text);
    const out = rowSegments(text, rows, tokens, tokenStarts(tokens), 0, rows.count, [], 0);
    expect(out.filter((s) => s.text !== '\n').map((s) => [s.text, s.cls])).toEqual([
      ['<!-- a', 'tok-com'], ['b -->', 'tok-com'], ['<x', 'tok-tag'], ['>', 'tok-tag'],
    ]);
  });

  it('zaczyna od środka tekstu', () => {
    const text = 'aaa\nbbb\nccc';
    const rows = textRows(text);
    const tokens = plain(text);
    expect(rowSegments(text, rows, tokens, tokenStarts(tokens), 1, 2, [], 0).map((s) => s.text)).toEqual(['bbb', '\n']);
  });

  it('oznacza trafienia z ich numerem, także przecinające tokeny i wiersze', () => {
    const text = 'abc\ndef';
    const tokens = [{ cls: 'x', text: 'ab' }, { cls: 'y', text: 'c\ndef' }];
    const rows = textRows(text);
    const out = rowSegments(text, rows, tokens, tokenStarts(tokens), 0, rows.count, [{ start: 1, end: 5 }], 7);
    expect(out.map((s) => [s.text, s.cls, s.hit])).toEqual([
      ['a', 'x', -1], ['b', 'x', 7], ['c', 'y', 7], ['\n', '', -1], ['d', 'y', 7], ['ef', 'y', -1], ['\n', '', -1],
    ]);
  });

  it('pusty zakres to brak kawałków', () => {
    const rows = textRows('a');
    expect(rowSegments('a', rows, plain('a'), tokenStarts(plain('a')), 1, 1, [], 0)).toEqual([]);
  });
});
