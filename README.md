# Continuity checker, for Agentic Cinema

Everyone generating film with a model has the same problem: the character's jacket is red
in shot two and blue in shot three, and nothing in the pipeline notices. This entry checks
the film it just made, finds the shots that broke, and re-renders only those.

Checking is close to free next to generating. Reading a whole 40-second film with Gemini
2.5 Pro costs about $0.04, against $16.00 to render it at full quality
([`notes/render-cost.md`](notes/render-cost.md)). At that ratio it is hard to justify not
checking.

## Where the work is up to

The pipeline runs end to end and exports a playable cut. Shots are drawn, not generated:
the renderer is ffmpeg boxes standing in for Veo, which lets the whole thing be built and
tested before any second of video is billed. Swap the backend and the same commands render
for real.

The placeholder cut is also the checker's first fixture. It carries two continuity breaks
put there on purpose: the jacket changes colour in shot three, and the parcel vanishes in
shot four. `film.yaml` holds the answer key the checker is scored against but never sees.

## The shot bible

A checker with no ground truth is only asking a model for an opinion. `film.yaml` carries a
bible: the characters and props, and for each tracked attribute the words an answer may use
and the rule that says whether a change is an error. It writes the generation prompt as
well as the check, so the thing the film was asked for and the thing the check looks for
are one sentence rather than two that drift.

The rule is the part a longer prompt cannot do. Not everything that changes is a mistake:

| rule | means | in this film |
|---|---|---|
| `constant` | the value must never leave `canon` | the courier's jacket, the parcel |
| `progressive` | the value moves along `order` and never back | the light, dusk then night |
| `declared` | constant, except at the shots the author lists in `changes_at` | — |

So the sun setting between shot three and shot four is the story, and the jacket turning
blue is a break. A checker that reports both finds nothing worth acting on.

One function judges the film, and it is handed two different readings of it: the state
declared in `film.yaml`, which gives the answer key, and the state Gemini reads out of the
frames, which gives the finding. The spec refuses to load if the hand-written answer key
and the shots disagree, so fixing a shot means retiring its answer-key entry in the same
edit.

## Running it

```sh
python3 -m cinema info        # the spec, and the answer key
python3 -m cinema bible       # the ground truth, and the questions the checker asks
python3 -m cinema bible --prompts    # what each shot is actually generated from
python3 -m cinema build       # render what has changed, join it into out/cut.mp4
python3 -m cinema render --shot s03    # re-render one shot; this is the demo
python3 -m cinema timings     # wall clock and spend, per shot
python3 -m unittest discover -s tests
```

Rendering is cached and resumable. A shot is redrawn when its inputs change and skipped
when they have not, so fixing the one broken shot costs one shot: on Veo 3.1 Standard that
is $3.20 rather than $16.00. The ledger is written after every shot, so a killed pass costs
one render rather than the whole film, and each output is checked against its own digest —
delete a shot and it comes back.

What counts as an input is the backend's to declare. Veo reads the model tier, the seed and
the reference image, so a fixed shot three correctly makes shots four and five stale, since
shot three's last frame is shot four's reference. The placeholder backend reads none of
them, so switching tiers while iterating does not redraw five identical boxes.

It needs `ffmpeg`, `ffprobe` and `pyyaml`, and it runs without any credential.

## How it is laid out

| | |
|---|---|
| `film.yaml` | the five shots, their continuity state, the bible, and the planted breaks |
| `cinema/bible.py` | the ground truth: vocabulary, the break rules, and the prompt it writes |
| `cinema/spec.py` | reads the spec and refuses one that could not be re-rendered |
| `cinema/render.py` | the cached, resumable render loop, and the ledger it writes |
| `cinema/pricing.py` | Veo's per-second rates, so a render's cost is known before it runs |
| `cinema/backends/placeholder.py` | free local shots, so the pipeline can be built offline |
| `cinema/backends/veo.py` | Veo 3.1 on Vertex AI. Not wired up: it needs a budget |
| `cinema/assemble.py` | joins shots by stream copy, and probes what came out |
| `notes/render-cost.md` | what a shot costs, priced off Google's own tables |

Every shot is eight seconds. Veo's reference-image-to-video mode only accepts eight, and
the re-render step feeds the previous shot's last frame in as its reference, so a shorter
shot would be one the pipeline could never fix. `spec.py` rejects any other length.

The Veo backend refuses to run without an explicit flag. Rendering costs money and the agent
building this has a spend cap of zero, so that guard lives in the code where it can stop a
command.

---

Built by an autonomous agent working for Joe Muller.
