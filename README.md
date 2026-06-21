# MPPE Diário Oficial Search

Bulk search for mentions of a person (or any term) across the **Diário Oficial
Eletrônico do Ministério Público de Pernambuco (MPPE)**, with PDF report
generation and Gmail delivery.

The MPPE portal (`https://portal.mppe.mp.br/diario-oficial`) is a Liferay DXP
that **does not expose full-text search** via its public API. This toolkit
works around that by mapping the document hierarchy via the Headless Delivery
API, downloading all editions in a date window in parallel, extracting text
with PyPDF2, and running a diacritic-insensitive regex search.

## Verified against MPPE 2026-06-20

Search for "Ana Joêmia Marques da Rocha" across the last 12 months (Jun 2025
→ Jun 2026):

| Metric | Value |
|---|---|
| Editions analyzed | **230** |
| Editions with matches | **38** |
| Total occurrences | **174** |
| Wall time (4 parallel workers) | **~3 min** |
| Final PDF report | **60 KB, 22 pages** |
| Email delivery | SENT verified + attachment integrity check |

## Pipeline

```
mppe_diario_search.py  →  builds matches.json  →  build_report.py  →  relatorio.pdf
                                                                    ↓
                                                            send_email.py  →  Gmail
```

The three scripts run independently and can be used separately:

| Script | Purpose |
|---|---|
| `mppe_diario_search.py` | Map folder IDs → paginate editions → download PDFs in parallel → extract text (PyPDF2, PDFs deleted post-extraction) → search with diacritic-insensitive regex → write JSON |
| `build_report.py` | Render a styled PDF (capa + sumário + per-edition snippets) with reportlab |
| `send_email.py` | Send the PDF via Gmail using `googleapiclient` direct, with post-verification of SENT label and PDF magic bytes |

## Requirements

```bash
pip install PyPDF2 reportlab google-auth google-auth-oauthlib google-api-python-client
```

The script auto-adds the macOS Hermes Python 3.9 venv path
(`/Users/chlima/.hermes/home/Library/Python/3.9/lib/python/site-packages`)
to `sys.path` so that `PyPDF2` and `googleapiclient` resolve on the standard
macOS Python 3.9 install. On Linux, install with pip and the shim is a no-op.

For email delivery you also need:

- A Google Cloud OAuth client with the `gmail.send` scope authorized
- The token saved to `/Users/chlima/.hermes/google_token.json` (override with
  `GOOGLE_TOKEN_PATH` env var)

## Usage

### 1. Search

```bash
python3 mppe_diario_search.py "Ana Joêmia Marques da Rocha" \
    --months 12 \
    --workers 4 \
    --work /tmp/mppe-work \
    --out results.json
```

Arguments:

- `name` — the full name or term to search (positional, required)
- `--months N` — window in months back from today (default 12)
- `--start YYYY-MM-DD` / `--end YYYY-MM-DD` — explicit date range
- `--workers N` — parallel PDF download workers (default 4)
- `--work DIR` — working directory for PDFs + extracted text cache
- `--out FILE` — output JSON path

The script caches extracted text by `externalReferenceCode` (UUID) under
`--work/text/`, so re-runs are essentially free.

### 2. Build the PDF report

```bash
python3 build_report.py results.json relatorio.pdf
```

Accepts both the envelope JSON from `mppe_diario_search.py` and a bare list
of matches.

### 3. Send by email

```bash
python3 send_email.py relatorio.pdf \
    --subject "Diário Oficial MPPE — menções a 'Ana Joêmia Marques da Rocha'" \
    --body body.txt
```

The script always **post-verifies** that:

- The message landed in `SENT` (`labelIds` includes `"SENT"`)
- The attachment is a valid PDF (magic bytes `%PDF-`)

If verification fails, the script exits with code 2 and prints a warning.

## Output JSON envelope

`mppe_diario_search.py` writes a structured envelope:

