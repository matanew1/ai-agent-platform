/**
 * standard-version updater for pyproject.toml.
 *
 * standard-version bumps package.json out of the box; this project has no
 * package.json (it's a uv/Python workspace), so the canonical version lives
 * in pyproject.toml's [project] table instead. Without this, a release would
 * tag a new version while pyproject.toml still claimed the old one.
 *
 * Scoped deliberately to the FIRST `version = "..."` under [project]: the
 * file also carries version *constraints* for dependencies (`"fastapi>=0.115"`)
 * and a [tool.uv.sources] table, none of which should ever be rewritten.
 */

const VERSION_LINE = /^version\s*=\s*"([^"]+)"/m;

module.exports.readVersion = function (contents) {
  const match = contents.match(VERSION_LINE);
  if (!match) {
    throw new Error("pyproject.toml: no `version = \"...\"` line found");
  }
  return match[1];
};

module.exports.writeVersion = function (contents, version) {
  return contents.replace(VERSION_LINE, `version = "${version}"`);
};
