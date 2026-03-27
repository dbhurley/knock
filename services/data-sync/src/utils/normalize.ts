/**
 * Normalization and fuzzy-matching utilities for the Knock data pipeline.
 */

/**
 * Normalize a name: lowercase, remove diacritics/accents, strip non-alpha chars
 * except spaces, and collapse whitespace.
 */
export function normalizeName(name: string | null | undefined): string {
  if (!name) return '';
  return name
    .normalize('NFD')                       // decompose accents
    .replace(/[\u0300-\u036f]/g, '')        // strip combining marks
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, '')            // strip punctuation
    .replace(/\s+/g, ' ')                   // collapse whitespace
    .trim();
}

/**
 * Normalize a US phone number to E.164-ish 10-digit format.
 * Returns digits only (e.g. "2125551234") or empty string.
 */
export function normalizePhone(phone: string | null | undefined): string {
  if (!phone) return '';
  const digits = phone.replace(/\D/g, '');
  // If 11 digits and starts with 1, strip leading 1
  if (digits.length === 11 && digits.startsWith('1')) {
    return digits.slice(1);
  }
  if (digits.length === 10) {
    return digits;
  }
  // Return whatever we got; caller can decide if it's valid
  return digits;
}

/**
 * Normalize a US street address for comparison.
 * Lowercases, expands common abbreviations, strips unit/suite info.
 */
export function normalizeAddress(address: string | null | undefined): string {
  if (!address) return '';

  let normalized = address
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();

  // Expand common abbreviations
  const abbrevs: Record<string, string> = {
    'st\\.?': 'street',
    'ave\\.?': 'avenue',
    'blvd\\.?': 'boulevard',
    'dr\\.?': 'drive',
    'ln\\.?': 'lane',
    'rd\\.?': 'road',
    'ct\\.?': 'court',
    'pl\\.?': 'place',
    'cir\\.?': 'circle',
    'pkwy\\.?': 'parkway',
    'hwy\\.?': 'highway',
    'n\\.?': 'north',
    's\\.?': 'south',
    'e\\.?': 'east',
    'w\\.?': 'west',
  };

  for (const [pattern, replacement] of Object.entries(abbrevs)) {
    normalized = normalized.replace(
      new RegExp(`\\b${pattern}\\b`, 'g'),
      replacement,
    );
  }

  // Strip apartment / suite / unit designations
  normalized = normalized.replace(
    /\b(apt|suite|ste|unit|#)\s*[\w-]+$/i,
    '',
  );

  return normalized.replace(/\s+/g, ' ').trim();
}

/**
 * Compute Levenshtein distance between two strings.
 */
export function levenshtein(a: string, b: string): number {
  const la = a.length;
  const lb = b.length;

  if (la === 0) return lb;
  if (lb === 0) return la;

  // Use two-row approach for memory efficiency
  let prev = Array.from({ length: lb + 1 }, (_, i) => i);
  let curr = new Array<number>(lb + 1);

  for (let i = 1; i <= la; i++) {
    curr[0] = i;
    for (let j = 1; j <= lb; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      curr[j] = Math.min(
        prev[j] + 1,       // deletion
        curr[j - 1] + 1,   // insertion
        prev[j - 1] + cost, // substitution
      );
    }
    [prev, curr] = [curr, prev];
  }
  return prev[lb];
}

/**
 * Compute similarity ratio between two strings (0..1, 1 = identical).
 * Uses normalized Levenshtein distance.
 */
export function similarity(a: string, b: string): number {
  const na = normalizeName(a);
  const nb = normalizeName(b);
  if (na === nb) return 1;
  const maxLen = Math.max(na.length, nb.length);
  if (maxLen === 0) return 1;
  return 1 - levenshtein(na, nb) / maxLen;
}

/**
 * Check if two strings are a fuzzy match above a given threshold.
 */
export function fuzzyMatch(
  a: string,
  b: string,
  threshold = 0.7,
): boolean {
  return similarity(a, b) >= threshold;
}

/**
 * Normalize email to lowercase, trim whitespace.
 */
export function normalizeEmail(email: string | null | undefined): string {
  if (!email) return '';
  return email.toLowerCase().trim();
}

/**
 * Normalize a ZIP code: keep first 5 digits.
 */
export function normalizeZip(zip: string | null | undefined): string {
  if (!zip) return '';
  const digits = zip.replace(/\D/g, '');
  return digits.slice(0, 5);
}

/**
 * Normalize state abbreviation to uppercase 2-letter code.
 */
export function normalizeState(state: string | null | undefined): string {
  if (!state) return '';
  return state.trim().toUpperCase().slice(0, 2);
}
