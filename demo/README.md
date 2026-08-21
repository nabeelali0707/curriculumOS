# Demo inputs

`CS201_DSA_Syllabus.pdf` — a sample Data Structures & Algorithms course
syllabus, written for this demo so the repo has a working syllabus input
without redistributing a real institution's material. It is **sample data,
not a real course document.** `make_syllabus.py` regenerates it
(`pip install fpdf2` first); fpdf2 is not an app dependency.

Past papers are not in the repo — point the pipeline at your own:

```bash
uvicorn app.main:app                # in another terminal

python scripts/demo_pipeline.py \
  --syllabus demo/CS201_DSA_Syllabus.pdf \
  --paper "2024:final:/path/to/final-2024.pdf" \
  --paper "2022:mid1:/path/to/mid1-2022.pdf"
```

The script prints what actually landed at each stage — a step that silently
does nothing shows up as a zero rather than a green check. A scanned paper
with no text layer is fine and worth including: it's what exercises the
OCR leg of the parser chain.
