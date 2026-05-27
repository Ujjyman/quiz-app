# quiz-app

UP TGT Hindi MCQ Quiz — PYQ + Mock Test Series

**Live:** https://test-app-weld-nu.vercel.app

## What's inside

| Mode | Papers | Description |
|------|--------|-------------|
| ⚡ PYQ | 3 (2013, 2016, 2021) | Instant answer + explanation on click |
| 🏆 Mock Test | 14 | Timer, submit-to-reveal, score card |

## Regenerate output

```bash
pip3 install beautifulsoup4 pymupdf pytesseract pillow
brew install tesseract tesseract-lang   # for OCR (Hindi font PDFs)

python3 generate_quiz.py
```

Drop new HTML files in `pyq/` or PDFs in `test series/` and re-run.
