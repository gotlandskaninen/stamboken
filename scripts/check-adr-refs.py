#!/usr/bin/env python3
"""Check that code references in the ADRs exist in this checkout.

Every inline `code span` in docs/adr/*.md (outside fenced blocks) is
classified and checked against the repo:

- file paths         -> exist (relative to the repo, app/, next-app/, next-app/src/,
                        next-app/src/app/ or next-app/src/app/(app)/);
                        a bare file name must exist somewhere in the repo
- /api/... endpoints -> match a Flask route (herdbook.py + blueprints)
- other /paths       -> match a Next.js route, an nginx location or a Payload route
- --sb-* / .sb-*     -> defined in next-app/src/styles/tokens.css
- identifiers, env vars and literals such as url_prefix="/api"
                     -> occur somewhere in the code (docs/ and *.md excluded)

The URL namespace ADR must also list exactly the slugs in RESERVED_SLUGS and the
middleware matcher. Historical or hypothetical names belong in prose, not in
code spans. A decided but not yet built identifier is declared in the ADR with
`<!-- check-adr-refs: planned some_table some_column -->` and is skipped until
it appears in the code (then the comment is removed). GitHub repo names (gotlandskaninen/...) are skipped. Exit code 1
when anything is missing.

Usage: scripts/check-adr-refs.py [files...]   (default: docs/adr/0*.md)
"""

import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH_BASES = ["", "app/", "next-app/", "next-app/src/", "next-app/src/app/", "next-app/src/app/(app)/"]
FILE_EXT = re.compile(r"\.(py|pyx|ts|tsx|js|mjs|css|scss|md|ya?ml|sh|json|sql|conf|toml|txt)$")
VERSION = re.compile(r"^(v?\d+(\.\d+)*(-[\w.]+)?|-rc\.\d+)$")
METHOD = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) (/\S+)$")


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as f:
        return f.read()


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.split("\0") if f]


def code_corpus(files):
    out = []
    for rel in files:
        if rel.startswith("docs/") or rel.endswith(".md"):
            continue
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path) or os.path.islink(path) or os.path.getsize(path) > 2_000_000:
            continue
        out.append(read(rel))
    return "\n".join(out)


ROUTE = re.compile(r'@(\w+)\.route\(\s*"([^"]+)"(?:\s*,\s*methods\s*=\s*\[([^\]]*)\])?')


def flask_routes():
    """(path, methods) for every Flask route in herdbook.py and the blueprints."""
    routes = []
    blueprints = [os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "app/blueprints/*.py"))]
    for rel in ["app/herdbook.py", *blueprints]:
        src = read(rel)
        prefixes = dict(re.findall(r'(\w+)\s*=\s*Blueprint\([^)]*url_prefix="([^"]*)"', src))
        for bp, route, methods in ROUTE.findall(src):
            routes.append((prefixes.get(bp, "") + route, set(re.findall(r"\w+", methods)) or {"GET"}))
    return routes


def site_routes():
    """(exact, prefix) URL paths: Next.js routes (groups stripped), Payload routes,
    nginx `location =` (exact) and other nginx locations (prefix). nginx's
    catch-all `location /` is left out so it cannot validate arbitrary paths."""
    exact, prefix = set(), set()
    app_dir = os.path.join(ROOT, "next-app/src/app")
    for dirpath, _, _ in os.walk(app_dir):
        parts = [s for s in os.path.relpath(dirpath, app_dir).split(os.sep) if s != "." and not s.startswith("(")]
        if not any(s.startswith("_") for s in parts):
            exact.add("/" + "/".join(parts))
    for conf in glob.glob(os.path.join(ROOT, "nginx/production/*.conf")):
        for eq, loc in re.findall(r"^\s*location\s+(=?)\s*(/\S*)\s*\{", read(os.path.relpath(conf, ROOT)), re.M):
            (exact if eq else prefix).add(loc) if loc != "/" else None
    exact.update(re.findall(r'(?:admin|api|graphQL):\s*"(/[^"]+)"', read("next-app/src/payload.config.ts")))
    return exact, prefix


def segs(path):
    return [s for s in path.split("/") if s]


def is_var(seg):
    return bool(re.fullmatch(r"<[^>]*>|\[[^\]]*\]|\*|:path\*|…", seg))


def path_matches(ref, known, known_prefix=False):
    """True when the documented path `ref` is served by `known`.

    A placeholder in `ref` (`<x>`, `[x]`, `*`) matches any segment; a dynamic
    segment in `known` matches only a placeholder. A trailing `*` in `ref`
    covers the subtree and a `ref` ending in `/` is a prefix; `known_prefix`
    marks nginx prefix locations."""
    r, k = segs(ref), segs(known)
    for i, rs in enumerate(r):
        if i >= len(k):
            return known_prefix
        ks = k[i]
        if ks.startswith("[...") or ks.startswith("[[...") or (rs in ("*", ":path*") and i == len(r) - 1):
            return True  # catch-all route, or a trailing `*` covering the subtree
        if not (rs == ks or is_var(rs)):
            return False
    return len(r) == len(k) or ref.endswith("/")


