import { render, screen } from '@testing-library/svelte';
import { describe, expect, test } from 'vitest';
import DropZone from './DropZone.svelte';

describe('DropZone', () => {
  test('shows count, size, destination and the free space of the phone', () => {
    render(DropZone, { props: { drop: { count: 3, bytes: 5 * 1024 ** 2, dropped: false }, folder: 'Camera', free: 12 * 1024 ** 3 } });
    expect(screen.getByText('Upuść, żeby wgrać do Camera')).toBeTruthy();
    expect(screen.getByText(/3 elementy · 5 MB · wolne miejsce: 12 GB/)).toBeTruthy();
  });

  test('without storage data the free space is left out', () => {
    render(DropZone, { props: { drop: { count: 1, bytes: null, dropped: true }, folder: 'Camera', free: null } });
    expect(screen.queryByText(/wolne miejsce/)).toBeNull();
  });
});
