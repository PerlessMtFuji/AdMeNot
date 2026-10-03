// Renderuje SVG do PNG w zadanym rozmiarze (scripts/build_icons.py). Użycie: node render-icon.mjs <svg> <px> <png>
import { readFileSync, writeFileSync } from 'node:fs';
import { Resvg } from '@resvg/resvg-js';

const [src, size, out] = process.argv.slice(2);
const png = new Resvg(readFileSync(src), { fitTo: { mode: 'width', value: Number(size) } }).render().asPng();
writeFileSync(out, png);
