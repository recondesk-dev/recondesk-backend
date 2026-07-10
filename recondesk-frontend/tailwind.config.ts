import type { Config } from "tailwindcss";

import { brandColors } from "./lib/brand";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: brandColors.DEFAULT,
          hover: brandColors.hover,
          dim: brandColors.dim,
        },
        sidebar: "#0F1117",
      },
      fontFamily: {
        sans: [
          "var(--font-plus-jakarta)",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        brand: [
          "var(--font-plus-jakarta)",
          "system-ui",
          "sans-serif",
        ],
        mono: ["var(--font-space-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
