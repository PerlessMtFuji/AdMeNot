import { afterEach, describe, expect, test, vi } from 'vitest';
import { zoomDirection, zoomRun, zoomSnapshot } from './zoom';

function scene() {
  const host = document.createElement('section');
  const stage = document.createElement('div');
  stage.innerHTML = '<p>stara zawartość</p>';
  host.append(stage);
  document.body.append(host);
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  const animate = vi.fn(() => ({ onfinish: null, oncancel: null, cancel: vi.fn() }));
  Object.assign(stage, { animate });
  return { host, stage, animate };
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

describe('folder zoom', () => {
  test('going deeper zooms in, going up zooms out', () => {
    expect(zoomDirection('/sdcard', '/sdcard/DCIM')).toBe('in');
    expect(zoomDirection('/sdcard/DCIM/Camera', '/sdcard/DCIM')).toBe('out');
    expect(zoomDirection('/sdcard/Music', '/sdcard/Download')).toBe('in');
  });

  test('zoom in: the old content grows to 2.4 and fades with blur(4px), the new one starts at .6; 450 ms', () => {
    const { host, stage, animate } = scene();
    const ghostAnimate = vi.fn(() => ({ onfinish: null, oncancel: null }));
    const zoom = zoomSnapshot(host, stage, '/sdcard', '/sdcard/DCIM', { x: 40, y: 20 })!;
    Object.assign(zoom.ghost, { animate: ghostAnimate });
    expect(zoom.ghost.textContent).toBe('stara zawartość');
    expect(zoom.ghost.getAttribute('aria-hidden')).toBe('true');
    expect(zoom.origin).toBe('40px 20px');
    zoomRun(stage, zoom);
    const [oldFrames, oldOptions] = ghostAnimate.mock.calls[0] as unknown as [Keyframe[], KeyframeAnimationOptions];
    expect(oldFrames[1]).toEqual({ transform: 'scale(2.4)', opacity: 0, filter: 'blur(4px)' });
    expect(oldOptions.duration).toBe(450);
    const [newFrames] = animate.mock.calls[0] as unknown as [Keyframe[]];
    expect(newFrames[0]).toEqual({ transform: 'scale(0.6)', opacity: 0, filter: 'blur(4px)' });
    expect(newFrames[1]).toEqual({ transform: 'scale(1)', opacity: 1, filter: 'blur(0px)' });
  });

  test('zoom out reverses it and starts from the centre', () => {
    const { host, stage, animate } = scene();
    const zoom = zoomSnapshot(host, stage, '/sdcard/DCIM', '/sdcard', { x: 40, y: 20 })!;
    Object.assign(zoom.ghost, { animate: vi.fn(() => ({})) });
    zoomRun(stage, zoom);
    expect(zoom.dir).toBe('out');
    expect((animate.mock.calls[0] as unknown as [Keyframe[]])[0][0]).toMatchObject({ transform: 'scale(2.4)' });
    expect((zoom.ghost.animate as ReturnType<typeof vi.fn>).mock.calls[0][0][1]).toMatchObject({ transform: 'scale(0.6)' });
  });

  test('reduced motion: no snapshot, the content just changes', () => {
    const { host, stage } = scene();
    vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
    expect(zoomSnapshot(host, stage, '/sdcard', '/sdcard/DCIM', null)).toBeNull();
    expect(host.children).toHaveLength(1);
  });
});
