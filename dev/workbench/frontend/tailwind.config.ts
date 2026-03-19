import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        sage: {
          50: "#f3f7f7",
          100: "#deeaeb",
          200: "#bfd4d7",
          300: "#97b7bd",
          400: "#6e99a2",
          500: "#517b86",
          600: "#40636d",
          700: "#36515a",
          800: "#30444b",
          900: "#2b3a40"
        },
        earth: {
          50: "#faf6f1",
          100: "#f1e8dc",
          200: "#e3d1bb",
          300: "#d3b293",
          400: "#c08d65",
          500: "#aa6f47",
          600: "#8f5d3d",
          700: "#744c35",
          800: "#603f30",
          900: "#51362a"
        }
      },
      fontFamily: {
        sans: ["Fira Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["Fira Code", "ui-monospace", "monospace"]
      },
      boxShadow: {
        soft: "0 16px 40px rgba(52, 65, 53, 0.08)"
      },
      borderRadius: {
        "4xl": "2rem"
      }
    }
  },
  plugins: [],
} satisfies Config;
