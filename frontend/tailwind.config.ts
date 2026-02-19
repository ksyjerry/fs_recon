import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        "pwc-orange":    "var(--pwc-orange)",
        "pwc-orange-dk": "var(--pwc-orange-dk)",
        "pwc-red":       "var(--pwc-red)",
        "pwc-black":     "var(--pwc-black)",
        "pwc-grey": {
          90: "var(--pwc-grey-90)",
          70: "var(--pwc-grey-70)",
          20: "var(--pwc-grey-20)",
          5:  "var(--pwc-grey-05)",
        },
        "pwc-white":     "var(--pwc-white)",
        success:         "var(--color-success)",
        warning:         "var(--color-warning)",
        danger:          "var(--color-danger)",
      },
      fontFamily: {
        sans: ["var(--font-body)", "Helvetica Neue", "Helvetica", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;
