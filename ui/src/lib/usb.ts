// Instrukcje włączenia debugowania USB według producenta (spec §9.2 ekran 1); teksty w i18n usb.*.
export const USB_GROUPS = ['samsung', 'xiaomi', 'motorola', 'oppo', 'huawei', 'pixel', 'other'] as const;
export type UsbGroup = (typeof USB_GROUPS)[number];

export const USB_STEPS: Record<UsbGroup, number> = {
  samsung: 4, xiaomi: 5, motorola: 4, oppo: 5, huawei: 4, pixel: 4, other: 4,
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
