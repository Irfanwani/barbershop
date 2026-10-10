/**
 * Class-name joining.
 *
 * NativeWind accepts a plain string, so this only has to concatenate and drop
 * falsy entries. It is here so `clsx` is not another dependency for six lines.
 */
export type ClassValue = string | number | null | undefined | false | ClassValue[];

export function cn(...values: ClassValue[]): string {
  const out: string[] = [];
  for (const value of values) {
    if (!value) continue;
    if (Array.isArray(value)) {
      const nested = cn(...value);
      if (nested) out.push(nested);
    } else {
      out.push(String(value));
    }
  }
  return out.join(' ');
}