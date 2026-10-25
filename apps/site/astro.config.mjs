// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import version from "./src/generated/version.json";

// Docs are versioned with the repo: the generator pins the release these
// pages were built from (latest `v*` git tag, or `edge` from a checkout).
const release = /** @type {{ version: string }} */ (version).version;

/** @type {import('@astrojs/starlight').StarlightUserConfig['sidebar']} */
const sidebar = [
    {
        label: "Get started",
        items: [
            "docs/get-started/quickstart",
            "docs/get-started/install",
            "docs/get-started/first-sandbox",
            "docs/get-started/mcp",
        ],
    },
    {
        label: "Guides",
        items: [
            "docs/guides/remote-servers",
            "docs/guides/macos",
            "docs/guides/windows",
            "docs/guides/policies",
            "docs/guides/vault-and-profiles",
            "docs/guides/domain-https-backups",
            "docs/guides/upgrading",
            "docs/guides/kubernetes",
            "docs/guides/building-on-zoo",
        ],
    },
    {
        label: "Concepts",
        items: ["docs/concepts/architecture", "docs/concepts/security-model", "docs/concepts/runtimes"],
    },
    {
        label: "Reference",
        items: [
            "docs/reference/conventions",
            "docs/reference/api",
            "docs/reference/tools",
            "docs/reference/sdk",
            "docs/reference/cli",
            "docs/reference/configuration",
            "docs/reference/errors",
            "docs/reference/performance",
        ],
    },
];

// The generated Reference pages carry the release they were generated from.
for (const group of sidebar) {
    if (group.label === "Reference") {
        // @ts-expect-error augmenting the group with a generated badge
        group.badge = { text: release, variant: "note" };
    }
}

// Code blocks match the landing page's terminal windows: warm dark screen,
// paper text, park-yellow keywords. A single dark theme keeps every block
// terminal-dark while the page around it is light paper.
const zooTerminal = {
    name: "zoo-terminal",
    type: "dark",
    appearance: "dark",
    colors: {
        "editor.background": "#26231f",
        "editor.foreground": "#ece6da",
        "selection.background": "#f7cb47",
        "editor.lineHighlightBackground": "#312d2880",
        "editorLineNumber.foreground": "#9a9284",
    },
    tokenColors: [
        { scope: ["comment", "punctuation.definition.comment"], settings: { foreground: "#9a9284", fontStyle: "italic" } },
        { scope: ["string", "punctuation.definition.string", "string.quoted"], settings: { foreground: "#a8bf6d" } },
        { scope: ["keyword", "keyword.control", "storage.type", "storage.modifier", "support.type"], settings: { foreground: "#e9b52a" } },
        { scope: ["entity.name.function", "support.function", "meta.function-call", "variable.function"], settings: { foreground: "#7fb3c4" } },
        { scope: ["constant", "constant.numeric", "constant.language", "constant.character"], settings: { foreground: "#d6b67e" } },
        { scope: ["entity.name.type", "entity.name.class", "support.class", "entity.name.tag"], settings: { foreground: "#d6b67e" } },
        { scope: ["variable.parameter", "meta.parameter"], settings: { foreground: "#cbb98f" } },
        { scope: ["punctuation"], settings: { foreground: "#c9c2b4" } },
    ],
};

export default defineConfig({
    devToolbar: { enabled: false },
    integrations: [
        starlight({
            title: "Zoo",
            description: "Self-hosted sandboxes for AI agents.",
            logo: { src: "./src/assets/zoo-mark.png" },
            favicon: "/favicon.png",
            social: [{ icon: "github", label: "GitHub", href: "https://github.com/chann44/zoo" }],
            customCss: [
                "@fontsource-variable/archivo",
                "@fontsource/fragment-mono",
                "@fontsource/silkscreen/400.css",
                "./src/styles/docs.css",
            ],
            expressiveCode: { themes: [zooTerminal] },
            editLink: {
                baseUrl: "https://github.com/chann44/zoo/edit/main/apps/site/",
            },
            lastUpdated: true,
            sidebar,
        }),
    ],
});
