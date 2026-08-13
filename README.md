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

## Running it

```sh
python3 -m cinema info        # the spec, and the answer key
python3 -m cinema build       # render five shots, join them into out/cut.mp4
python3 -m cinema render --shot s03    # re-render one shot; this is the demo
python3 -m unittest discover -s tests
```

It needs `ffmpeg`, `ffprobe` and `pyyaml`, and it runs without any credential.

## How it is laid out

| | |
|---|---|
| `film.yaml` | the five shots, their continuity state, and the planted breaks |
| `cinema/spec.py` | reads the spec and refuses one that could not be re-rendered |
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
