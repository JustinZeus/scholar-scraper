const COLOR_SCALE_STEPS = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"];

function cssColorScale(token) {
  return Object.fromEntries(
    COLOR_SCALE_STEPS.map((step) => [step, `rgb(var(--color-${token}-${step}) / <alpha-value>)`]),
  );
}

function cssToken(token) {
  return `rgb(var(--theme-${token}) / <alpha-value>)`;
}

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{vue,ts,tsx,js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Manrope", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Space Grotesk", "Manrope", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        panel: "0 10px 30px -20px rgba(8, 15, 30, 0.45)",
      },
      colors: {
        brand: cssColorScale("brand"),
        info: cssColorScale("info"),
        success: cssColorScale("success"),
        warning: cssColorScale("warning"),
        danger: cssColorScale("danger"),
        surface: {
          app: cssToken("surface-app"),
          nav: cssToken("surface-nav"),
          "nav-active": cssToken("surface-nav-active"),
          card: cssToken("surface-card"),
          "card-muted": cssToken("surface-card-muted"),
          table: cssToken("surface-table"),
          "table-header": cssToken("surface-table-header"),
          input: cssToken("surface-input"),
          overlay: cssToken("surface-overlay"),
        },
        ink: {
          primary: cssToken("text-primary"),
          secondary: cssToken("text-secondary"),
          muted: cssToken("text-muted"),
          inverse: cssToken("text-inverse"),
          link: cssToken("text-link"),
        },
        stroke: {
          default: cssToken("border-default"),
          strong: cssToken("border-strong"),
          subtle: cssToken("border-subtle"),
          interactive: cssToken("border-interactive"),
        },
        focus: {
          ring: cssToken("focus-ring"),
          offset: cssToken("focus-ring-offset"),
        },
        action: {
          primary: {
            bg: cssToken("action-primary-bg"),
            border: cssToken("action-primary-border"),
            text: cssToken("action-primary-text"),
            "hover-bg": cssToken("action-primary-hover-bg"),
            "hover-border": cssToken("action-primary-hover-border"),
            "hover-text": cssToken("action-primary-hover-text"),
          },
          secondary: {
            bg: cssToken("action-secondary-bg"),
            border: cssToken("action-secondary-border"),
            text: cssToken("action-secondary-text"),
            "hover-bg": cssToken("action-secondary-hover-bg"),
            "hover-border": cssToken("action-secondary-hover-border"),
            "hover-text": cssToken("action-secondary-hover-text"),
          },
          ghost: {
            bg: cssToken("action-ghost-bg"),
            border: cssToken("action-ghost-border"),
            text: cssToken("action-ghost-text"),
            "hover-bg": cssToken("action-ghost-hover-bg"),
            "hover-border": cssToken("action-ghost-hover-border"),
            "hover-text": cssToken("action-ghost-hover-text"),
          },
          danger: {
            bg: cssToken("action-danger-bg"),
            border: cssToken("action-danger-border"),
            text: cssToken("action-danger-text"),
            "hover-bg": cssToken("action-danger-hover-bg"),
            "hover-border": cssToken("action-danger-hover-border"),
            "hover-text": cssToken("action-danger-hover-text"),
          },
        },
        state: {
          info: {
            bg: cssToken("state-info-bg"),
            border: cssToken("state-info-border"),
            text: cssToken("state-info-text"),
          },
          success: {
            bg: cssToken("state-success-bg"),
            border: cssToken("state-success-border"),
            text: cssToken("state-success-text"),
          },
          warning: {
            bg: cssToken("state-warning-bg"),
            border: cssToken("state-warning-border"),
            text: cssToken("state-warning-text"),
          },
          danger: {
            bg: cssToken("state-danger-bg"),
            border: cssToken("state-danger-border"),
            text: cssToken("state-danger-text"),
          },
        },
      },
    },
  },
  plugins: [],
};
