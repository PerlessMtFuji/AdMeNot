// Sąsiednie zdjęcia w podglądzie: pobrane i zdekodowane, zanim serwisant naciśnie strzałkę. Tylko w pamięci okna
// (serwer mediów ma `no-store`: pliki klienta nie trafiają do pamięci podręcznej na dysku).

interface Photo {
  ctl: AbortController;
  src: string | null;
  /** Żywy obraz trzyma zdekodowaną bitmapę: `<img>` z tym samym adresem pokazuje ją od razu. */
  image: HTMLImageElement | null;
}

export class PhotoPrefetch {
  private readonly items = new Map<string, Photo>();

  /** Adres `blob:` gotowego zdjęcia albo null. */
  get(url: string): string | null {
    return this.items.get(url)?.src ?? null;
  }

  /** Zostawia tylko `keep` i dopiero pobiera `wanted` (oba to adresy plików). */
  keep(keep: readonly string[], wanted: readonly string[]): void {
    const stay = new Set([...keep, ...wanted]);
    for (const url of [...this.items.keys()]) if (!stay.has(url)) this.drop(url);
    for (const url of wanted) if (!this.items.has(url)) void this.load(url);
  }

  /** Koniec podglądu: pobieranie przerwane, adresy `blob:` zwolnione. */
  clear(): void {
    for (const url of [...this.items.keys()]) this.drop(url);
  }

  private drop(url: string): void {
    const item = this.items.get(url);
    if (!item) return;
    item.ctl.abort();
    if (item.src) URL.revokeObjectURL(item.src);
    this.items.delete(url);
  }

  private async load(url: string): Promise<void> {
    const item: Photo = { ctl: new AbortController(), src: null, image: null };
    this.items.set(url, item);
    try {
      const r = await fetch(url, { signal: item.ctl.signal });
      if (!r.ok) throw new Error(`photo ${r.status}`);
      const blob = await r.blob();
      if (this.items.get(url) !== item) return;
      const src = URL.createObjectURL(blob);
      const image = new Image();
      image.src = src;
      item.image = image;
      await image.decode?.();
      if (this.items.get(url) === item) item.src = src;
      else URL.revokeObjectURL(src);
    } catch {
      // bez zapasu zdjęcie wczyta się zwykłą drogą, a przy następnym `keep` spróbujemy znowu
      if (this.items.get(url) === item) this.items.delete(url);
    }
  }
}