def endpoint_matches(ref, route, method=None):
    path, methods = route
    return path_matches(ref, path) and (method is None or method in methods)


def check_file(ref, basenames):
    if "/" not in ref:
        return ref in basenames
    pattern = re.sub(r"<[^>]+>", "*", ref.rstrip("/")).replace("[", "[[]")
    return any(glob.glob(os.path.join(ROOT, glob.escape(base) + pattern)) for base in PATH_BASES)


def spans(md):
    text = re.sub(r"^```.*?^```", "", md, flags=re.S | re.M)
    return re.findall(r"`([^`\n]+)`", text)


def planned(md):
    """Identifiers the ADR declares as decided but not yet in the code."""
    return {w for m in re.findall(r"<!--\s*check-adr-refs:\s*planned\s+([^>]*?)-->", md) for w in m.split()}


def classify(span):
    s = span.strip().strip('"')
    if not s or VERSION.match(s) or re.fullmatch(r"gotlandskaninen/[\w.-]+", s):
        return None
    m = METHOD.match(s)
    if m:
        return ("endpoint", (m.group(2), m.group(1)))
    if " " in s:
        paths = [t for t in s.split() if "/" in t and FILE_EXT.search(t)]
        return ("file", paths[0]) if paths else None
    if s.startswith("/api/"):
        return ("endpoint", (s.split("?")[0], None))
    if s.startswith("/"):
        return ("site", s.split("?")[0])
    if "=" in s or "://" in s:
        return ("literal", s)
    if s.startswith("--sb-") or s.startswith(".sb-"):
        return ("token", s)
    if "/" in s or FILE_EXT.search(s):
        return ("file", s)
    ident = re.sub(r"<[^>]*>|\(.*?\)|^@", "", s).split(".")[-1]
    if re.fullmatch(r"[\w$-]+", ident) and not ident.isdigit():
        return ("ident", ident)
    return None


def token_defined(ref, tokens):
    """`--sb-x` / `.sb-x` must occur as a whole name; `--sb-*` is a prefix."""
    if ref.endswith("*"):
        return ref.rstrip("*") in tokens
    return re.search(r"(?<![\w-])" + re.escape(ref) + r"(?![\w-])", tokens) is not None


def in_code(text, corpus):
    return re.search(r"(?<![\w-])" + re.escape(text) + r"(?![\w-])", corpus) is not None


def check_url_namespace_adr():
    # globbed, not numbered, so ADR renumbering does not break the check
    (path,) = glob.glob(os.path.join(ROOT, "docs/adr/*-url-namespace-architecture.md"))
    rel = os.path.relpath(path, ROOT)
    adr = read(rel)
    blocks = re.findall(r"^```(\w*)\n(.*?)^```", adr, flags=re.S | re.M)
    code_slugs = set(re.findall(r'^\s*"([^"]+)",', read("next-app/src/hooks/validateSlug.ts"), re.M))
    slug_block = next((b for lang, b in blocks if lang == "text" and "admin," in b), "")
    doc_slugs = {s.strip() for s in slug_block.replace("\n", " ").split(",")}
    mw = read("next-app/src/middleware.ts")
    code_matcher = re.findall(r'"([^"]+)"', mw[mw.index("matcher:") :])
    doc_matcher = next((re.findall(r'"([^"]+)"', b) for _, b in blocks if "matcher" in b), [])
    out = []
    if code_slugs != doc_slugs:
        only_code, only_adr = sorted(code_slugs - doc_slugs), sorted(doc_slugs - code_slugs)
        out.append(f"{rel}: RESERVED_SLUGS differ: code-only {only_code}, adr-only {only_adr}")
    if code_matcher != doc_matcher:
        out.append(f"{rel}: middleware matcher differs: code {code_matcher}, adr {doc_matcher}")
    return out


# [ADR-NNNN …](…/NNNN-slug.md#anchor "title") and reference-style [ADR-NNNN]: …/NNNN-slug.md
ADR_LINKS = [
    re.compile(r'\[ADR-(\d{4})[^\]]*\]\((?:[^)\s]*/)?(\d{4})-[a-z0-9-]+\.md(?:#[^)\s]*)?(?:\s+"[^"]*")?\)'),
    re.compile(r"^\[ADR-(\d{4})[^\]]*\]:\s*(?:\S*/)?(\d{4})-[a-z0-9-]+\.md", re.M),
]


