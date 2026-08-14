# Experiments

One line per attempt, appended by the cycle that ran it. **Read this before proposing work
and append before ending a cycle**, because it is what stops the next cycle re-running what the
last one already measured.

| date | rung | what changed | local | leaderboard / demo | cycles | keep? |
|---|---|---|---|---|---|---|
| 2026-08-13 | 0 | Priced one 8s shot from Google's published rates (no render, because #1008 still blocks Vertex access) | Veo 3.1 Standard 1080p+audio **$3.20/shot, 2.5 s per $**; Lite 720p video-only **$0.24/shot, 33.3 s per $**. Gemini 2.5 Pro checks a whole 40s film for **~$0.04** | not run | 986 | yes |
| 2026-08-13 | 1 | Built the spec-driven pipeline and exported the worst possible cut on a free placeholder backend (ffmpeg boxes, not a model) | `out/cut.mp4` 40.0s, 960 frames, 320x180, 56 KB. Whole five-shot build **0.41s wall clock, $0.00**. 12 tests green in 1.1s | not run | 987 | yes |
| 2026-08-13 | 2 | Made the render loop cached and resumable: a ledger per shot, keyed on the inputs the backend says it reads, written after every shot | Warm five-shot build renders **0 shots in 0.11s**; fixing s03's jacket re-renders **1 of 5**. Placeholder wall clock **0.08s per shot at 320x180**. 41 tests green in 1.2s | not run | 988 | yes |
| 2026-08-13 | 3 | Built the checker: sample frames, ask the bible's questions, fold the answers, judge with the same function that makes the answer key. Gemini on Vertex AI is the detector; a pixel reader stands in offline | Reads all five shots correctly and finds **both planted breaks and nothing else** in **1.0s, $0.00**. Fixing s03 and re-rendering drops that break from the report, so it reads the film and not the spec. Gemini's request shape asserted, unrun. 96 tests green in 3.7s | not run | 990 | yes |
| 2026-08-13 | 4 | Scored the checker against the answer key it never sees, then closed the loop: repair, re-render only what moved, check again, plate the before and the after | **2 of 2 planted breaks found, 0 false alarms, 0 near misses, 15/15 cells read as declared**, including the legitimate dusk to night change at s04, which was not flagged. The whole repair re-renders **2 shots of 5**. On Veo Lite that is $0.48 against $1.20; on Standard $6.40 against $16.00. 119 tests green in 4.0s | not run | 991 | yes |
| 2026-08-13 | 5 | Published the two named Devpost artefacts: the MIT repo, and a hosted page whose every figure is read out of the run at publish time | Page **200 at 15,977 bytes**, `assets/cut.mp4` **200 at 56,292 bytes**, both read back with no token. `test_publish` rebuilds `docs/` and diffs it, so a moved run that is not re-published turns the suite red | page live at joemuller.com/continuity-checker | 992 | yes |
| 2026-08-13 | 6 | Cut the demo video out of the run itself: the two console panels are the real stdout of `check` and `score`, captured while the video builds | `out/demo.mp4` **2:41, 1280x720, 846 KB**, plus an English `.srt`. A worse run therefore makes a worse video | not run | 994 | yes |
| 2026-08-13 | 7 | Made the page something a judge operates rather than reads: pick a shot, see the frames, the questions, each answer and the verdict | The run is inlined and never fetched, and the page decides nothing in the browser. The report gained a `questions` field; 10 new tests. This is also what answers the rules requirement to run on web, Android or iOS | page live | 996 | yes |
| 2026-08-13 | 8 | Drew the real call graph into the README as mermaid, read out of the code rather than sketched | 167 tests unchanged, no module touched. The first attempt put the paid nodes in a subgraph, which parsed but laid out **3,122px tall** with edges doubling back; two diagrams plus a `classDef` gave a readable 775x2,072 and 861x494 | README live | 1026 | yes |
| 2026-08-13 | 9 | Checked the diagram's labels rather than its layout | **Two of them named nothing**: `bible.fold` is a string helper, where the stage is `Bible.read`. Rendering proves a diagram lays out, never that a label is real | README live | 1031 | yes |
| 2026-08-13 | 10 | Wrote the beat sheet against the judging criteria, and moved the first repaired shot to 0:09 so a judge who stops at thirty seconds has seen the tool work | 13 beats, one criterion each. Video **169.0s**. 172 tests, up from 168, and the four new ones fail against the old storyboard | video not uploaded | 1040 | yes |
| 2026-08-13 | 11 | Photographed the hosted page into the cut, out of a site published from the current run so the picture cannot be older than the cards beside it | Video **169.0s to 178.0s**, 14 panels, inside the 180s Devpost judges. 188 tests. The frame at 2:08 was extracted and looked at, which is how the caption band was found sitting over the table | video not uploaded | 1041 | yes |
| 2026-08-13 | 12 | Walked the whole submission order through the CLI in one test: build, check, score, fix, revert, build, check, score, publish, demo | 209 tests, up from 188, in **29s at $0.00**. Two mutations were watched failing first: deleting `fixes.clear()`'s unlink gives a "0 planted, 0 found" cut, which is exactly the silent failure the test exists for | not run | 1045 | yes |
| 2026-08-13 | 13 | Rewrote the README's first screen for a judge: the s03 plate, then the page, the video and the dependencies | README 18,788 bytes. Every command it quotes was run first in a throwaway copy with `out/` deleted: `build` **0.5s**, `fix` **1.6s**, both $0.00 | README live | 1049 | yes |
| 2026-08-13 | 14 | Wrote the Veo call. `request()` returns the call as a plain dict and imports nothing, so the shape that decides the bill is asserted with no SDK and no credential | 229 tests, up from 209. Two claims checked by mutation: sending `shot.prompt` instead of `shot.text` turns one red, dropping the previous shot's file turns another. **Still unrun**, behind #1008 | not run | 1059 | yes |
| 2026-08-13 | 15 | Put a ceiling on the paid path: `render.max_spend_usd`, $25.00, priced before the first call and re-checked before every shot | 246 tests. Proved by making the projection lie: the pass stops at s03 with 2 shots rendered and **$3.20 recorded**, and raising the ceiling resumes at s03 rather than paying for s01 again | not run | 1062 | yes |
| 2026-08-13 | 16 | Pinned the dependencies from an AST walk over `cinema/`, not from memory, and added the install block the rules ask for | `PyYAML==6.0.3` and `google-genai==2.18.0`, the second imported only inside `_client()` in two files. `requirements.txt` 525 bytes, with a test that fails if an import appears with no pin | repo live | 1073 | yes |
| 2026-08-13 | 17 | Said what the entry is in the contest's own words: a four-row Perceive, Judge, Act, Verify table naming the real modules | Framing only, no capability added. It found a real fault: a 50-character card heading fitted a 46-character line by luck and ffmpeg draws the overflow off the frame at exit 0, so `demo.HEADING_COLS` now refuses it | page and video rebuilt | 1082 | yes |
| 2026-08-13 | 18 | Ran the four steps as a `google.adk.workflow.Workflow`, with `cinema fix` calling the same functions so there is only one copy of each step | **ADK 2.7.0 runs offline**: a Workflow of FunctionNodes needs no model, no credential and no network, which is what makes this provable at $0.00. `SequentialAgent` is deprecated in its favour | not run | 1084 | yes |
| 2026-08-13 | 19 | Added a second fixture film and let the page pick between films, because one film could only ever break one way | `film-lighthouse` scores **2 of 2**: a progressive attribute running backwards, which a constant rule misses while flagging the sunset, and a declared change that must read as clean. Page 22,697 bytes. Deleting the vocabulary dispatch renders it flat and the checker then misses both breaks and invents one | page live, both films | 1087 | yes |
| 2026-08-13 | 20 | Ran the humanizer pass over every public word, then rebuilt the page and the video from a fresh run rather than editing the output | **130 em dashes removed** across the README, the write-up, 21 modules, both films and the notes. The served page carries **no em or en dash at all**, against 2 before | page live | 1092 | yes |
| 2026-08-13 | R | Read the rules into the project prompt, swept the video frame by frame for third-party marks, and mapped each judging criterion to where the entry loses it | Two findings changed the build: two of the four criteria name the Partner services, so an absent IBM costs score and not only eligibility, and the rules want a project that runs on web, Android or iOS. #1065, #1068, #1072 | not run | see tasks | yes |
| 2026-08-14 | R | Looked for a better idea than the continuity checker, against the playbook's edge list | **None.** Both remaining gaps are Joe's permissions, #1008 and #1018, rather than the concept, so a pivot would spend the last cycles rebuilding what already works. #1089 | not run | see tasks | keep the idea |

