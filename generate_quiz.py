#!/usr/bin/env python3
"""
UP TGT Hindi Quiz Website Generator
Reads:  pyq/*.html          → PYQ quiz apps  (instant feedback)
        test series/*.pdf   → Mock test apps (submit-to-reveal)
Writes: output/index.html + output/pyq/*.html + output/test_series/*.html
"""

import os, sys, re, json
from bs4 import BeautifulSoup

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pytesseract
    from PIL import Image as PILImage
    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False

# ── constants ───────────────────────────────────────────────────────────────
OPT_MAP     = {'क': 0, 'ख': 1, 'ग': 2, 'घ': 3}
OPT_LETTERS = ['क', 'ख', 'ग', 'घ']

PDF_SKIP = [
    r'\d{7,}', r'एक हजार', r'व्हाट्स अप',
    r'^मो\.?[\s\-–]', r'^पता[\s–\-]', r'NEW TEST',
    r'कु\.प्र\.', r'^\-?$', r'^–$', r'^पता$',
]

# min extraction rate (qs/ak) to include a PDF in the website
PDF_MIN_RATE = 0.50
PDF_MIN_QS   = 20

# ── HTML source parser (Jetpack Quiz) ───────────────────────────────────────

def parse_html_questions(path):
    with open(path, encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    questions = []
    for idx, block in enumerate(soup.find_all('div', class_='jetpack-quiz'), 1):
        q_div = block.find('div', class_='jetpack-quiz-question')
        if not q_div:
            continue
        question_text = q_div.get_text(strip=True)
        options, correct_index, explanation = [], 0, ''
        for ai, ans_div in enumerate(block.find_all('div', class_='jetpack-quiz-answer')):
            exp_div = ans_div.find('div', class_='jetpack-quiz-explanation')
            if exp_div:
                explanation = exp_div.decode_contents().strip()
                exp_div.extract()
            options.append(ans_div.get_text(strip=True))
            if ans_div.get('data-correct') == '1':
                correct_index = ai
        questions.append({
            'id': idx, 'question': question_text,
            'options': options, 'correct_index': correct_index,
            'explanation': explanation,
        })
    return questions


# ── PDF source parser (multi-column MCQ via PyMuPDF) ────────────────────────

def _page_columns(page):
    """Split a PDF page into left and right column line-lists."""
    mid = page.rect.width / 2 - 10
    pd = page.get_text('dict', flags=0)
    left, right = [], []
    for block in pd['blocks']:
        if block['type'] != 0:
            continue
        bx = block['bbox'][0]
        col = left if bx < mid else right
        for line in block['lines']:
            t = ' '.join(s['text'] for s in line['spans']).strip()
            if t:
                col.append(t)
    return left, right


def _clean(lines):
    out = []
    for l in lines:
        l = l.strip()
        if not l:
            continue
        if re.match(r'^\d{1,3}\.$', l):   # lone question number — always keep
            out.append(l); continue
        if len(l) < 3:
            continue
        if any(re.search(p, l) for p in PDF_SKIP):
            continue
        out.append(l)
    return out


def _is_q(line):
    m = re.match(r'^(\d{1,3})\.\s*(.*)', line)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 300:
            return n, m.group(2).strip()
    return None


def _parse_col(lines):
    questions = {}
    q_pos = [(i, r[0], r[1]) for i, l in enumerate(lines) if (r := _is_q(l))]
    for qi, (pos, num, first_text) in enumerate(q_pos):
        end = q_pos[qi + 1][0] if qi + 1 < len(q_pos) else len(lines)
        block = ([first_text] if first_text else []) + lines[pos + 1:end]

        opt_pos = {}
        for k, bl in enumerate(block):
            om = re.match(r'^\(([कखगघ])\)\s*(.*)', bl)
            if om:
                oi = OPT_MAP.get(om.group(1))
                if oi is not None and oi not in opt_pos:
                    opt_pos[oi] = (k, om.group(2).strip())
        if len(opt_pos) < 4:
            continue

        sorted_opts = sorted(opt_pos.items())
        opts = ['', '', '', '']
        for idx, (oi, (si, txt)) in enumerate(sorted_opts):
            nsi = sorted_opts[idx + 1][1][0] if idx + 1 < len(sorted_opts) else len(block)
            extra = []
            for el in block[si + 1:nsi]:
                if oi == 3 and (re.match(r'^[‚„""]', el) or _is_q(el)):
                    break
                extra.append(el)
            opts[oi] = (txt + ' ' + ' '.join(extra)).strip()

        stem_end = sorted_opts[0][1][0]
        qtxt = re.sub(r'^[‚„"]+\s*', '', ' '.join(block[:stem_end])).strip()
        if not qtxt:
            qtxt = f'प्रश्न {num}'
        if all(opts):
            questions[num] = {'question': qtxt, 'options': opts}
    return questions


def _ocr_col_questions(img):
    """Extract ordered list of (question_text) from one OCR'd column image."""
    col_text = pytesseract.image_to_string(img, lang='hin+eng', config='--psm 6')
    lines = [l.strip() for l in col_text.split('\n') if l.strip()]
    questions = []
    cur_lines = []
    in_question = False
    for line in lines:
        is_qnum = bool(re.match(r'^[lLI]?\d{1,3}[.,।।]\s', line) or
                       re.match(r'^\d{1,3}[.,।।]\s', line))
        is_option = bool(re.match(r'^\([कखगघ]\)', line))
        if is_qnum:
            if in_question and cur_lines:
                questions.append(' '.join(cur_lines).strip())
            # Extract text after the question number
            first = re.sub(r'^[lLI]?\d{1,3}[.,।।]\s*', '', line).strip()
            cur_lines = [first] if first and not is_option else []
            in_question = True
        elif is_option and in_question:
            if cur_lines:
                questions.append(' '.join(cur_lines).strip())
            cur_lines = []
            in_question = False
        elif in_question:
            cur_lines.append(line)
    if in_question and cur_lines:
        questions.append(' '.join(cur_lines).strip())
    return [q for q in questions if q]


def _ocr_question_texts(path, known_q_ids_per_page):
    """OCR-extract question texts from PDFs where font encoding is broken.
    known_q_ids_per_page: dict {page_index: [sorted question ids on that page]}
    """
    if not TESSERACT_OK:
        return {}
    doc = fitz.open(path)
    q_texts = {}
    scale = 3
    mat = fitz.Matrix(scale, scale)
    for pi in range(len(doc)):
        page = doc[pi]
        full_text = page.get_text()
        if len(re.findall(r'\d+\.[कखगघ]', full_text)) >= 8:
            continue  # skip answer key page
        q_ids = known_q_ids_per_page.get(pi, [])
        if not q_ids:
            continue
        pw, ph = page.rect.width, page.rect.height
        mid = pw / 2
        header_y = 210  # skip logo/address header
        all_qtexts = []
        for x0, x1 in [(36, mid - 10), (mid + 10, pw - 10)]:
            pix = page.get_pixmap(matrix=mat, clip=fitz.Rect(x0, header_y, x1, ph - 30))
            img = PILImage.frombytes('RGB', [pix.width, pix.height], pix.samples)
            all_qtexts.extend(_ocr_col_questions(img))
        # Match positionally to known question IDs on this page
        for i, qid in enumerate(q_ids):
            if i < len(all_qtexts) and all_qtexts[i]:
                q_texts[qid] = all_qtexts[i]
    doc.close()
    return q_texts


def parse_pdf_questions(path):
    if fitz is None:
        raise RuntimeError('PyMuPDF not installed')
    doc = fitz.open(path)
    answer_key, all_q = {}, {}
    page_q_ids = {}  # page_index → list of question ids found on that page
    for pi in range(len(doc)):
        page = doc[pi]
        full_text = page.get_text()
        if len(re.findall(r'\d+\.[कखगघ]', full_text)) >= 8:
            for m in re.finditer(r'(\d+)\.[।\s]*([कखगघ])', full_text):
                answer_key[int(m.group(1))] = OPT_MAP[m.group(2)]
            continue
        page_qs = {}
        for col_lines in _page_columns(page):
            page_qs.update(_parse_col(_clean(col_lines)))
        page_q_ids[pi] = sorted(page_qs.keys())
        all_q.update(page_qs)
    doc.close()

    if not answer_key:
        return []   # no answer key → can't build quiz

    questions = []
    for num in sorted(all_q.keys()):
        if num not in answer_key:
            continue
        q = all_q[num]
        questions.append({
            'id': num,
            'question': q['question'],
            'options': q['options'],
            'correct_index': answer_key[num],
            'explanation': '',
        })

    # If most questions have placeholder text, OCR the actual question text
    empty = sum(1 for q in questions if q['question'].startswith('प्रश्न '))
    if empty > len(questions) * 0.5 and TESSERACT_OK:
        # Filter page_q_ids to only include questions in final list
        final_ids = {q['id'] for q in questions}
        filtered_page_ids = {
            pi: [qid for qid in ids if qid in final_ids]
            for pi, ids in page_q_ids.items()
        }
        ocr_texts = _ocr_question_texts(path, filtered_page_ids)
        filled = 0
        for q in questions:
            if q['id'] in ocr_texts and ocr_texts[q['id']]:
                q['question'] = ocr_texts[q['id']]
                filled += 1
        if filled:
            print(f'  OCR filled {filled}/{len(questions)} question texts')

    return questions


# ── Naming helpers ───────────────────────────────────────────────────────────

def _html_meta(path):
    name = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r'(\d{4})', name)
    year = m.group(1) if m else ''
    title = f'UP TGT हिंदी {year}' if year else re.sub(r'[_\-]+', ' ', name).strip().title()
    slug = f'up_tgt_hindi_{year}' if year else re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return title, slug, year


