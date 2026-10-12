# data/manual_snapshots — manually captured official pages

Use this folder when automated retrieval of an official page is blocked or fails (brief §6.4):

1. Open the official URL in a normal browser.
2. Save the page as HTML (or save the PDF) to `data/manual_snapshots/<bank_id>/<slug>.html`.
3. Run `bankrec ingest --manual <path> --source-url <url> [--captured-at YYYY-MM-DD]`.

Manual snapshots go through the same classification, parsing, and validation stages and are labeled
`capture_method=manual`.
