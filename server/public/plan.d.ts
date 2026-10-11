// Typy eksportów plan.js dla testów (server/test/plan-page.test.ts); plik nie jest publikowany (.assetsignore).
export interface PlanApp { n: string; l: "silence" | "disable" | "remove"; b?: number; i?: string | null }
export interface PlanPayload {
  v: number; lang: string; at: string; phone: string; code: string; notif: number; shop?: string; apps: PlanApp[];
}
export type PlanTexts = Record<string, string>;
export const TEXTS: Record<"pl" | "en", PlanTexts>;
export function parseFragment(hash: string):
  { mode: "server"; id: string; key: string } | { mode: "local"; data: string } | null;
export function decodeLocal(data: string): Promise<PlanPayload>;
export function decryptShare(blob: Uint8Array, key: string): Promise<PlanPayload>;
export function effect(app: { n: string; l: string; b?: number }, notif: boolean, t: PlanTexts, many?: boolean): string;
export interface PlanGroup { key: "remove" | "disable" | "silence" | "blocked"; title: string; text: string; apps: PlanApp[] }
export function groups(apps: PlanApp[], notif: boolean, t: PlanTexts, lang: string): PlanGroup[];
export function render(root: Element, payload: PlanPayload, mode: "server" | "local"): void;
export function canInflate(g: object): boolean;
export function initial(name: string): string;
