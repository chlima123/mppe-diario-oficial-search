# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-06-20

### Verified end-to-end

Search for "Ana Joêmia Marques da Rocha" across the last 12 months
(21/06/2025 → 20/06/2026):

- 230 editions analyzed
- 38 editions with matches
- 174 total occurrences
- ~3 min wall time (4 parallel workers)
- PDF report: 60 KB, 22 pages
- Email delivered and SENT-verified

### Scripts

- `mppe_diario_search.py` — bulk download + diacritic-insensitive search
- `build_report.py` — reportlab PDF renderer
- `send_email.py` — Gmail delivery with post-verification

### Known issues

- Python 3.9 incompatible with PEP 604 `X | None` syntax in type hints;
  scripts use bare annotations
- `gh repo create` requires `gh` CLI authenticated; see README for
  alternatives using `curl` + GitHub REST API