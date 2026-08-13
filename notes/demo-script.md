# The demo script — what the judge sees, in order

The submission video is cut by `python3 -m cinema demo` from `cinema/demo.py:storyboard`,
so this file is the argument and that function is the artefact. They must agree: change
one and change the other in the same edit. Nothing here is narration to be read aloud —
the video has no voice track. Every word below is drawn on the screen and repeated in
`out/demo.srt`.

## What the script is written against

Devpost judges on four criteria of equal weight, and there is no fifth thing to optimise:

| Tag | Criterion |
|---|---|
| **TECH** | Technological Implementation |
| **DESIGN** | Design |
| **IMPACT** | Potential Impact |
| **IDEA** | Quality of the Idea |

Three hard constraints sit above taste:

- **180 seconds.** Devpost evaluates the first three minutes and truncates the rest without
  telling anybody. `storyboard` refuses a longer cut before a frame is encoded, and `build`
  re-probes the finished file.
- **Nothing is typed in.** Every figure on a card is read from `out/score.json` and
  `out/continuity.json` or priced through `pricing.py`, and both console panels are the real
  stdout of `check` and `score`, captured while the video builds. A worse run has to make a
  worse video.
- **The reader is named beside its score.** The run in the video is the `pixels` stand-in, so
  the video says so, in the video, on its own card.

## The beat sheet

Timings are the panel lengths in `storyboard`; the clip's length is the film's own, probed
from `out/cut.mp4`. A judge who stops watching at any point should already have seen a
result.

| # | At | For | Kind | What is on screen | Aimed at |
|---|---|---|---|---|---|
| 1 | 0:00 | 9s | card | "Everyone generates the film. Nobody checks it." — one paragraph on what a continuity break is, and the disclosure that an agent built this. | **IDEA** |
| 2 | 0:09 | 8s | still | The first repaired shot's before/after plate. The checker's own finding, on screen, before anything is explained. | **IDEA**, **IMPACT** |
| 3 | 0:17 | 40s | clip | The film itself, captioned with its title, shot count and the number of breaks planted in it. | **DESIGN** |
| 4 | 0:57 | 10s | card | "What the checker is handed" — one bible writes the prompt and the questions; the checker never gets the answer key, the canon or the shot's declared state. | **TECH** |
| 5 | 1:07 | 22s | console | Real stdout of `python3 -m cinema check`. | **TECH** |
| 6 | 1:29 | 12s | console | Real stdout of `python3 -m cinema score`. | **TECH** |
| 7 | 1:41 | 9s | card | "N planted, N found" — the scorer's own sentences, the cell count, the reader's name. | **TECH** |
| 8 | 1:50 | 9s each | still | One before/after plate per repaired shot, in shot order. | **DESIGN** |
| 9 | 2:08 | 11s | card | "Only the broken shots are re-rendered" — the repair is read off the finding, and it is a layer over the spec rather than an edit to it. | **TECH** |
| 10 | 2:19 | 11s | card | "Checking costs a rounding error of generating" — the Veo pass and the Gemini pass, both priced from Google's published rates. | **IMPACT** |
| 11 | 2:30 | 10s | card | "What this score is, and what it is not" — the `pixels` reader proves the pipeline and is not the detection; detection is Gemini on Vertex AI, written and unrun. | **TECH** |
| 12 | 2:40 | 9s | card | The four commands, the page and the repo. | **DESIGN** |

Beat 8 repeats beat 2's plate on purpose. The first showing is the hook and carries no
explanation; the second lands after the judge has watched the checker find it, and by then
the same picture means something different.

## Why the order is this one

**The first thirty seconds decide the presentation score, so a result has to land inside
them.** Until 2026-08-13 the cut opened with the hook card and then played the whole film,
which put the judge 21 seconds into placeholder footage at the half-minute mark with no
evidence that anything worked. Beat 2 was added to fix exactly that: the payoff is on screen
at 0:09, and the film that follows is then something the judge is watching *for* a reason.

**The film is not trimmed.** It is 40 seconds and it is a quarter of the running time, which
is a real cost while the renderer is the placeholder. It stays whole for two reasons: the
cut is the subject the entry is about, and a shortened window would break the refusal that
stops a long film silently pushing the video past three minutes. When Veo footage replaces
the boxes, this beat stops being a cost and becomes the strongest thirty seconds in the cut.

**The two console panels are next to each other and neither is narrated.** They are the
whole Technological Implementation argument: the tool runs, in public, and prints what it
found. A card summarising them would be a claim; the capture is evidence.

**The honesty card is late but it is not last.** It has to be after the score, or it reads as
a disclaimer nobody connects to a number, and it has to be before the closing card, or the
video ends on a caveat.

## What the script does not yet cover

- **The hosted page never appears in the video.** `https://joemuller.com/continuity-checker/`
  is the entry's platform under Devpost's "must run on web, Android or iOS" rule, and its
  shot inspector is the best Design evidence the project owns. Putting it on screen needs a
  screenshot taken at build time from the published `docs/`, which means a headless browser
  in a build that is otherwise ffmpeg-only, plus a rule for what happens when the shot is
  older than the page. That is its own piece of work, not a line in this file.
- **Everything here is the `pixels` run.** When the Vertex AI credential lands (#1008), the
  video is rebuilt rather than edited: the numbers, the console captures and the honesty card
  all move by themselves, which is the point of building it this way.
