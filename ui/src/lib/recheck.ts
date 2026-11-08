/** Co ile ms program sam sprawdza, czy serwisant załatwił rzecz na telefonie (zamiast przycisku „Sprawdź ponownie”). */
export const RECHECK_MS = 5000;

/** Wywołuje `fn` co `ms`, gdy `active()` jest prawdą (np. rozwinięcie jest widoczne). Następne wywołanie
 *  jest planowane dopiero po zakończeniu poprzedniego, więc dwa nigdy nie idą naraz. Błąd `fn` nie
 *  zatrzymuje sprawdzania. Zwraca funkcję zatrzymującą (także sprawdzenie w toku nie planuje kolejnego). */
export function recheck(fn: () => Promise<unknown>, active: () => boolean, ms = RECHECK_MS): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const tick = async () => {
    if (stopped) return;
    if (active()) {
      try {
        await fn();
      } catch {
        // kolejna próba za `ms`
      }
    }
    if (!stopped) timer = setTimeout(tick, ms);
  };
  timer = setTimeout(tick, ms);
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}
