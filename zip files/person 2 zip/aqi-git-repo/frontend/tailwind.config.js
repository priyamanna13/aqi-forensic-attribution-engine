/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Apple-grade premium dark obsidian variations
        obsidian: {
          DEFAULT: "#09090b", // Core background base
          panel: "rgba(20, 20, 25, 0.4)", // Ultra-thin frosted glass sidebar
          card: "rgba(255, 255, 255, 0.02)", // Seamless micro-information box
        }
      },
      backdropBlur: {
        xl: "24px",
        "2xl": "40px",
      }
    },
  },
  plugins: [],
}