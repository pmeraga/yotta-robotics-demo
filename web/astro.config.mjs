import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

// GitHub Pages serves a project site from a subpath, so the base has to be injected at
// build time. Hosts that serve from the domain root (Vercel, Netlify) need no change.
const base = process.env.PUBLIC_BASE_PATH || "/";

export default defineConfig({
  site: process.env.PUBLIC_SITE_URL,
  base,
  vite: {
    plugins: [tailwindcss()],
  },
});
