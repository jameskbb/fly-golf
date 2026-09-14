# Public release audit

Date: 2026-09-14. Scope: the first public release of Fly Golf, published as a clean snapshot of
the private incubation repository's working tree. **No Git history was transferred**: this
repository starts from its own placeholder commit, followed by the release commits.

## Method

1. The source was taken from the private repository's committed tree with `git archive`, so
   untracked and git-ignored material could not be copied by accident.
2. Every file was also inspected by name, and every tracked text file was searched for
   credential-shaped and private-looking content. We did not rely on `.gitignore` alone.
3. Binary assets (PNG, WebP, GIF, MP4, SVG) were searched for embedded paths and user names, and
   the PNG metadata chunks (`tEXt`, `iTXt`, `zTXt`, `eXIf`) were checked.

## Categories checked

| Category | What was searched | Result |
| --- | --- | --- |
| API keys, tokens and passwords | patterns for GitHub tokens (`ghp_`, `gho_`, `github_pat_`), AWS keys, `sk-` keys, bearer tokens, private-key headers, and `password` / `secret` / `token` / `api_key` assignments | none found |
| `.env` values | `.env*` files | only `.env.example` exists, and it contains placeholders and local defaults only |
| neuPrint credentials | `NEUPRINT_APPLICATION_CREDENTIALS` with a value | none; the variable appears only as a commented, empty example. No code path needs a token |
| Machine-specific absolute paths | `/home/…`, `/Users/…`, `C:\Users\…` | three metadata strings in trained-readout JSON files pointed into the author's home directory (a training-output path and two benchmark-report paths). They are informational only and were rewritten to repository-relative paths (`runs/…`). No code reads them |
| User names and e-mail addresses | the author's user name and address | none, apart from the repository owner's public GitHub handle in URLs |
| Private URLs, private IPs and internal hostnames | RFC 1918 ranges, `.local`, `.internal` | none. Only `127.0.0.1` / `localhost` development defaults |
| Debug output, personal notes and AI-assistant transcripts | planning and assistant directories | `.planning/` (project-planning files, including one note with session scratch paths) and `.claude/` (assistant guidance for a private workflow) were **omitted**. Their lasting content is already covered by `docs/` |
| Large local artifacts | file sizes | the largest committed file is the 2.8 MB README gameplay GIF. No file is larger than 3 MB |
| Raw MaleCNS downloads | `data/raw/` (about 1.1 GB) | **omitted** (git-ignored, and never tracked) |
| Compiled MaleCNS graph | `data/compiled/` (about 306 MB) | **omitted** (git-ignored, and never tracked) |
| Local runs and training output | `runs/` (about 22 MB of shot records, bench reports and training directories), `services/sim/.smoke-runs/` | **omitted**. The showcase uses one freshly recorded run, exported by `fly-golf export-showcase` (see [GITHUB_PAGES.md](GITHUB_PAGES.md)) |
| Caches, environments and build output | `node_modules/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `apps/web/dist/` | **omitted** |
| Image and video metadata | embedded strings and PNG text chunks | none found |

## What is intentionally public

- All Fly Golf source: the web app, the wire protocol, the simulator, training, tests and CI.
- Licensing and provenance: `LICENSE`, `THIRD_PARTY_NOTICES.md`, `services/sim/licenses/`
  (CC BY 4.0, DOOMFLY MIT, Shiu et al. MIT), `docs/PROVENANCE.md`, `docs/UPSTREAM.md` and
  `docs/DOOMFLY_DECOUPLING_AUDIT.md`.
- `data/malecns_v1.lock.json`: public URLs, sizes and checksums of the official MaleCNS release.
  It contains no connectome data.
- The installed trained readout (`experiments/readouts/malecns-readout-v1.json`) and two archived
  readouts. These are small linear weights fitted by Fly Golf, together with their training
  metadata. They are not connectome data.
- `services/sim/tests/fixtures/lif_reference.json`: spike counts from small synthetic test
  networks, used as the Brian2 parity oracle.
- README screenshots and the gameplay clip, all rendered from this application.
- `apps/web/public/showcase/`: exported records of real, recorded Fly Golf shots. These are shot
  outcomes and summary neural statistics, not connectome data.

## Edits made for publication

- Readout metadata paths were made repository-relative (see above).
- The build log and decoupling audit no longer point at the omitted planning directories.
- `THIRD_PARTY_NOTICES.md` now gives the correct location of the license texts.
- One test (`test_lock.py`) no longer depends on a developer's `FLY_GOLF_DATA_DIR`.

## Secrets found

None. No credential was found anywhere in the tree, so nothing had to be withheld for that reason.
