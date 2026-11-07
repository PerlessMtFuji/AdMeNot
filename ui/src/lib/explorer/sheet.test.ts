import { expect, test } from 'vitest';
import type { EntryView } from '../types';
import { CELL, colName, colRange, columnWidths, findInBook, isSheet, offsets, toTsv } from './sheet';

test('column names like a spreadsheet', () => {
  expect([0, 1, 25, 26, 27, 51, 52, 701].map(colName)).toEqual(['A', 'B', 'Z', 'AA', 'AB', 'AZ', 'BA', 'ZZ']);
});

test('sheet files by extension, folders never', () => {
  const e = (ext: string, kind: 'file' | 'dir' = 'file') => ({ ext, kind }) as EntryView;
  expect(['xlsx', 'XLSM', 'xls', 'csv', 'tsv'].map((x) => isSheet(e(x)))).toEqual([true, true, true, true, true]);
  expect(isSheet(e('ods'))).toBe(false);
  expect(isSheet(e('csv', 'dir'))).toBe(false);
});

test('finds cells across sheets, literal, case-insensitive, whole words', () => {
  const book = [
    { rows: [['Łódź', 'x'], ['', 'ŁÓDŹ Kaliska']] },
    { rows: [] },
    { rows: [['łódźka', 'a.b', 'axb']] },
  ];
  expect(findInBook(book, 'łódź')).toEqual([
    { sheet: 0, row: 0, col: 0 }, { sheet: 0, row: 1, col: 1 }, { sheet: 2, row: 0, col: 0 }]);
  expect(findInBook(book, 'łódź', true)).toHaveLength(2);
  expect(findInBook(book, 'a.b')).toEqual([{ sheet: 2, row: 0, col: 1 }]);
  expect(findInBook(book, '')).toEqual([]);
  expect(findInBook([{ rows: [Array(50).fill('a')] }], 'a', false, 10)).toHaveLength(10);
});

test('TSV quotes only cells that need it', () => {
  expect(toTsv([['a', 'b\tc'], ['"x"', 'd\ne']])).toBe('a\t"b\tc"\r\n"""x"""\t"d\ne"');
});

test('column widths from the longest first line, clamped', () => {
  const w = columnWidths([['a', 'x'.repeat(200), 'długa wartość\nx'], ['', '', '', 'd']]);
  expect(w).toHaveLength(4);
  expect(w[0]).toBe(CELL.min);
  expect(w[1]).toBe(CELL.max);
  expect(w[2]).toBe(Math.round(13 * CELL.char + CELL.pad));
});

test('visible column range with one spare on each side', () => {
  const edges = offsets([100, 100, 100, 100, 100]);
  expect(edges).toEqual([0, 100, 200, 300, 400, 500]);
  expect(colRange(edges, 0, 150)).toEqual([0, 3]);
  expect(colRange(edges, 250, 100)).toEqual([1, 5]);
  expect(colRange(edges, 1000, 100)).toEqual([4, 5]);
  expect(colRange([0], 0, 100)).toEqual([0, 0]);
});
