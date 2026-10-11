import { describe, expect, it } from "vitest";
import vector from "../../tests/fixtures/share_vector.json";
import { TEXTS, canInflate, decodeLocal, decryptShare, effect, initial, parseFragment } from "../public/plan.js";

const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

describe("plan.js", () => {
  it("rozpoznaje oba tryby i odrzuca resztę", () => {
    const id = "A".repeat(22), key = "k".repeat(43);
    expect(parseFragment(`#s.${id}.${key}`)).toEqual({ mode: "server", id, key });
    expect(parseFragment("#l.abc_-")).toEqual({ mode: "local", data: "abc_-" });
    for (const bad of ["", "#", "#s.krotki.k", "#x.abc", `#s.${id}.${key}.x`]) expect(parseFragment(bad)).toBeNull();
  });

  it("odszyfrowuje wektor z Pythona", async () => {
    expect(await decryptShare(bytes(vector.blob), vector.key)).toEqual(vector.payload);
  });

  it("odrzuca zły klucz i złą wersję", async () => {
    const other = "A".repeat(43);
    await expect(decryptShare(bytes(vector.blob), other)).rejects.toThrow();
    const wrong = bytes(vector.blob);
    wrong[0] = 2;
    await expect(decryptShare(wrong, vector.key)).rejects.toThrow();
  });

  it("dekoduje tryb lokalny z Pythona", async () => {
    expect(await decodeLocal(vector.local_fragment.slice(2))).toEqual(vector.local_payload);
  });

  it("tekst skutku zależy od akcji, blokady i Androida 13", () => {
    const t = TEXTS.pl;
    expect(effect({ n: "a", l: "silence" }, true, t)).toBe(
      "Zostaje na telefonie, ale nie będzie wyświetlać powiadomień ani okien nad innymi aplikacjami.");
    expect(effect({ n: "a", l: "silence" }, false, t)).toBe(
      "Zostaje na telefonie i nie będzie wyświetlać okien nad innymi aplikacjami. "
      + "Jej powiadomienia trzeba wyłączyć ręcznie w ustawieniach telefonu.");
    expect(effect({ n: "a", l: "disable" }, true, t)).toBe("Przestanie działać. Jej dane zostają na telefonie.");
    expect(effect({ n: "a", l: "remove" }, true, t)).toBe(
      "Zostanie usunięta razem ze swoimi danymi. Samą aplikację da się przywrócić.");
    expect(effect({ n: "a", l: "remove", b: 1 }, true, t)).toBe("Nie zostanie zmieniona.");
  });

  it("inicjał to cały pierwszy znak graficzny, także flaga i emoji złożone", () => {
    expect(initial("🇵🇱 Polska")).toBe("🇵🇱");
    expect(initial("👨‍👩‍👧 Rodzina")).toBe("👨‍👩‍👧");
    expect(initial("  ćma")).toBe("Ć");
    expect(initial("   ")).toBe("?");
  });

  it("rozpoznaje przeglądarkę bez rozpakowywania deflate-raw (Safari < 16.4, Chrome < 103)", () => {
    expect(canInflate(globalThis)).toBe(true);
    expect(canInflate({})).toBe(false);
    class Old { constructor(format: string) { if (format !== "gzip") throw new TypeError(format); } }
    expect(canInflate({ DecompressionStream: Old })).toBe(false);
  });

  it("oba języki mają te same klucze", () => {
    expect(Object.keys(TEXTS.en).sort()).toEqual(Object.keys(TEXTS.pl).sort());
  });
});
