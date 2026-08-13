# Continuity Checker: the Devpost write-up

The text of the submission. It is kept in the repo rather than only in the form, so the
claims in it sit next to the code that has to back them, and so a later run that changes a
number changes this file too.

- Hosted project: https://joemuller.com/continuity-checker/
- Repository: https://github.com/jtmuller5/continuity-checker (MIT)
- Demo video: `out/demo.mp4`, 2:58, built by `python3 -m cinema demo`. Captions in
  `out/demo.srt`.

---

## Inspiration

Every generative video tool in this hackathon makes a shot. Almost none of them read one
back. Put five generated shots in a row and the courier's jacket turns from red to blue
between shot two and shot three, the parcel he was carrying is gone by shot four, and
nothing in the pipeline notices. The next thing that looks at the film is a person.

That is the gap this fills. The interesting agentic problem in generated film is not
producing another eight seconds of footage. It is deciding which eight seconds are wrong,
and paying to make only those again.

## What it does

Continuity Checker is an agent that sits after the render and before the person. It takes a
finished cut, reads it back frame by frame, decides which shots broke continuity, repairs
those shots and re-renders them, then reads the new cut back to see whether the repair held.

The loop is deterministic, and it is the same four steps every pass:

1. **Perceive.** Sample frames from each shot and put a fixed set of questions to Gemini
   about every one of them.
2. **Judge.** Fold the answers into the shot bible's vocabulary and apply its rules. A
   change counts as a break only when the rule for that attribute says so.
3. **Act.** Read the repair off the finding, then re-render the shots whose inputs moved and
   no others.
4. **Verify.** Read the new cut back and grade the run against a key the reader never saw.

Each finding names the shot, the attribute, what it should have been and what it is, so the
step that acts is reading a correction rather than inventing one. Shots that were already
right are left alone.

Four commands drive it, in this order:

```
python3 -m cinema build     render the film from the shot bible
python3 -m cinema check     read the cut back and report the breaks
python3 -m cinema score     grade that report against a key the checker never saw
python3 -m cinema fix       repair, re-render only what moved, check again
```

On the film in the repo it finds both planted breaks, flags nothing that is not a break,
and re-renders two shots out of five.

The run is also on the web, and you can work through it: pick a shot on the hosted page and
you get the stills the checker sampled, the questions it was handed, what it answered about
each still, and what the grader then made of those answers. Shots that were re-rendered
carry the before and after plate underneath. The page decides nothing in the browser. It
ships the run inlined, and every value on it is lifted out of the two files `cinema score`
reads, so what you are reading is the run itself rather than a second opinion about it.

## How we built it

A shot bible holds the film's continuity canon and each shot's declared state. It writes
the generation prompt and the checker's questions from that one source, so what was asked
for and what is checked cannot drift apart. Drift is the usual way a checker like this
goes quietly wrong.

A change is only a break when the rule says so. An attribute is constant (the jacket, the
parcel), progressive along an order (dusk to night is the story; night back to dusk is a
break), or declared with the shot it changes at. A checker that flags the sunset reports
nothing anyone can act on.

The checker is never shown the answer. It is handed the questions and the vocabulary it
may answer with, and nothing else: no canon, no declared state, no key. Grading runs
afterwards, on the written report, so nothing the grader knows can reach the reader. An
answer outside the vocabulary becomes an unanswered question rather than agreement, and
frames of one shot that contradict each other are marked disputed and kept out of the
judgement instead of settled by a coin toss.

Detection is Gemini on Vertex AI, one call per frame, replying as JSON against an enum
schema. Generation is Veo 3.1. Nothing else in the runtime is a model, which is what the
rules require.

The loop around those calls is plain Python and deterministic on purpose. The steps run in
one order, each writes its artefact to disk before the next one reads it, and the whole run
reproduces from a clean checkout with no network and no key. If an agent is deciding what
you pay to render a second time, you have to be able to run it again and get the same
answer out of it.

A repair is a layer and never an edit. Fixes are written beside the film and applied over
it, and the loader derives the breaks again over the repaired film, so a repair that
resolves one break and creates another is refused. A tool that can edit its own answer key
can report any accuracy it likes.

Only the broken shots are paid for twice. Each render is cached against its prompt, its
continuity state, the output format and whatever the backend declares as an input, so a
fixed shot is the only one redrawn. The exception is a backend that chains, where shot
three's last frame is shot four's reference image. Then the shots after it go stale on
purpose, which is why the earliest break is fixed first.

## Challenges we ran into

The demo had to exist before the credential did. Vertex AI access is still open work here,
so the whole pipeline was built against a placeholder renderer that draws each shot's
continuity state with ffmpeg: the jacket as a moving colour block, the parcel as a pale
rectangle that is there or is not. That made a fixture whose answer is known, which turned
out to be worth more than the footage would have been. The checker can be scored, and the
score reproduces on any machine with no key and no bill.

The honest consequence is stated on the page, in the video and here. The score in the demo
was produced by the offline stand-in reader, and it measures the pipeline rather than the
detection. The Gemini reader is written and unrun.

Fitting the argument into three minutes was the other one. The video is generated by
`cinema demo` from the same files the page is built from, and it refuses to build a cut
over 180 seconds rather than let Devpost truncate it mid-sentence.

## Accomplishments

It runs end to end for $0.00 and with no credential. Clone it and the demo reproduces.
There are 252 tests, all green, and none of them mock away the thing being tested.

The page and the video are both generated from the last run's output. No figure in either
was typed in, so a worse run says the worse thing instead of the same confident thing.

## What we learned

Checking is nearly free next to generating. Rendering five 8-second shots on Veo 3.1 at
1080p with audio is $16.00. Reading every frame of that film back with Gemini 2.5 Pro is
about three cents, under one percent of it. That ratio is the argument for putting a
checker in the loop: at that price it can run on every pass, and the re-render it triggers
is scoped to the shots that failed rather than to the film.

## What's next

Vertex AI access, then the number that matters: how the Gemini reader does on subtle
breaks in real footage rather than obvious ones in drawn boxes. A prop in the wrong hand, a
watch that changes wrist, light that moves the wrong way. After that, the checker belongs
inside the render loop rather than after it.

## Built with

Python 3, ffmpeg, Vertex AI (Veo 3.1 for generation, Gemini 2.5 Pro for detection),
GitHub Pages.

---

Built by an autonomous agent working for Joe Muller. Everything in this repo, on the page
and in the video was written by the agent. Joe reviews it and files the submission.
