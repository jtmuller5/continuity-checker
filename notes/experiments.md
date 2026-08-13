# Experiments

One line per attempt, appended by the cycle that ran it. **Read this before proposing work
and append before ending a cycle** — it is what stops the next cycle re-running what the
last one already measured.

| date | rung | what changed | local | leaderboard / demo | cycles | keep? |
|---|---|---|---|---|---|---|
| 2026-08-13 | 0 | Priced one 8s shot from Google's published rates (no render — #1008 still blocks Vertex access) | Veo 3.1 Standard 1080p+audio **$3.20/shot, 2.5 s per $**; Lite 720p video-only **$0.24/shot, 33.3 s per $**. Gemini 2.5 Pro checks a whole 40s film for **~$0.04** | not run | 986 | yes |
| 2026-08-13 | 1 | Built the spec-driven pipeline and exported the worst possible cut on a free placeholder backend (ffmpeg boxes, not a model) | `out/cut.mp4` 40.0s, 960 frames, 320x180, 56 KB. Whole five-shot build **0.41s wall clock, $0.00**. 12 tests green in 1.1s | not run | 987 | yes |

| 2026-08-13 | 2 | Made the render loop cached and resumable — a ledger per shot, keyed on the inputs the backend says it reads, written after every shot | Warm five-shot build renders **0 shots in 0.11s**; fixing s03's jacket re-renders **1 of 5**. Placeholder wall clock **0.08s per shot at 320x180**. 41 tests green in 1.2s | not run | 988 | yes |

**Render cost model: `notes/render-cost.md`.** Veo wall clock is still unmeasured — it needs
a real call, behind #1008 — but nobody has to remember to time it now: every render writes
its own, and `python3 -m cinema timings` prints it.
