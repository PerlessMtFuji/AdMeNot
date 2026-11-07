// Kolorowanie JSON i XML w podglądzie tekstu: lekki tokenizer (bez zależności). Zawsze zwraca tokeny,
// które sklejone dają dokładnie wejście; tekst niepoprawny (zepsuty JSON) wraca jako jeden zwykły token.
export type Token = { cls: string; text: string };

export type HighlightKind = 'json' | 'xml';

const JSON_TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b/g;
const XML_TOKEN = /(<!--[\s\S]*?-->)|(<\/?[\w:.-]+)|(\/?>)|([\w:.-]+)(\s*=\s*)("[^"]*"|'[^']*')|(<\?[\s\S]*?\?>)/g;

function plain(text: string): Token[] {
  return text ? [{ cls: '', text }] : [];
}

/** Dokłada tokeny wg grup dopasowania `[grupa, klasa]`; tekst między dopasowaniami zostaje zwykły. */
function scan(text: string, re: RegExp, classify: (m: RegExpExecArray) => Token[]): Token[] {
  const out: Token[] = [];
  let last = 0;
  re.lastIndex = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    out.push(...plain(text.slice(last, m.index)), ...classify(m));
    last = m.index + m[0].length;
  }
  out.push(...plain(text.slice(last)));
  return out;
}

function json(text: string): Token[] {
  try {
    JSON.parse(text);
  } catch {
    return plain(text);
  }
  return scan(text, JSON_TOKEN, (m) => {
    if (m[1] !== undefined) {
      return m[2] !== undefined
        ? [{ cls: 'tok-key', text: m[1] }, ...plain(m[2])]
        : [{ cls: 'tok-str', text: m[1] }];
    }
    return [{ cls: m[3] !== undefined ? 'tok-num' : 'tok-lit', text: m[0] }];
  });
}

function xml(text: string): Token[] {
  return scan(text, XML_TOKEN, (m) => {
    if (m[1] !== undefined) return [{ cls: 'tok-com', text: m[1] }];
    if (m[2] !== undefined || m[3] !== undefined) return [{ cls: 'tok-tag', text: m[0] }];
    if (m[4] !== undefined) return [{ cls: 'tok-attr', text: m[4] }, ...plain(m[5]), { cls: 'tok-val', text: m[6] }];
    return [{ cls: 'tok-com', text: m[0] }];  // <?xml … ?>
  });
}

export function highlight(text: string, kind: HighlightKind): Token[] {
  return kind === 'json' ? json(text) : xml(text);
}
