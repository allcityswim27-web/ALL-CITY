# Madison All-City Swim & Dive League — 1972–1979 Swim PDF Text Extracts

Raw text extracted from the swim-related PDFs published on the league history
archive at https://allcityswimdive.org/league-history/1970s/, covering the
Swim Results, Swim Heat Sheets, and Swim News documents for 1972–1979.

This is **raw extracted text only** — no parsing of names, ages, teams, or
times into structured fields. Text is extracted page by page in original
page order. OCR output for scanned pages will contain the usual OCR
artifacts (misread characters, garbled spacing, etc.) since these are old
mimeographed/typewritten heat sheets and results sheets, and a few are
scanned newspaper clippings.

## Method

- Source PDFs were downloaded directly from `allcityswimdive.org/history/<year>/...`.
- Each PDF was first tried with native text extraction (`pdftotext -layout`,
  poppler-utils).
- The "Swim News" PDFs (newspaper clippings) already carried an embedded
  text layer and extracted cleanly with `pdftotext`.
- The "Swim Results" and "Swim Heat Sheets" PDFs are scanned images with no
  text layer (native extraction returned empty/placeholder text). These were
  OCR'd with `ocrmypdf --force-ocr` (Tesseract), and the OCR sidecar text
  file was kept as the raw extract.

## Layout

```
results/history/<year>/<year>_Swim_<Type>.txt
```

One `.txt` file per source PDF, named after the original PDF filename.

All of the above are also concatenated, in chronological/document order, into
a single file: `All_City_Swim_1972-1979_Combined.txt`. Each section in that
file is preceded by a header banner naming the year, document type, source
filename, and source PDF URL, so it stays traceable back to its origin.

## Known site quirk — 1972 Swim Results

On the league history page, the "1972 Swim Results" link actually points to
`https://allcityswimdive.org/history/1973/1973_Swim_Results.pdf` — the same
file used for 1973's results — rather than a dedicated 1972 results PDF.
This appears to be a mislabeled/duplicated link on the source site itself
(no separate 1972 results PDF exists there). `1972/1972_Swim_Results.txt`
here is therefore identical to `1973/1973_Swim_Results.txt`, matching what
the site actually serves.

## Files per year

- **1972**: Swim Heat Sheets (Prelims), Swim Heat Sheets (Finals), Swim News,
  Swim Results (see quirk above)
- **1973**: Swim Results, Swim News (no separate heat sheets PDF published)
- **1974**: Swim Heat Sheets, Swim Results, Swim News
- **1975**: Swim Heat Sheets (Prelims), Swim Heat Sheets (Finals), Swim Results,
  Swim News
- **1976**: Swim Heat Sheets, Swim Heat Sheets (Finals) [source file named
  `heatsheet_1976_finals.pdf`], Swim Results, Swim News
- **1977**: Swim Heat Sheets (Finals), Swim Results, Swim News
- **1978**: Swim Heat Sheets (Finals), Swim Results, Swim News
- **1979**: Swim Heat Sheets (Prelims), Swim Heat Sheets (Finals), Swim Results,
  Swim News
