# AGENT.md — MCQ Quiz App Builder

## Project Overview

This project converts HTML question-paper files into interactive MCQ quiz apps.
There are **two folders**, each with different UX behavior:

```
project/
├── test_series/      → Mock test mode  (answers shown AFTER full test)
├── pyq/              → PYQ mode        (answers shown IMMEDIATELY on click)
├── AGENT.md          → This file
└── output/           → Generated HTML quiz apps go here
```

---

## Input File Format

All input files are HTML pages scraped from **hindisarang.com** (or similar sites).
Questions are encoded in the **Jetpack Quiz** widget format.

### HTML Structure of Each Question

```html
<div class="jetpack-quiz quiz">

  <!-- The question text -->
  <div class="jetpack-quiz-question question" tabindex="-1">
    1. 'साखी' किस कवि का काव्य-संग्रह है?
  </div>

  <!-- Wrong option -->
  <div class="jetpack-quiz-answer answer">
    केदारनाथ सिंह
  </div>

  <!-- Wrong option -->
  <div class="jetpack-quiz-answer answer">
    कुँवर नारायण
  </div>

  <!-- Wrong option -->
  <div class="jetpack-quiz-answer answer">
    मलयज
  </div>

  <!-- CORRECT option — marked with data-correct="1" -->
  <div class="jetpack-quiz-answer answer" data-correct="1">
    विजयदेव नारायण साही

    <!-- Explanation is nested INSIDE the correct answer div -->
    <div class="jetpack-quiz-explanation explanation">
      'साखी' काव्य-संग्रह कवि विजयदेव नारायण साही का है।
      मछलीघर, संवाद तुमसे, आवाज़ हमारी जाएगी आदि उनके अन्य काव्य संग्रह हैं।
    </div>
  </div>

</div>
```

### Parsing Rules

| Field       | How to Extract                                           |
|-------------|----------------------------------------------------------|
| Question    | Text content of `.jetpack-quiz-question`                 |
| Options     | Text content of each `.jetpack-quiz-answer` (strip inner explanation div first) |
| Correct Ans | The `.jetpack-quiz-answer` that has `data-correct="1"`   |
| Explanation | Text inside `.jetpack-quiz-explanation` (inside correct answer) |

> ⚠️ **Important:** The explanation div is nested INSIDE the correct answer div.
> When extracting the option text, always strip/exclude the inner `.jetpack-quiz-explanation` text.

---

## Folder Behaviors

### 1. `test_series/` — Mock Test Mode

**UX Rule:** User answers ALL questions first. Answers & explanations are revealed only AFTER submitting the full test.

**Features to implement:**
- Show all questions on one page (or paginated)
- Each option is a clickable radio button — selection is stored but no feedback given
- A **"Submit Test"** button at the end
- After submission:
  - Correct options turn **green**
  - Wrong selected options turn **red**
  - Unselected correct option is highlighted in green (if user got it wrong)
  - Explanation text appears below each question
  - A **Score Card** is shown: `Score: 23/125`, percentage, pass/fail
- No option change allowed after submission

**Timer (optional):** Show countdown timer (e.g. 2 hours for 125 Qs)

**State machine:**
```
UNANSWERED → SELECTED (click option) → [Submit] → EVALUATED
```

---

### 2. `pyq/` — Previous Year Questions Mode

**UX Rule:** Instant feedback. As soon as user clicks any option, the answer is shown.

**Features to implement:**
- Questions shown one at a time OR all at once (scrollable)
- On clicking any option:
  - If correct → that option turns **green** ✅
  - If wrong → clicked option turns **red** ❌, correct option turns **green** ✅
  - Explanation text appears immediately below
- Once an option is clicked, all options for that question are **disabled** (no re-attempt)
- A small live score tracker at top: `Attempted: 12 | Correct: 9 | Wrong: 3`

**State machine:**
```
UNANSWERED → ANSWERED (click option → immediate reveal)
```

---

## Output Format

Each input HTML file → one output HTML file (self-contained, no external dependencies).

**Output file naming:**
```
test_series/up_tgt_hindi_2013.html  →  output/test_series/up_tgt_hindi_2013_quiz.html
pyq/up_tgt_hindi_2013.html          →  output/pyq/up_tgt_hindi_2013_quiz.html
```

**Output file requirements:**
- Single HTML file with inline CSS + JS (no CDN, works offline)
- Hindi text must render correctly (UTF-8, use system fonts or Noto Sans Devanagari)
- Mobile responsive
- Dark/Light mode support (optional, nice-to-have)

---

## Agent Workflow

When given a new HTML file, the agent must:

1. **Detect folder** — Is the source file in `test_series/` or `pyq/`?
2. **Parse questions** — Extract all `.jetpack-quiz` blocks from the HTML
3. **Build question objects** — For each block:
   ```json
   {
     "id": 1,
     "question": "साखी किस कवि का काव्य-संग्रह है?",
     "options": [
       "केदारनाथ सिंह",
       "कुँवर नारायण",
       "मलयज",
       "विजयदेव नारायण साही"
     ],
     "correct_index": 3,
     "explanation": "साखी काव्य-संग्रह कवि विजयदेव नारायण साही का है।"
   }
   ```
4. **Generate HTML app** — Based on folder mode (test_series vs pyq)
5. **Save output** — To the appropriate output subfolder

---

## Edge Cases to Handle

| Scenario | Handling |
|----------|----------|
| `data-correct="1"` appears on first option | Index = 0, still works |
| Explanation contains HTML tags (`<strong>`, `<em>`) | Preserve inner HTML of explanation |
| Question text has numbering like `1.` or `1)` | Keep as-is in display |
| Multiple correct answers (rare) | Treat first `data-correct="1"` as correct |
| Empty explanation | Show no explanation box for that question |

---

## Tech Stack for Generated Apps

- **Pure HTML + CSS + Vanilla JS** (no React, no framework)
- Inline everything — single file output
- Use CSS custom properties for theming
- Font: `font-family: 'Noto Sans Devanagari', sans-serif` or system fallback

---

## Example: Parsed Data from UP TGT Hindi 2013

Source: `hindisarang_com__up-tgt-hindi-question-paper-2013_.html`
Total questions: **125**
Subject: **Hindi Literature & Grammar**
Exam: **UP TGT Hindi 2013** (held 15-01-2015)

Sample parsed question:
```json
{
  "id": 1,
  "question": "1. 'साखी' किस कवि का काव्य-संग्रह है?",
  "options": [
    "केदारनाथ सिंह",
    "कुँवर नारायण",
    "मलयज",
    "विजयदेव नारायण साही"
  ],
  "correct_index": 3,
  "explanation": "'साखी' काव्य-संग्रह कवि विजयदेव नारायण साही का है। मछलीघर, संवाद तुमसे, आवाज़ हमारी जाएगी आदि उनके अन्य काव्य संग्रह हैं।"
}
```

---

## Summary Table

| Feature              | `test_series/`         | `pyq/`                    |
|----------------------|------------------------|---------------------------|
| Answer reveal timing | After full submission  | Immediately on click      |
| Re-attempt allowed   | No                     | No                        |
| Score shown          | End of test            | Live tracker at top       |
| Explanation          | After submission       | Right after clicking      |
| Timer                | Yes (recommended)      | No                        |
| Use case             | Exam simulation        | Study / quick revision    |
