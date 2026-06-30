# Task: Generate a Resume Flowchart — Human + AI Collaboration Process

## Goal

Generate a clean, simple, professional flowchart for page 2 of my resume. The purpose is **not** to explain the technical details of the project — it's to show **how I worked with an AI agent (Claude Code)** to complete a quant research project. A recruiter should look at this for 5 seconds and understand: "this person knows how to direct and supervise an AI agent, not just prompt it once and accept whatever comes back."

**This is the most important instruction: keep it simple.** Do not include detailed statistics, percentages, or technical jargon (no "calibration error," no specific numbers like "9.8%"). The previous version was too dense and read like a technical report, not a resume graphic. Strip almost all project-specific detail — this diagram is about the **collaboration process**, not the research findings.

## Style Reference

Two reference images are provided in this folder: `project_flowchart.png` (previous draft — do not reuse its dense text-box style) and `images.png` (structural reference — **follow this one's layout logic**).

From `images.png`, copy this structural pattern:
- The page is divided into **vertical swimlane columns** with thin vertical divider lines and a column header label at the top of each lane
- Flow moves top-to-bottom within a lane, and sideways between lanes via arrows
- Decision points are diamond shapes with "yes/no" (or similar) branching, including **feedback loops that go back to an earlier step** when the answer is "no"
- Boxes are simple rectangles, thin black outline, no fill color or very light fill, no shadows or gradients
- Minimal text per box — a few words, not full sentences

## Content Structure: Two Swimlanes

**Lane 1 (left): "Me"** — represents human direction, review, and decision-making
**Lane 2 (right): "AI (Claude Code)"** — represents execution: writing code, pulling data, running models, generating analysis

The flow should zigzag between the two lanes to show back-and-forth collaboration, not a one-way handoff. Use this sequence (keep wording short, plain English, no jargon):

1. **[Me]** Define research question — "Can I find a tradeable price gap in a sports prediction market?"
2. **[AI]** Collect data + build prediction model
3. **Decision diamond:** "Model accurate enough?"
   - No → **[AI]** Investigate cause, revise model → loop back to step 3
   - Yes → continue to step 4
4. **[AI]** Compare model output to live market prices, run backtest
5. **Decision diamond:** "Result makes sense?"
   - No → **[Me]** Flag the anomaly, ask AI to re-verify → **[AI]** re-check data/logic → loop back to step 5
   - Yes → continue to step 6
6. **[Me]** Review final result, decide whether to accept the conclusion
7. **Final box (spans both lanes or sits at the bottom, neutral tone):** "Conclusion: strategy signal was real, but trading costs outweighed it — a complete, well-supported research finding"

Do not add more steps than this. Do not add specific numbers, model names, or fee figures. The point is the *shape of the collaboration*, not the research result itself.

## Caption / Legend

Add one small line at the bottom, plain text, no box around it:

> AI executed the technical work. I directed the research, reviewed results at each checkpoint, and decided when to revise or accept.

## Technical Requirements

- **Language:** All English.
- **Output formats:** PNG (300 dpi) and a vector format (PDF or SVG).
- **Color:** Black/dark gray lines and text only, on white background. No color fills, no gradients, no decorative icons. This should look like it could appear in a clean technical paper or a McKinsey-style deck, not a marketing graphic.
- **Font:** System sans-serif (Helvetica/Arial), consistent weight throughout except bold for the two lane headers ("Me" / "AI (Claude Code)").
- **Size:** Should fit comfortably in roughly half a page when placed on resume page 2 — landscape orientation preferred, since two side-by-side lanes work better wide than tall.

## Process

1. Look at `images.png` first and confirm you understand the swimlane + decision-diamond structure before writing any code.
2. Build a first draft using matplotlib (or similar) as a quick wireframe — simple boxes and arrows, no styling polish yet. Show me this draft before refining.
3. Once content and layout are confirmed, refine styling to match the plain black-and-white technical-diagram look described above.
4. Output final PNG + vector file.
5. Tell me the file paths in one short sentence. No design rationale needed unless I ask.

## Acceptance Criteria

- A reader who has never seen this project should understand, within seconds, that this person directed an AI agent through a research project with real checkpoints — not that they "vibe-coded" something or that AI did everything unsupervised.
- The diagram should look intentionally minimal — if in doubt, remove text rather than add it.
- No specific project statistics should appear anywhere in the diagram.