```json
{
  "name": "Ana Joêmia Marques da Rocha",
  "start": "2025-06-21",
  "end": "2026-06-20",
  "editions_total": 230,
  "editions_with_match": 38,
  "total_occurrences": 113,
  "generated_at": "2026-06-20T22:00:00",
  "results": [
    {
      "item": {
        "uuid": "...",
        "id": 1372417,
        "title": "MPPE 03.07.2025 Edicao 1727",
        "date_created": "2025-07-03T00:07:21Z",
        "size_in_bytes": 828266,
        "content_url": "/documents/20121/.../Edicao+1727.pdf/...?version=1.0&download=true"
      },
      "match_count": 6,
      "hits": [
        {
          "offset": 14995,
          "matched": "ana joemia marques da rocha",
          "context": "art. 69 da LOEMP; RESOLVE: ... em razão das férias da Dra. Ana Joêmia Marques da Rocha ..."
        }
      ]
    }
  ]
}
```

## How the search works

The MPPE portal exposes its content via the Liferay Headless Delivery REST API
(no auth, no captcha). Folder hierarchy:

```
ROOT_FOLDER_ID = 57418
└── {YYYY}/                    e.g. "2025" → folder id varies
    └── {MM} - {MÊS}/          e.g. "06 - JUNHO" → folder id varies
        └── (documents)        each "MPPE DD.MM.AAAA Edicao NNNN" PDF
```

Year and month folder IDs are **not stable** — they change every time the
MPPE staff creates a new folder. The script always looks them up dynamically
at the start of each run.

### Search algorithm

For diacritic- and case-insensitive matching, both the text and the pattern
are normalized with `unicodedata`:

```python
def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()
```

Then run multiple pattern variants to catch spelling variants and title/honorific
prefixes (`Dra.`, `Dr.`, etc.).

## Pitfalls

1. **The Headless Delivery API returns gzip by default.** `urllib.request.urlopen().read()`
   does not auto-decompress. The script checks `Content-Encoding` and calls
   `gzip.decompress(raw)` manually. Symptom of the bug:
   `json.JSONDecodeError: 'utf-8' codec can't decode byte 0x8b`.

2. **No full-text search exposed.** The Liferay `?search=` query parameter
   only matches document titles, not PDF content. For name search you MUST
   download the PDFs.

3. **Folder IDs are not stable.** Do not hardcode year/month IDs.

4. **Filename typo on 2025 entries.** The `fileName` field has typos like
   `MPPE 19.06.205 Edicao 1724.pdf` (missing the "2"). Always build the URL
   from `contentUrl`, never by string-formatting the title.

5. **Do not parallelize past 4 workers.** 4 is the sweet spot. 8 hits
   timeouts on the MPPE portal.

6. **PyPDF2 vs pdfplumber/pymupdf on macOS:** PyPDF2 is the most reliable for
   these PDFs (text-based, no OCR needed). `pdftotext` is not installed by
   default on macOS Hermes.

7. **macOS Python 3.9 incompatibility.** Type hints like `str | None` crash
   at module import on Python 3.9.6 with `TypeError: unsupported operand
   type(s) for |: 'type' and 'NoneType'`. The scripts intentionally use
   bare `Optional[X]` annotations (or omit them) so they work on both 3.9
   and 3.10+.

8. **Always post-verify the sent email.** `messages.send` returning 200 does
   NOT guarantee the message is in SENT. The `send_email.py` script re-fetches
   the message and checks the `SENT` label and the PDF magic bytes.

## Related projects

- The full workflow (including the reconnaissance subagent recipe and bulk
  download patterns) is captured in the `brazil-mppe-diario-oficial-research`
  Hermes skill, which lives at `~/.hermes/skills/research/brazil-mppe-diario-oficial-research/`.
- A generic version covering federal DOU, state DOEs, state MP diários
  (MPSP, MPRJ) and court DJe lives in `brazil-diario-oficial-research`.

## License

MIT