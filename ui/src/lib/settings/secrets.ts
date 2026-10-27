const SECRET = /__SECRET__:([A-Za-z0-9_.-]+)/g;

export interface SecretSpan {
  from: number;
  to: number;
  name: string;
}

export function findSecrets(text: string): SecretSpan[] {
  const out: SecretSpan[] = [];
  const re = new RegExp(SECRET);
  let match: RegExpExecArray | null;
  while ((match = re.exec(text))) {
    out.push({ from: match.index, to: match.index + match[0].length, name: match[1] });
  }
  return out;
}

/** True when a change that replaces [from, to) would alter a masked secret. */
export function rangeHitsSecret(text: string, from: number, to: number): boolean {
  return findSecrets(text).some((span) => from < span.to && to > span.from);
}
