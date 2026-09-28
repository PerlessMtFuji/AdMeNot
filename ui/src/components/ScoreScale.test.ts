import { render } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import ScoreScale from './ScoreScale.svelte';

test('score scale: a high score without a malicious verdict does not show the "Szkodliwa" band', () => {
  const { queryByText, getAllByText } = render(ScoreScale, { props: { score: 100, verdict: 'suspicious' } });
  expect(queryByText('szkodliwa')).toBeNull();
  expect(getAllByText('podejrzana').length).toBe(2); // pasma 50-75 i 75-100 łączą się w jedno
});

test('score scale: a malicious verdict keeps the distinct "Szkodliwa" band', () => {
  const { getByText } = render(ScoreScale, { props: { score: 100, verdict: 'malicious' } });
  expect(getByText('szkodliwa')).toBeTruthy();
});
