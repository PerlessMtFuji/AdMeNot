// Instrukcje włączenia debugowania USB według producenta (spec §9.2 ekran 1); teksty w i18n usb.*.
export const USB_GROUPS = ['samsung', 'xiaomi', 'motorola', 'oppo', 'huawei', 'pixel', 'other'] as const;
export type UsbGroup = (typeof USB_GROUPS)[number];

// Każdy krok ma w i18n usb.<grupa>.s<n>.act; tu są wymienione jego dodatkowe części.
// `optional` nie ma własnego tekstu — to plakietka connect.guide_optional.
export type UsbStepPart = 'path' | 'note' | 'cond' | 'optional';

export const USB_STEPS: Record<UsbGroup, UsbStepPart[][]> = {
  samsung: [['path'], ['note'], ['path', 'cond'], ['path'], ['note']],
  xiaomi: [['path'], ['note'], ['path'], ['path', 'note', 'optional'], ['note']],
  motorola: [['path'], ['note'], ['path'], ['note']],
  oppo: [['path'], ['note'], ['path'], ['path', 'note', 'optional'], ['note']],
  huawei: [['path'], ['note'], ['path'], ['note']],
  pixel: [['path'], ['note'], ['path'], ['note']],
  other: [['path', 'note'], ['note'], ['path', 'note'], ['note']],
};

export function guessUsbGroup(model: string | null): UsbGroup {
  const m = (model ?? '').toLowerCase();
  if (m.startsWith('sm_') || m.startsWith('sm-') || m.includes('galaxy')) return 'samsung';
  if (/redmi|poco|^m2\d|^2\d{3}|mi_/.test(m)) return 'xiaomi';
  if (m.includes('moto')) return 'motorola';
  if (/^cph|^rmx|oneplus|^ne2|^pj/.test(m)) return 'oppo';
  if (/huawei|honor|^[a-z]{3}_l\d/.test(m)) return 'huawei';
  if (m.includes('pixel')) return 'pixel';
  return 'other';
}
