// @ts-check

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: "scholarr",
  tagline: "Self-hosted scholar tracking docs",
  favicon: "img/favicon.ico",

  url: "https://justinzeus.github.io",
  baseUrl: "/scholar-scraper/",

  organizationName: "JustinZeus",
  projectName: "scholar-scraper",

  onBrokenLinks: "throw",
  onBrokenMarkdownLinks: "warn",

  i18n: {
    defaultLocale: "en",
    locales: ["en"],
  },

  presets: [
    [
      "classic",
      {
        docs: {
          path: "../docs",
          routeBasePath: "/",
          sidebarPath: require.resolve("./sidebars.js"),
          editUrl: "https://github.com/JustinZeus/scholar-scraper/tree/main/",
        },
        blog: false,
        theme: {
          customCss: require.resolve("./src/css/custom.css"),
        },
      },
    ],
  ],

  themeConfig: {
    navbar: {
      title: "scholarr",
      items: [
        {
          type: "docSidebar",
          sidebarId: "docsSidebar",
          position: "left",
          label: "Docs",
        },
        {
          href: "https://github.com/JustinZeus/scholar-scraper",
          label: "GitHub",
          position: "right",
        },
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Docs",
          items: [{ label: "Index", to: "/" }],
        },
        {
          title: "Community",
          items: [
            {
              label: "GitHub",
              href: "https://github.com/JustinZeus/scholar-scraper",
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} scholarr.`,
    },
  },
};

module.exports = config;