def _pdf_meta(path):
    name = os.path.splitext(os.path.basename(path))[0]
    # Strip trailing ID_timestamp
    name = re.sub(r'_\d{7,}_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}$', '', name)
    name = re.sub(r'_\d{7,}$', '', name)
    # Strip answer-key suffix
    name = re.sub(r'\s*\(उत्तर[^)]*\)', '', name)
    name = re.sub(r'\s*उत्तर[^_\s]*', '', name)
    # Parse test number
    m = re.match(r'(?:NEW\s*)?TEST[-_\s]*(\d+)[-_\s]*(.*)', name, re.IGNORECASE)
    if m:
        num = m.group(1).zfill(2)
        topic = m.group(2).strip(' -_')
        title = f'TEST {num}: {topic}' if topic else f'TEST {num}'
        slug = f'test_{num}'
    else:
        # Hindi filename
        title = name.strip()
        slug = re.sub(r'[^a-z0-9]+', '_', name.lower(), flags=re.ASCII).strip('_') or 'test'
    return title, slug


# ── Shared CSS ───────────────────────────────────────────────────────────────

SHARED_CSS = """
:root {
  --bg:#f0f4ff;--surface:#fff;--surface2:#f8faff;
  --border:#e2e8f0;--text:#1e293b;--muted:#64748b;
  --primary:#4f46e5;--primary-dark:#3730a3;--primary-light:#eef2ff;
  --pyq:#0891b2;--pyq-bg:#ecfeff;--pyq-dark:#0e7490;
  --ts:#ea580c;--ts-bg:#fff7ed;--ts-dark:#c2410c;
  --correct:#16a34a;--correct-bg:#dcfce7;--correct-bdr:#86efac;
  --wrong:#dc2626;--wrong-bg:#fee2e2;--wrong-bdr:#fca5a5;
  --trick:#d97706;--trick-bg:#fffbeb;--trick-bdr:#fcd34d;
  --sel-bg:#eef2ff;--sel-bdr:#4f46e5;
  --shadow:0 1px 3px rgba(0,0,0,.08),0 4px 16px rgba(0,0,0,.06);
  --r:14px;
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#0f1117;--surface:#1a1d27;--surface2:#141720;
    --border:#2d3141;--text:#e2e8f0;--muted:#94a3b8;
    --primary:#818cf8;--primary-dark:#6366f1;--primary-light:#1e1b4b;
    --pyq:#22d3ee;--pyq-bg:#0c1a1e;--pyq-dark:#0891b2;
    --ts:#fb923c;--ts-bg:#1c0f05;--ts-dark:#ea580c;
    --correct:#4ade80;--correct-bg:#052e16;--correct-bdr:#166534;
    --wrong:#f87171;--wrong-bg:#2d0909;--wrong-bdr:#991b1b;
    --trick:#fbbf24;--trick-bg:#1c1500;--trick-bdr:#92400e;
    --sel-bg:#1e1b4b;--sel-bdr:#818cf8;
    --shadow:0 1px 3px rgba(0,0,0,.3),0 4px 16px rgba(0,0,0,.25);
  }
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:'Noto Sans Devanagari','Mangal',system-ui,sans-serif;
     background:var(--bg);color:var(--text);line-height:1.7;
     -webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
"""

FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari'
    ':wght@400;500;600;700;800&display=swap" rel="stylesheet">'
)


# ── INDEX PAGE ───────────────────────────────────────────────────────────────

def _paper_card(p, mode):
    color = 'pyq' if mode == 'pyq' else 'ts'
    path  = f"{mode}/{p['slug']}_quiz.html"
    label = '⚡ PYQ' if mode == 'pyq' else '🏆 Mock Test'
    cta   = 'शुरू करें →' if mode == 'pyq' else 'परीक्षा दें →'
    desc  = 'तत्काल उत्तर · व्याख्या · ट्रिक' if mode == 'pyq' else 'टाइमर · जमा करने पर उत्तर'
    year_badge = f'<div class="p-year">{p["year"]}</div>' if p.get('year') else ''
    return f"""
      <a href="{path}" class="pcard {color}-card">
        {year_badge}
        <div class="p-name">{p['title']}</div>
        <div class="p-meta">
          <span class="tag tag-{color}">{label}</span>
          <span class="p-count">📝 {p['count']} प्रश्न</span>
        </div>
        <div class="p-desc">{desc}</div>
        <div class="p-cta">{cta}</div>
      </a>"""


def generate_index(pyq_papers, ts_papers, out_dir):
    pyq_cards = '\n'.join(_paper_card(p, 'pyq') for p in pyq_papers)
    ts_cards  = '\n'.join(_paper_card(p, 'test_series') for p in ts_papers)

    html = f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>UP TGT हिंदी प्रश्नोत्तरी</title>
{FONT_LINK}
<style>
{SHARED_CSS}
.site-header{{
  background:linear-gradient(135deg,#312e81,#4f46e5 55%,#7c3aed);
  color:#fff;padding:18px 24px;
  display:flex;align-items:center;gap:14px;
  box-shadow:0 4px 20px rgba(79,70,229,.4);
}}
.logo{{font-size:28px;flex-shrink:0}}
.site-title{{font-size:19px;font-weight:800}}
.site-sub{{font-size:12px;opacity:.75;margin-top:2px}}
.hero{{
  background:linear-gradient(135deg,#312e81,#4f46e5 60%,#7c3aed);
  color:#fff;text-align:center;padding:52px 20px 44px;
}}
.hero h1{{font-size:clamp(22px,5vw,40px);font-weight:900;line-height:1.2;margin-bottom:12px}}
.hero p{{font-size:15px;opacity:.85;max-width:460px;margin:0 auto 24px}}
.chips{{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}}
.chip{{background:rgba(255,255,255,.15);backdrop-filter:blur(6px);
      border:1px solid rgba(255,255,255,.25);border-radius:100px;
      padding:5px 14px;font-size:13px;font-weight:600}}
main{{max-width:1020px;margin:0 auto;padding:44px 18px 80px}}
.sec-label{{display:inline-flex;align-items:center;gap:7px;font-size:12px;
           font-weight:800;letter-spacing:.6px;text-transform:uppercase;
           padding:4px 13px;border-radius:100px;margin-bottom:10px}}
.lbl-pyq{{background:var(--pyq-bg);color:var(--pyq)}}
.lbl-ts {{background:var(--ts-bg); color:var(--ts)}}
.sec-title{{font-size:21px;font-weight:900;margin-bottom:5px}}
.sec-desc{{font-size:13px;color:var(--muted);margin-bottom:22px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(255px,1fr));
       gap:16px;margin-bottom:56px}}
.pcard{{background:var(--surface);border:1px solid var(--border);
        border-radius:var(--r);padding:20px 18px;
        display:flex;flex-direction:column;gap:5px;
        box-shadow:var(--shadow);cursor:pointer;position:relative;overflow:hidden;
        transition:transform .18s,box-shadow .18s,border-color .18s}}
.pcard::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px}}
.pyq-card::before{{background:linear-gradient(90deg,var(--pyq),#6366f1)}}
.ts-card::before {{background:linear-gradient(90deg,var(--ts),#f97316)}}
.pcard:hover{{transform:translateY(-4px);box-shadow:0 8px 32px rgba(79,70,229,.18);
              border-color:var(--primary)}}
.ts-card:hover{{border-color:var(--ts)}}
.p-year{{font-size:11px;font-weight:800;color:var(--primary);letter-spacing:.5px;text-transform:uppercase}}
.p-name{{font-size:17px;font-weight:800;line-height:1.3}}
.p-meta{{display:flex;align-items:center;gap:8px;margin-top:3px}}
.tag{{font-size:11px;font-weight:700;padding:2px 9px;border-radius:100px;letter-spacing:.3px}}
.tag-pyq{{background:var(--pyq-bg);color:var(--pyq)}}
.tag-ts {{background:var(--ts-bg); color:var(--ts)}}
.p-count{{font-size:12px;color:var(--muted)}}
.p-desc{{font-size:12px;color:var(--muted)}}
.p-cta{{margin-top:9px;font-size:13px;font-weight:800;color:var(--primary)}}
.ts-card .p-cta{{color:var(--ts)}}
footer{{text-align:center;padding:24px;font-size:12px;color:var(--muted);
        border-top:1px solid var(--border)}}
</style>
</head>
<body>
<header class="site-header">
  <div class="logo">📚</div>
  <div>
    <div class="site-title">UP TGT हिंदी प्रश्नोत्तरी</div>
    <div class="site-sub">पूर्ण तैयारी · स्मार्ट अभ्यास · स्मरण ट्रिक</div>
  </div>
</header>

<section class="hero">
  <h1>हिंदी परीक्षा की<br>स्मार्ट तैयारी करें</h1>
  <p>पूर्व वर्षों के प्रश्नपत्र · मॉक परीक्षा श्रृंखला · व्याख्या सहित</p>
  <div class="chips">
    <span class="chip">⚡ तत्काल उत्तर</span>
    <span class="chip">💡 ट्रिक सहित</span>
    <span class="chip">🏆 स्कोर कार्ड</span>
    <span class="chip">⏱ टाइमर</span>
    <span class="chip">📱 मोबाइल अनुकूल</span>
  </div>
</section>

<main>
  <div class="sec-label lbl-pyq">⚡ PYQ Mode</div>
  <div class="sec-title">पूर्ववर्ती वर्षों के प्रश्नपत्र</div>
  <div class="sec-desc">विकल्प पर क्लिक करते ही तुरंत सही उत्तर, व्याख्या और ट्रिक देखें</div>
  <div class="grid">{pyq_cards}</div>

  <div class="sec-label lbl-ts">🏆 Test Series</div>
  <div class="sec-title">मॉक परीक्षा श्रृंखला</div>
  <div class="sec-desc">पूरी परीक्षा दें — जमा करने के बाद उत्तर व स्कोर कार्ड देखें</div>
  <div class="grid">{ts_cards}</div>
</main>

<footer>© 2026 UP TGT हिंदी प्रश्नोत्तरी · प्रश्न hindisarang.com एवं अन्य स्रोतों से संकलित</footer>
</body>
</html>"""
    out = os.path.join(out_dir, 'index.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    return out


# ── PYQ QUIZ PAGE ────────────────────────────────────────────────────────────

PYQ_PAGE = """<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — PYQ</title>
{font}
<style>
{css}
.qheader{{position:sticky;top:0;z-index:100;background:var(--surface);
          border-bottom:1px solid var(--border);padding:0 18px;
          box-shadow:0 2px 12px rgba(0,0,0,.08)}}
.htop{{display:flex;align-items:center;gap:10px;padding:11px 0 7px}}
.back{{width:34px;height:34px;border-radius:50%;border:1px solid var(--border);
       background:var(--surface2);display:flex;align-items:center;justify-content:center;
       font-size:16px;flex-shrink:0;text-decoration:none;transition:background .15s}}
.back:hover{{background:var(--pyq-bg)}}
.htitle{{font-size:14px;font-weight:800;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.hmode{{font-size:11px;font-weight:700;padding:3px 10px;border-radius:100px;
        background:var(--pyq-bg);color:var(--pyq);flex-shrink:0}}
.stats{{display:flex;gap:6px;padding:0 0 9px;flex-wrap:wrap}}
.sp{{display:flex;align-items:center;gap:4px;font-size:12px;font-weight:700;
     padding:3px 11px;border-radius:100px;background:var(--surface2);border:1px solid var(--border)}}
.sp.sc{{background:var(--correct-bg);color:var(--correct);border-color:var(--correct-bdr)}}
.sp.sw{{background:var(--wrong-bg);  color:var(--wrong);  border-color:var(--wrong-bdr)}}
.pbar{{height:3px;background:var(--border);margin:0 -18px}}
.pfill{{height:100%;background:linear-gradient(90deg,var(--pyq),var(--primary));
        width:0%;transition:width .3s}}
.wrap{{max-width:780px;margin:0 auto;padding:22px 15px 70px}}
.qcard{{background:var(--surface);border:1px solid var(--border);
        border-radius:var(--r);padding:20px 20px 16px;margin-bottom:16px;
        box-shadow:var(--shadow)}}
.qmeta{{display:flex;align-items:center;gap:7px;margin-bottom:10px}}
.qnum{{font-size:11px;font-weight:800;color:var(--pyq);
       background:var(--pyq-bg);padding:3px 10px;border-radius:100px;letter-spacing:.4px}}
.qst{{margin-left:auto;font-size:12px;opacity:0;transition:opacity .2s}}
.qst.show{{opacity:1}}
.qtxt{{font-size:15px;font-weight:600;line-height:1.65;margin-bottom:14px}}
.opts{{display:flex;flex-direction:column;gap:7px}}
.opt{{display:flex;align-items:flex-start;gap:10px;padding:10px 14px;
      border-radius:9px;border:1.5px solid var(--border);background:var(--surface2);
      cursor:pointer;font-family:inherit;font-size:14px;color:var(--text);
      text-align:left;line-height:1.5;width:100%;transition:all .15s}}
.oc{{width:20px;height:20px;border-radius:50%;border:2px solid var(--border);
     flex-shrink:0;display:flex;align-items:center;justify-content:center;
     margin-top:1px;font-size:11px;font-weight:800;transition:all .15s;background:var(--surface)}}
.opt:hover:not(:disabled) .oc{{border-color:var(--pyq);background:var(--pyq-bg)}}
.opt:hover:not(:disabled){{border-color:var(--pyq);background:var(--pyq-bg)}}
.opt:disabled{{cursor:default}}
.opt.correct{{background:var(--correct-bg);border-color:var(--correct-bdr)}}
.opt.correct .oc{{background:var(--correct);border-color:var(--correct);color:#fff}}
.opt.correct .ol{{color:var(--correct);font-weight:700}}
.opt.wrong{{background:var(--wrong-bg);border-color:var(--wrong-bdr)}}
.opt.wrong .oc{{background:var(--wrong);border-color:var(--wrong);color:#fff}}
.opt.wrong .ol{{color:var(--wrong);font-weight:700}}
.tbox{{margin-top:13px;border-radius:9px;border:1.5px solid var(--trick-bdr);
       background:var(--trick-bg);padding:12px 14px;display:none;
       animation:fs .25s ease}}
.tbox.show{{display:block}}
@keyframes fs{{from{{opacity:0;transform:translateY(-5px)}}to{{opacity:1;transform:translateY(0)}}}}
.tlabel{{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:800;
         color:var(--trick);letter-spacing:.5px;text-transform:uppercase;margin-bottom:7px}}
.ttext{{font-size:13px;line-height:1.7;color:var(--text)}}
.ttext strong{{color:var(--trick)}}
</style>
</head>
<body>
<div class="qheader">
  <div class="htop">
    <a href="../index.html" class="back">←</a>
    <div class="htitle">{title}</div>
    <div class="hmode">⚡ PYQ</div>
  </div>
  <div class="stats">
    <div class="sp">📋 प्रयास: <span id="va">0</span></div>
    <div class="sp sc">✅ सही: <span id="vc">0</span></div>
    <div class="sp sw">❌ गलत: <span id="vw">0</span></div>
    <div class="sp" style="margin-left:auto">📝 {total} प्रश्न</div>
  </div>
  <div class="pbar"><div class="pfill" id="pf"></div></div>
</div>
<div class="wrap" id="qc"></div>
<script>
const Q={qjson};
const AL=['A','B','C','D','E'];
let att=0,cor=0,wrg=0;
function upd(){{
  document.getElementById('va').textContent=att;
  document.getElementById('vc').textContent=cor;
  document.getElementById('vw').textContent=wrg;
  document.getElementById('pf').style.width=Math.round(att/Q.length*100)+'%';
}}
function build(){{
  const c=document.getElementById('qc');
  Q.forEach((q,qi)=>{{
    const card=document.createElement('div');
    card.className='qcard';card.id='c'+qi;
    card.innerHTML=`
      <div class="qmeta">
        <span class="qnum">प्रश्न ${{qi+1}}</span>
        <span class="qst" id="st${{qi}}"></span>
      </div>
      <div class="qtxt">${{q.question}}</div>
      <div class="opts" id="o${{qi}}"></div>
      ${{q.explanation?`<div class="tbox" id="t${{qi}}">
        <div class="tlabel">💡 याद रखें</div>
        <div class="ttext">${{q.explanation}}</div></div>`:''}}`;
    const od=card.querySelector('#o'+qi);
    q.options.forEach((opt,oi)=>{{
      const b=document.createElement('button');
      b.className='opt';
      b.innerHTML=`<span class="oc">${{AL[oi]}}</span><span class="ol">${{opt}}</span>`;
      b.addEventListener('click',()=>ans(qi,oi));
      od.appendChild(b);
    }});
    c.appendChild(card);
  }});
}}
function ans(qi,ch){{
  const q=Q[qi];
  const btns=document.querySelectorAll('#o'+qi+' .opt');
  btns.forEach(b=>b.disabled=true);
  btns[q.correct_index].classList.add('correct');
  btns[q.correct_index].querySelector('.oc').textContent='✓';
  const st=document.getElementById('st'+qi);
  if(ch===q.correct_index){{cor++;st.textContent='✅ सही';st.style.color='var(--correct)';}}
  else{{btns[ch].classList.add('wrong');btns[ch].querySelector('.oc').textContent='✗';
        wrg++;st.textContent='❌ गलत';st.style.color='var(--wrong)';}}
  st.classList.add('show');
  const t=document.getElementById('t'+qi);
  if(t)t.classList.add('show');
  att++;upd();
}}
build();upd();
</script>
</body>
</html>"""


def generate_pyq(questions, title, out_path):
    html = PYQ_PAGE.format(
        title=title, total=len(questions),
        qjson=json.dumps(questions, ensure_ascii=False),
        font=FONT_LINK, css=SHARED_CSS,
    )
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)


# ── TEST SERIES QUIZ PAGE ────────────────────────────────────────────────────

TS_PAGE = """<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Mock Test</title>
{font}
<style>
{css}
.qheader{{position:sticky;top:0;z-index:100;background:var(--surface);
          border-bottom:1px solid var(--border);padding:0 18px;
          box-shadow:0 2px 12px rgba(0,0,0,.08)}}
.htop{{display:flex;align-items:center;gap:10px;padding:11px 0 7px;flex-wrap:wrap}}
.back{{width:34px;height:34px;border-radius:50%;border:1px solid var(--border);
       background:var(--surface2);display:flex;align-items:center;justify-content:center;
       font-size:16px;flex-shrink:0;text-decoration:none;transition:background .15s}}
.back:hover{{background:var(--ts-bg)}}
.htitle{{font-size:14px;font-weight:800;flex:1;min-width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.timer{{font-size:17px;font-weight:800;letter-spacing:1px;color:var(--ts);
        font-variant-numeric:tabular-nums;flex-shrink:0}}
.timer.urg{{color:var(--wrong);animation:pu 1s infinite}}
@keyframes pu{{0%,100%{{opacity:1}}50%{{opacity:.5}}}}
.hmode{{font-size:11px;font-weight:700;padding:3px 10px;border-radius:100px;
        background:var(--ts-bg);color:var(--ts);flex-shrink:0}}
.prow{{display:flex;align-items:center;gap:10px;padding:5px 0 9px}}
.plbl{{font-size:12px;color:var(--muted);white-space:nowrap}}
.pbar{{flex:1;height:5px;background:var(--border);border-radius:100px;overflow:hidden}}
.pfill{{height:100%;background:linear-gradient(90deg,var(--ts),#f97316);
        width:0%;transition:width .3s;border-radius:100px}}
.wrap{{max-width:780px;margin:0 auto;padding:22px 15px 36px}}
.qcard{{background:var(--surface);border:1px solid var(--border);
        border-radius:var(--r);padding:20px 20px 16px;margin-bottom:16px;
        box-shadow:var(--shadow)}}
.qmeta{{display:flex;align-items:center;gap:7px;margin-bottom:10px}}
.qnum{{font-size:11px;font-weight:800;color:var(--ts);
       background:var(--ts-bg);padding:3px 10px;border-radius:100px;letter-spacing:.4px}}
.qdot{{width:7px;height:7px;border-radius:50%;background:var(--border);
       margin-left:auto;transition:background .2s}}
.qdot.done{{background:var(--ts)}}
.qtxt{{font-size:15px;font-weight:600;line-height:1.65;margin-bottom:14px}}
.opts{{display:flex;flex-direction:column;gap:7px}}
.opt{{display:flex;align-items:flex-start;gap:10px;padding:10px 14px;
      border-radius:9px;border:1.5px solid var(--border);background:var(--surface2);
      cursor:pointer;font-family:inherit;font-size:14px;color:var(--text);
      text-align:left;line-height:1.5;width:100%;transition:all .15s}}
.or{{width:18px;height:18px;border-radius:50%;border:2px solid var(--border);
     flex-shrink:0;margin-top:2px;transition:all .15s;background:var(--surface);
     display:flex;align-items:center;justify-content:center}}
.or::after{{content:'';display:none;width:7px;height:7px;background:#fff;border-radius:50%}}
.opt:hover:not(:disabled):not(.sel) .or{{border-color:var(--ts)}}
.opt:hover:not(:disabled):not(.sel){{border-color:var(--ts);background:var(--ts-bg)}}
.opt:disabled{{cursor:default}}
.opt.sel{{background:var(--sel-bg);border-color:var(--sel-bdr)}}
.opt.sel .or{{border-color:var(--primary);background:var(--primary)}}
.opt.sel .or::after{{display:block}}
.opt.correct{{background:var(--correct-bg);border-color:var(--correct-bdr)}}
.opt.correct .or{{background:var(--correct);border-color:var(--correct)}}
.opt.correct .or::after{{content:'✓';display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:900}}
.opt.correct .ol{{color:var(--correct);font-weight:700}}
.opt.wrong{{background:var(--wrong-bg);border-color:var(--wrong-bdr)}}
.opt.wrong .or{{background:var(--wrong);border-color:var(--wrong)}}
.opt.wrong .or::after{{content:'✗';display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:900}}
.opt.wrong .ol{{color:var(--wrong);font-weight:700}}
.tbox{{margin-top:13px;border-radius:9px;border:1.5px solid var(--trick-bdr);
       background:var(--trick-bg);padding:12px 14px;display:none;
       animation:fs .3s ease}}
.tbox.show{{display:block}}
@keyframes fs{{from{{opacity:0;transform:translateY(-5px)}}to{{opacity:1;transform:translateY(0)}}}}
.tlabel{{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:800;
         color:var(--trick);letter-spacing:.5px;text-transform:uppercase;margin-bottom:7px}}
.ttext{{font-size:13px;line-height:1.7}}
.subwrap{{text-align:center;padding:22px 16px 18px}}
.subbtn{{background:linear-gradient(135deg,#ea580c,#f97316);color:#fff;border:none;
         padding:15px 48px;font-size:16px;font-weight:800;border-radius:11px;
         cursor:pointer;font-family:inherit;
         box-shadow:0 4px 18px rgba(234,88,12,.4);transition:transform .15s,box-shadow .15s}}
.subbtn:hover{{transform:translateY(-2px);box-shadow:0 8px 28px rgba(234,88,12,.5)}}
.subbtn:disabled{{opacity:.5;cursor:default;transform:none}}
.warn{{font-size:12px;color:var(--wrong);margin-top:8px;display:none}}
/* Modal */
.ov{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);
     backdrop-filter:blur(4px);z-index:200;align-items:center;justify-content:center}}
.ov.show{{display:flex}}
.modal{{background:var(--surface);border-radius:18px;padding:38px 32px;
        max-width:420px;width:92%;text-align:center;
        box-shadow:0 24px 64px rgba(0,0,0,.35);
        animation:pi .28s cubic-bezier(.34,1.56,.64,1)}}
@keyframes pi{{from{{transform:scale(.82);opacity:0}}to{{transform:scale(1);opacity:1}}}}
.mico{{font-size:52px;margin-bottom:5px}}
.mhead{{font-size:22px;font-weight:900;margin-bottom:3px}}
.mscore{{font-size:48px;font-weight:900;
         background:linear-gradient(135deg,var(--ts),#f97316);
         -webkit-background-clip:text;-webkit-text-fill-color:transparent;
         background-clip:text;margin:7px 0}}
.mpct{{font-size:14px;color:var(--muted);margin-bottom:20px}}
.mgrid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:24px}}
.ms{{padding:13px;border-radius:11px}}
.ms .bn{{font-size:28px;font-weight:900;display:block;margin-bottom:1px}}
.ms .lb{{font-size:11px;font-weight:700}}
.msc{{background:var(--correct-bg);color:var(--correct)}}
.msw{{background:var(--wrong-bg);  color:var(--wrong)}}
.mss{{background:var(--surface2);  color:var(--muted);grid-column:span 2}}
.revbtn{{background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;border:none;
         padding:13px 38px;font-size:14px;font-weight:800;border-radius:9px;
         cursor:pointer;font-family:inherit;transition:transform .15s}}
.revbtn:hover{{transform:translateY(-2px)}}
</style>
</head>
<body>
<div class="qheader">
  <div class="htop">
    <a href="../index.html" class="back">←</a>
    <div class="htitle">{title}</div>
    <div class="timer" id="tmr">⏱ --:--:--</div>
    <div class="hmode">🏆 Mock Test</div>
  </div>
  <div class="prow">
    <span class="plbl" id="plbl">0 / {total} उत्तर दिए</span>
    <div class="pbar"><div class="pfill" id="pf"></div></div>
  </div>
</div>
<div class="wrap" id="qc"></div>
<div class="subwrap">
  <button class="subbtn" id="sbtn" onclick="trySub()">🏁 &nbsp;परीक्षा जमा करें</button>
  <div class="warn" id="wn"></div>
</div>
<div class="ov" id="ov">
  <div class="modal">
    <div class="mico" id="mi">🏆</div>
    <div class="mhead" id="mh">परिणाम</div>
    <div class="mscore" id="ms">0/{total}</div>
    <div class="mpct" id="mp">0%</div>
    <div class="mgrid">
      <div class="ms msc"><span class="bn" id="mc">0</span><span class="lb">✅ सही</span></div>
      <div class="ms msw"><span class="bn" id="mw">0</span><span class="lb">❌ गलत</span></div>
      <div class="ms mss"><span class="bn" id="mk">0</span><span class="lb">⏭ छोड़े गए</span></div>
    </div>
    <button class="revbtn" onclick="closeM()">📋 उत्तर देखें</button>
  </div>
</div>
<script>
const Q={qjson};
const TOT={total},SEC={timer};
const UA=new Array(Q.length).fill(null);
let done=false,left=SEC,tmr=null,cfm=false;
function p2(n){{return String(n).padStart(2,'0')}}
function startTmr(){{
  const el=document.getElementById('tmr');
  function tick(){{
    const h=Math.floor(left/3600),m=Math.floor((left%3600)/60),s=left%60;
    el.textContent='⏱ '+p2(h)+':'+p2(m)+':'+p2(s);
    if(left<=300)el.classList.add('urg');
    if(left--<=0){{clearInterval(tmr);doSub();}}
  }}
  tick();tmr=setInterval(tick,1000);
}}
function updP(){{
  const n=UA.filter(a=>a!==null).length;
  document.getElementById('plbl').textContent=n+' / '+TOT+' उत्तर दिए';
  document.getElementById('pf').style.width=Math.round(n/TOT*100)+'%';
}}
function build(){{
  const c=document.getElementById('qc');
  Q.forEach((q,qi)=>{{
    const card=document.createElement('div');
    card.className='qcard';card.id='c'+qi;
    card.innerHTML=`
      <div class="qmeta"><span class="qnum">प्रश्न ${{qi+1}}</span><span class="qdot" id="d${{qi}}"></span></div>
      <div class="qtxt">${{q.question}}</div>
      <div class="opts" id="o${{qi}}"></div>
      ${{q.explanation?`<div class="tbox" id="t${{qi}}"><div class="tlabel">💡 याद रखें</div><div class="ttext">${{q.explanation}}</div></div>`:''}}`;
    const od=card.querySelector('#o'+qi);
    q.options.forEach((opt,oi)=>{{
      const b=document.createElement('button');
      b.className='opt';
      b.innerHTML=`<span class="or"></span><span class="ol">${{opt}}</span>`;
      b.addEventListener('click',()=>sel(qi,oi,b));
      od.appendChild(b);
    }});
    c.appendChild(card);
  }});
}}
function sel(qi,oi,btn){{
  if(done)return;
  const prev=UA[qi];
  if(prev!==null)document.querySelectorAll('#o'+qi+' .opt')[prev].classList.remove('sel');
  UA[qi]=oi;btn.classList.add('sel');
  document.getElementById('d'+qi).classList.add('done');
  updP();
}}
function trySub(){{
  if(done)return;
  const un=UA.filter(a=>a===null).length;
  if(!cfm&&un>0){{
    const w=document.getElementById('wn');
    w.textContent=un+' प्रश्न अनुत्तरित हैं — दोबारा क्लिक करें';
    w.style.display='block';cfm=true;return;
  }}
  doSub();
}}
function doSub(){{
  if(done)return;
  done=true;clearInterval(tmr);
  document.getElementById('sbtn').disabled=true;
  document.getElementById('wn').style.display='none';
  let c=0,w=0,sk=0;
  Q.forEach((q,qi)=>{{
    const a=UA[qi];
    const bs=document.querySelectorAll('#o'+qi+' .opt');
    bs.forEach(b=>b.disabled=true);
    bs[q.correct_index].classList.remove('sel');
    bs[q.correct_index].classList.add('correct');
    if(a===null)sk++;
    else if(a===q.correct_index)c++;
    else{{bs[a].classList.remove('sel');bs[a].classList.add('wrong');w++;}}
    const t=document.getElementById('t'+qi);
    if(t)t.classList.add('show');
  }});
  const pct=Math.round(c/TOT*100);
  document.getElementById('ms').textContent=c+'/'+TOT;
  document.getElementById('mp').textContent=pct+'% · '+(pct>=40?'उत्तीर्ण ✓':'अनुत्तीर्ण ✗');
  document.getElementById('mi').textContent=pct>=75?'🏆':pct>=50?'🎯':pct>=40?'👍':'📚';
  document.getElementById('mh').textContent=pct>=75?'शानदार!':pct>=50?'बहुत अच्छे':pct>=40?'अच्छा प्रयास':'और मेहनत करें';
  document.getElementById('mc').textContent=c;
  document.getElementById('mw').textContent=w;
  document.getElementById('mk').textContent=sk;
  document.getElementById('ov').classList.add('show');
}}
function closeM(){{
  document.getElementById('ov').classList.remove('show');
  const fw=document.querySelector('.opt.wrong');
  if(fw)fw.closest('.qcard').scrollIntoView({{behavior:'smooth',block:'center'}});
}}
build();updP();startTmr();
</script>
</body>
</html>"""


def generate_test_series(questions, title, out_path):
    timer = max(90 * 60, len(questions) * 90)
    html = TS_PAGE.format(
        title=title, total=len(questions),
        qjson=json.dumps(questions, ensure_ascii=False),
        timer=timer, font=FONT_LINK, css=SHARED_CSS,
    )
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)


# ── VERCEL CONFIG ────────────────────────────────────────────────────────────

def write_vercel_json(root):
    cfg = {"outputDirectory": "output", "cleanUrls": True}
    p = os.path.join(root, 'vercel.json')
    with open(p, 'w') as f:
        json.dump(cfg, f, indent=2)
    return p


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    root = os.path.abspath(os.path.dirname(__file__))
    out_root = os.path.join(root, 'output')
    os.makedirs(os.path.join(out_root, 'pyq'), exist_ok=True)
    os.makedirs(os.path.join(out_root, 'test_series'), exist_ok=True)

    pyq_papers, ts_papers = [], []

    # ── PYQ: process HTML files ──────────────────────────────────────────────
    for folder in ['pyq']:
        d = os.path.join(root, folder)
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.lower().endswith('.html'):
                continue
            src = os.path.join(d, fname)
            title, slug, year = _html_meta(src)
            print(f'[PYQ] {title}')
            qs = parse_html_questions(src)
            if not qs:
                print('  → no questions, skipping'); continue
            out = os.path.join(out_root, 'pyq', f'{slug}_quiz.html')
            generate_pyq(qs, title, out)
            print(f'  → {len(qs)} questions  →  {os.path.relpath(out, root)}')
            pyq_papers.append({'title': title, 'slug': slug, 'year': year, 'count': len(qs)})

    # ── Test Series: process PDF files ───────────────────────────────────────
    if fitz is None:
        print('\nWARNING: PyMuPDF not installed, skipping PDF test series')
    else:
        ts_dir = os.path.join(root, 'test series')
        if not os.path.isdir(ts_dir):
            ts_dir = os.path.join(root, 'test_series')
        if os.path.isdir(ts_dir):
            for fname in sorted(os.listdir(ts_dir)):
                if not fname.lower().endswith('.pdf'):
                    continue
                src = os.path.join(ts_dir, fname)
                title, slug = _pdf_meta(src)
                print(f'[PDF] {title}')
                try:
                    qs = parse_pdf_questions(src)
                except Exception as e:
                    print(f'  → ERROR: {e}'); continue
                if len(qs) < PDF_MIN_QS:
                    print(f'  → only {len(qs)} questions, skipping'); continue
                out = os.path.join(out_root, 'test_series', f'{slug}_quiz.html')
                generate_test_series(qs, title, out)
                print(f'  → {len(qs)} questions  →  {os.path.relpath(out, root)}')
                ts_papers.append({'title': title, 'slug': slug, 'year': '', 'count': len(qs)})

    # Also add PYQ papers as test series (same questions, different UX)
    print('\n[Test Series from PYQ HTML]')
    for p in pyq_papers:
        src = os.path.join(root, 'pyq',
                           next(f for f in os.listdir(os.path.join(root, 'pyq'))
                                if f.endswith('.html') and p['year'] in f))
        qs = parse_html_questions(src)
        slug = p['slug'] + '_mock'
        title = p['title'] + ' — मॉक टेस्ट'
        out = os.path.join(out_root, 'test_series', f'{slug}_quiz.html')
        generate_test_series(qs, title, out)
        print(f'  → {p["title"]}  →  {os.path.relpath(out, root)}')
        ts_papers.append({'title': title, 'slug': slug, 'year': p['year'], 'count': p['count']})

    # ── Index page ───────────────────────────────────────────────────────────
    idx = generate_index(pyq_papers, ts_papers, out_root)
    print(f'\n[Index] {os.path.relpath(idx, root)}')

    # ── vercel.json ──────────────────────────────────────────────────────────
    vcfg = write_vercel_json(root)
    print(f'[Vercel] {os.path.relpath(vcfg, root)}')

    print(f'\n✓ Done! PYQ: {len(pyq_papers)}, Test Series: {len(ts_papers)}')
    print(f'  Open: output/index.html')


if __name__ == '__main__':
    main()
