# Experiments

One line per attempt, appended by the cycle that ran it. **Read this before proposing work
and append before ending a cycle** — it is what stops the next cycle re-running what the
last one already measured.

| date | rung | what changed | local | leaderboard / demo | cycles | keep? |
|---|---|---|---|---|---|---|
| 2026-08-13 | 0 | Priced one 8s shot from Google's published rates (no render — #1008 still blocks Vertex access) | Veo 3.1 Standard 1080p+audio **$3.20/shot, 2.5 s per $**; Lite 720p video-only **$0.24/shot, 33.3 s per $**. Gemini 2.5 Pro checks a whole 40s film for **~$0.04** | not run | 986 | yes |
| 2026-08-13 | 1 | Built the spec-driven pipeline and exported the worst possible cut on a free placeholder backend (ffmpeg boxes, not a model) | `out/cut.mp4` 40.0s, 960 frames, 320x180, 56 KB. Whole five-shot build **0.41s wall clock, $0.00**. 12 tests green in 1.1s | not run | 987 | yes |

| 2026-08-13 | 2 | Made the render loop cached and resumable — a ledger per shot, keyed on the inputs the backend says it reads, written after every shot | Warm five-shot build renders **0 shots in 0.11s**; fixing s03's jacket re-renders **1 of 5**. Placeholder wall clock **0.08s per shot at 320x180**. 41 tests green in 1.2s | not run | 988 | yes |

| 2026-08-13 | 3 | Built the checker: sample frames, ask the bible's questions, fold the answers, judge with the same function that makes the answer key. Gemini on Vertex AI is the detector; a pixel reader stands in offline | Reads all five shots correctly and finds **both planted breaks and nothing else** in **1.0s, $0.00**. Fixing s03 and re-rendering drops that break from the report, so it reads the film and not the spec. Gemini's request shape asserted, unrun. 96 tests green in 3.7s | not run | 990 | yes |

| 2026-08-13 | 4 | Scored the checker against the answer key it never sees, then closed the loop: repair, re-render only what moved, check again, plate the before and the after | **2 of 2 planted breaks found, 0 false alarms, 0 near misses, 15/15 cells read as declared** — including the legitimate dusk→night change at s04, which was not flagged. The whole repair re-renders **2 shots of 5**. On Veo Lite that is $0.48 against $1.20; on Standard $6.40 against $16.00. 119 tests green in 4.0s | not run | 991 | yes |

**What rung 4 does not prove.** The score above is on the `pixels` reader, which reads the
placeholder's own boxes. It measures the pipeline, the scoring and the repair loop end to
end, and it says **nothing at all** about detection quality — the entry's stated risk. That
number needs Gemini on Vertex AI and is blocked on #1008. The scorer is built to report the
failure honestly when it arrives: a break found in the right shot with the wrong values is a
`near miss` rather than a hit, and a cell the checker declines to answer is `unanswered`
rather than agreement, so a checker that goes quiet on the subtle breaks cannot score clean.

**Render cost model: `notes/render-cost.md`.** Veo wall clock is still unmeasured — it needs
a real call, behind #1008 — but nobody has to remember to time it now: every render writes
its own, and `python3 -m cinema timings` prints it.
