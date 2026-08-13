# What a shot costs

The budget the whole entry plans against. Read before proposing any render work.

Prices read 2026-08-13 from Google's own pages, not from a summary:

- `https://cloud.google.com/vertex-ai/generative-ai/pricing`, the Veo and Gemini 2.5 tables.
  The page prints the Veo unit as `$0.40 / 1 count` and never says what a count is.
- `https://ai.google.dev/gemini-api/docs/pricing`, the same numbers under the heading
  "Paid Tier, **per second** in USD". **So one count is one second of output video.**
- `https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/veo/3-1-generate`,
  the model specs.

`cloud.google.com/vertex-ai/...` now 301s to `docs.cloud.google.com/...`, and the product is
branded **Gemini Enterprise Agent Platform**. WebFetch returns "content truncated" on both
pricing pages; `curl` plus a tag strip is the way to read them.

## Veo 3.1, per second of output

Veo 3 shut down 2026-06-30, so **Veo 3.1 is the only choice**. Model ids:
`veo-3.1-generate-001`, `veo-3.1-fast-generate-001`, `veo-3.1-lite-generate-001`.

| Model | 720p | 1080p | 4K |
|---|---|---|---|
| 3.1 Standard, video + audio | $0.40 | $0.40 | $0.60 |
| 3.1 Standard, video only | $0.20 | $0.20 | $0.40 |
| 3.1 Fast, video + audio | $0.10 | $0.12 | $0.30 |
| 3.1 Fast, video only | $0.08 | $0.10 | $0.25 |
| 3.1 Lite, video + audio | $0.05 | $0.08 | not supported |
| 3.1 Lite, video only | $0.03 | $0.05 | not supported |

## One 8-second shot, and seconds per dollar

Joe's five shots at 8 seconds each is 40 seconds of film per pass.

| Tier | 1 shot (8s) | 5-shot pass (40s) | Seconds per $ | 5-shot passes per $100 |
|---|---|---|---|---|
| Standard 1080p + audio | **$3.20** | **$16.00** | 2.5 | 6.2 |
| Fast 1080p + audio | $0.96 | $4.80 | 8.3 | 20.8 |
| Fast 720p, video only | $0.64 | $3.20 | 12.5 | 31.2 |
| Lite 720p + audio | $0.40 | $2.00 | 20.0 | 50.0 |
| Lite 720p, video only | **$0.24** | **$1.20** | 33.3 | 83.3 |

A failed generation is free: "You will only be charged if your video is successfully
generated."

## Detection is not the cost. Generation is.

Gemini 2.5 bills video input at **258 tokens per second** of clip, sampled at 1 fps.
A whole 40-second film is 10,320 input tokens.

| Checker model | Input $/1M | Output $/1M | One whole-film check |
|---|---|---|---|
| Gemini 2.5 Pro | $1.25 | $10.00 | ~$0.04 |
| Gemini 2.5 Flash | $0.30 | $2.50 | ~$0.01 |

(Allowing 3,000 output tokens for the reasoning and the JSON verdict.)

**Checking a film costs about 0.3% of rendering it**: one Standard pass is $16.00 against
$0.04 to check it. Run the checker on Pro and never think about its cost again. It is also
the argument the entry itself makes: catching a break is 370 times cheaper than the re-render
it saves.

## The budget to ask for, and how it is spent

$77 of the $100 credit, leaving headroom:

| | Cost |
|---|---|
| 25 iteration passes, Lite 720p video only, $1.20 each | $30.00 |
| Detection over all of it, Gemini 2.5 Pro | ~$2.00 |
| 2 final passes, Standard 1080p + audio, $16.00 each | $32.00 |
| 4 re-rendered shots for the before/after, Standard, $3.20 each | $12.80 |
| **Total** | **~$77** |

Iterate on Lite and spend Standard only on what a judge watches. A single careless habit of
iterating on Standard burns the whole credit in six passes.

## What this decides about the build

- **Every shot is 8 seconds.** Not a style choice: `veo-3.1-generate-001` says
  "reference image to video only supports 8 seconds", and the re-render step feeds the
  previous shot's last frame in as a reference image. A 4- or 6-second shot cannot be
  re-rendered that way, which kills the demo. The shot bible (#1012) must pin 8s.
- Region is **us-central1 only**. Quota is 50 online prediction requests per model per
  minute; at most 4 output videos per prompt; 24 fps; 16:9 or 9:16.
- Audio is a per-second surcharge, not a flag, and it doubles Standard's price. Decide once
  whether the demo film has sound.

## Still unmeasured

**Wall-clock seconds per shot on Veo.** It needs a real Vertex AI call, which is behind
#1008 (credit, billed project, permission to spend).

Nobody has to remember to time it. `cinema/render.py` writes the wall clock of every render
into `out/renders.json`, and `python3 -m cinema timings` prints the mean per backend, tier
and resolution. The first real pass answers this section by itself; the placeholder backend
reads **0.08s per shot at 320x180**, which measures ffmpeg and says nothing about Veo.

## The cache is what protects the credit

The table above prices a *pass*. What is actually spent is priced by how many shots are
re-rendered, and the whole point of this entry is re-rendering one of five. `cinema/render.py`
holds the arithmetic:

| | Standard 1080p + audio |
|---|---|
| First pass, five shots | $16.00 |
| Fixing one caught break, cached | **$3.20** |
| Fixing one caught break, no cache | $16.00 |

At the $100 credit that is the difference between 6 iterations and 31. The prices in
`cinema/pricing.py` come from the tables above, and the ledger records what each render
actually cost, so the number in the demo is read rather than claimed.

## The ceiling, and where each half of it lives

The cache decides how much of a pass is bought. The ceiling decides whether the pass happens
at all, and it is the only thing between a mistyped tier and the credit.

`film.yaml` holds it under `render:`, beside the tier, the seed and the audio flag that the
same block already carries:

```yaml
render:
  tier: lite
  seed: 20260813
  audio: false
  max_spend_usd: 25.00
```

Everything there is overridable for one run (`--tier`, `--seed`, `--resolution`,
`--max-spend`), and `cinema/pricing.py` prices any combination of them. `python3 -m cinema
timings` prints what has actually been spent and what the ceiling is.

`$25.00` buys one Standard five-shot pass at $16.00 and a couple of re-renders at $3.20
each. It is deliberately far below the $100 credit: the ceiling is meant to stop a mistake,
not to ration the work, and raising it is a human's decision.

`cinema/render.py` checks it twice, and the two checks catch different failures.

- `plan_spend()` walks the shots before the first call, decides which ones the cache will
  miss, prices those, and adds the ledger's lifetime total. Over the ceiling, nothing is
  rendered at all. The walk is exact for a chaining backend as well as a free-standing one:
  once a shot is going to be rendered, the digest its successor's cache key is built from
  does not exist yet, so nothing after it can be a hit. The cascade is priced, not guessed.
- The loop re-checks the running total before each shot. A projection is priced off the
  cache, and the cache can go stale between the pricing and the render, so a pass can turn
  out dearer than it quoted. It stops at the shot that would cross rather than finishing.
  Everything already rendered stays on disk and in the ledger, so the next run resumes.

The total the ceiling is measured against is a **lifetime** figure, `spent_usd` in
`out/renders.json`, and not the sum of the shot rows. A re-render overwrites its shot's row,
and that money was still spent. Summing the rows would forget every pass but the last, which
is exactly backwards for a guard against repeated re-rendering. `cinema timings` prints both
and says which is which. A ledger written before this existed is read as what its shots cost,
which under-reads a re-rendered film and is still better than reading it as zero.