def adr_numbers_mismatch(text):
    """Links whose ADR-NNNN text names another number than the file they open."""
    return [m.group(0) for rx in ADR_LINKS for m in rx.finditer(text) if m.group(1) != m.group(2)]


def check_adr_numbers(files, tracked):
    out = []
    for path in files:
        rel = os.path.relpath(path, ROOT)
        title = re.match(r"# ADR-(\d{4})", read(rel))
        if title and title.group(1) != os.path.basename(path)[:4]:
            out.append(f"{rel}: title says ADR-{title.group(1)}")
    for rel in tracked:
        full = os.path.join(ROOT, rel)
        if rel.endswith(".md") and os.path.isfile(full) and not os.path.islink(full):
            out += [f"{rel}: link {link}" for link in adr_numbers_mismatch(read(rel))]
    return out


def main(argv):
    files = argv or sorted(glob.glob(os.path.join(ROOT, "docs/adr/0*.md")))
    files = [f for f in files if not f.endswith("0000-template.md")]
    tracked = tracked_files()
    basenames = {os.path.basename(f) for f in tracked}
    corpus = code_corpus(tracked)
    routes, (exact, prefix), tokens = flask_routes(), site_routes(), read("next-app/src/styles/tokens.css")
    checks = {
        "file": lambda r: check_file(r, basenames),
        "endpoint": lambda r: any(endpoint_matches(r[0], x, r[1]) for x in routes),
        "site": lambda r: any(path_matches(r, x) for x in exact) or any(path_matches(r, x, True) for x in prefix),
        "token": lambda r: token_defined(r, tokens),
        "ident": lambda r: in_code(r, corpus),
        "literal": lambda r: r in corpus,
    }
    missing, checked, skipped = [], 0, 0
    for path in files:
        md = read(os.path.relpath(path, ROOT))
        todo = planned(md)
        for span in spans(md):
            kind = classify(span)
            if not kind:
                continue
            if kind[0] == "ident" and kind[1] in todo:
                skipped += 1
                continue
            checked += 1
            if not checks[kind[0]](kind[1]):
                missing.append(f"{os.path.relpath(path, ROOT)}: {kind[0]} `{span}`")
        # a planned identifier that now exists must leave the comment
        for ident in todo:
            if in_code(ident, corpus):
                missing.append(f"{os.path.relpath(path, ROOT)}: `{ident}` is in the code, drop it from planned")
    missing += check_url_namespace_adr()
    missing += check_adr_numbers(files, tracked)
    for line in missing:
        print("MISSING", line)
    print(f"{checked} references checked in {len(files)} files, {len(missing)} missing, {skipped} planned")
    return 1 if missing else 0


if __name__ == "__main__":
    assert path_matches("/stamboken/*", "/stamboken/individ/[number]")
    assert path_matches("/uppladdningar/*", "/uppladdningar/", known_prefix=True)
    assert not path_matches("/k/<code>", "/stamboken/verifiera/[uuid]")
    assert not path_matches("/k", "/[slug]") and not path_matches("/butik/x", "/")
    tb = ("/api/v2/testbreed", {"POST"})
    assert endpoint_matches("/api/v2/", tb) and endpoint_matches("/api/v2/<resurs>", tb)
    assert endpoint_matches("/api/v2/testbreed", tb, "POST") and not endpoint_matches("/api/v2/testbreed", tb, "DELETE")
    assert not endpoint_matches("/api/v2/individual", ("/api/v2/individual/<number>", {"GET"}))
    assert token_defined(".sb-card", ".sb-card { x }") and not token_defined(".sb-car", ".sb-card { x }")
    assert not token_defined("--sb-in", "--sb-ink: #1F1B16;") and token_defined("--sb-*", "--sb-ink: #1F1B16;")
    assert classify("GET /api/individual/<n>") == ("endpoint", ("/api/individual/<n>", "GET"))
    assert classify("v1.2.3-rc.1") is None
    # numbers outside the ADR range, so renumbering never rewrites this test
    assert adr_numbers_mismatch("[ADR-0098](docs/adr/0099-x.md) [ADR-0099: X](0099-x.md)") == [
        "[ADR-0098](docs/adr/0099-x.md)"
    ]
    forms = '[ADR-0098](0099-x.md#beslut) [ADR-0098](0099-x.md "t")\n[ADR-0098]: 0099-x.md'
    assert len(adr_numbers_mismatch(forms)) == 3
    assert classify("@json_login_required") == ("ident", "json_login_required")
    assert planned("x <!-- check-adr-refs: planned some_table some_column --> y") == {"some_table", "some_column"}
    sys.exit(main(sys.argv[1:]))
