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
        // Scrollstory design system
        story: {
          dark: "#0a0a0a",
          light: "#ffffff",
          red: "#ef4444",
          green: "#16a34a",
          muted: "#888888",
        },
      },
      fontFamily: {
        sans: [
          "var(--font-plus-jakarta)",
          "'Plus Jakarta Sans'",
          "var(--font-inter)",
          "'Inter'",
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
        mono: ["var(--font-jetbrains-mono)", "var(--font-space-mono)", "ui-monospace", "monospace"],
        // Scrollstory body font
        story: ["var(--font-inter)", "Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;

