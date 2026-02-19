import fs from "node:fs";
import path from "node:path";

const projectRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const sourceRoot = path.join(projectRoot, "src");
const allowedExtensions = new Set([".vue", ".css"]);

const checks = [
  {
    name: "non-token palette utility",
    regex: /\b(?:bg|text|border|ring|from|to|via)-(?:zinc|gray|slate|neutral|stone|white|black)(?:[-/][A-Za-z0-9_\-[\]./%]+)?\b/g,
  },
  {
    name: "dark mode utility variant",
    regex: /\bdark:[^\s"'`<>}]*/g,
  },
  {
    name: "inline hex color",
    regex: /#[0-9a-fA-F]{3,8}\b/g,
  },
];

function listFilesRecursively(dirPath) {
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const nextPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      files.push(...listFilesRecursively(nextPath));
      continue;
    }

    if (allowedExtensions.has(path.extname(nextPath))) {
      files.push(nextPath);
    }
  }

  return files;
}

function relativePath(filePath) {
  return path.relative(projectRoot, filePath).replaceAll(path.sep, "/");
}

function run() {
  const violations = [];
  const files = listFilesRecursively(sourceRoot);

  for (const filePath of files) {
    const content = fs.readFileSync(filePath, "utf8");
    const lines = content.split(/\r?\n/);

    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];

      for (const check of checks) {
        check.regex.lastIndex = 0;
        let match = check.regex.exec(line);
        while (match) {
          violations.push({
            filePath: relativePath(filePath),
            line: index + 1,
            check: check.name,
            value: match[0],
          });
          match = check.regex.exec(line);
        }
      }
    }
  }

  if (violations.length > 0) {
    console.error("Theme token policy violations found:\n");
    for (const violation of violations) {
      console.error(`${violation.filePath}:${violation.line} [${violation.check}] ${violation.value}`);
    }
    process.exit(1);
  }

  console.log(`Theme token policy passed for ${files.length} files.`);
}

run();