**Where it stands, measured 2026-08-14.** 287 tests green in 31.9s, 3 skipped, at $0.00 with no
credential and no network. `out/demo.mp4` is 178.0s at 1280x720, the page serves both films, and
all four Devpost artefacts exist. No hosted Google service has been called yet: the ADK graph
runs offline, and the Veo backend and the Gemini reader are written and unrun.

**What rung 4 does not prove, and rungs 5 to 20 still do not.** Every score above is on the
`pixels` reader, which reads the placeholder's own boxes. It measures the pipeline, the scoring
and the repair loop end to end, and it says **nothing at all** about detection quality, the
entry's stated risk. That number needs Gemini on Vertex AI and is blocked on #1008. The scorer
is built to report the failure honestly when it arrives: a break found in the right shot with
the wrong values is a `near miss` rather than a hit, and a cell the checker declines to answer
is `unanswered` rather than agreement, so a checker that goes quiet on the subtle breaks cannot
score clean.

**The two open gaps are both permissions, not code.** #1008 is Vertex AI, without which no shot
is generated and Gemini has never read a frame. #1018 is IBM Bob, without which the entry is
ineligible for the only track it targets. Neither is worked around by building more.

**Render cost model: `notes/render-cost.md`.** Veo wall clock is still unmeasured, because it needs
a real call, behind #1008. But nobody has to remember to time it now: every render writes
its own, and `python3 -m cinema timings` prints it.
