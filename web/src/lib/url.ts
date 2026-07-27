// Files in public/ are not rewritten by the bundler, so anything referencing them by
// absolute path breaks when the site is served from a subpath. Route those through here.
const BASE = import.meta.env.BASE_URL;

export function asset(path: string): string {
  return `${BASE.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}
