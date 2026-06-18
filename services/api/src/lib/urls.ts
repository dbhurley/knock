// Canonical public-URL builders. Kept in one place so every surface that
// hands a client a link to the status page (the intake success response, the
// status response itself, and the planned status-change reminder email / PDF)
// produces a byte-identical string. CLAUDE.md describes status_url as "one
// source of truth"; this is where that single source actually lives, rather
// than each route re-deriving PUBLIC_BASE_URL + '/status?ref=…' on its own.

// Base URL of the public site, trailing-slash-normalized. Override with
// PUBLIC_BASE_URL if the public site ever moves off askknock.com.
export function publicBaseUrl(): string {
  return (process.env.PUBLIC_BASE_URL ?? 'https://askknock.com').replace(/\/+$/, '');
}

// Canonical deep-link back to the status surface for a given search number.
export function statusUrlFor(searchNumber: string): string {
  return `${publicBaseUrl()}/status?ref=${encodeURIComponent(searchNumber)}`;
}
