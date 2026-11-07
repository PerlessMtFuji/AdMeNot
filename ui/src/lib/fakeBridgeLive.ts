/** Atrapy mostu (`fakeBridge.ts`), które jeszcze mogą wysłać spóźnione zdarzenie (łańcuch `replay`, timery).
 *  Testy kończą je w `afterEach` (`test-setup.ts`), zanim jsdom zniknie — inaczej `dispatchEvent` po końcu
 *  pliku testów to „Unhandled Rejection”. Osobny moduł: konfiguracja testów nie wczytuje nagrań atrapy. */
export const live = new Set<() => void>();

/** Kończy wszystkie żywe atrapy (po każdym teście). */
export function disposeFakeBridges(): void {
  for (const dispose of [...live]) dispose();
}
