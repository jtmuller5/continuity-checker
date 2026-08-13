"""The part of the page a judge operates, rather than reads.

Devpost asks for a project that runs on the web. A page reporting the numbers
of a run nobody can start is a result, not a project, so this turns the run
itself into something you can work through: pick a shot, see the stills the
checker sampled, the questions it was asked, what it answered about each still,
how those answers folded into one reading, and what the scorer then made of it.

It carries every run in `out/`, not one. A checker that has only ever been
shown against a single film is indistinguishable from a checker with that
film's answer written into it, so the page lets a visitor switch films as well
as shots, and each film breaks in a way the other does not.

Two rules hold it honest, and they are the whole reason this file is small:

**It re-implements nothing.** Every value it shows is lifted out of
`out/continuity.json` and `out/score.json` — the same two files `score`,
`fix` and `demo` read. There is no judgement in the JavaScript. A break shown
here is a break `bible.derive_breaks` found, and a verdict beside it is the one
`cinema score` wrote. The moment the browser starts deciding anything, the
entry's claim about a single source of truth stops being true.

**The data is inlined, not fetched.** The site is static files on GitHub Pages
and the run is a few kilobytes of JSON, so the page carries it. That keeps the
app working from a local file, from a zip a judge downloaded, and with no
server, no build step and no dependency — and it means a page that renders at
all is a page whose data arrived.
"""

from __future__ import annotations

import json

# Every run gets its own folder of assets. Two films both have an s01, so a
# flat folder would serve one film's still under the other film's name.
def assets_dir(key: str) -> str:
    return f"assets/{key}"


def frames_dir(key: str) -> str:
    return f"{assets_dir(key)}/frames"


# The scorer's verdicts, in the words the page shows them in. `score` writes
# each finding into exactly one of these lists.
VERDICTS = {
    "hits": ("found", "hit"),
    "misses": ("MISSED", "miss"),
    "false_alarms": ("FALSE ALARM", "alarm"),
}


def _frame_src(path: str, key: str) -> str:
    """A frame's path in the report, as the published site serves it."""
    return f"{frames_dir(key)}/{str(path).replace(chr(92), '/').rsplit('/', 1)[-1]}"


def frame_paths(report: dict) -> list[str]:
    """Every frame the report names, relative to `out/`.

    `publish` copies these; the app points at them. One list, so a frame that
    reaches the page and a frame that reaches the site cannot disagree.
    """
    found = []
    for shot in report.get("shots") or ():
        for frame in shot.get("frames") or ():
            path = frame.get("path")
            if path:
                found.append(str(path))
    return found


def _graded(score: dict) -> dict:
    """Every finding the scorer wrote, keyed by the shot it belongs to.

    A miss is on this list too. It is the one thing a shot's own reading cannot
    show — the checker said nothing, and silence looks identical to a clean
    shot until the answer key is laid beside it.
    """
    by_shot: dict = {}
    for kind, (label, css) in VERDICTS.items():
        for item in score.get(kind) or ():
            by_shot.setdefault(item["shot"], []).append({
                "label": label,
                "css": css,
                "attribute": item.get("attribute"),
                "sentence": item.get("sentence")
                or f"{item['shot']}: {item.get('attribute')} was "
                   f"{item.get('expected')}, is {item.get('found')}",
            })
    for near in score.get("near_misses") or ():
        expected, found = near.get("expected") or {}, near.get("found") or {}
        by_shot.setdefault(expected.get("shot") or found.get("shot"), []).append({
            "label": "near miss",
            "css": "near",
            "attribute": expected.get("attribute"),
            "sentence": f"planted {expected.get('expected')} → {expected.get('found')}, "
                        f"read {found.get('expected')} → {found.get('found')}",
        })
    return by_shot


def _cell_flags(score: dict) -> dict:
    """`(shot, attribute)` the scorer marked, so the table can say which cells."""
    cells = score.get("cells") or {}
    flags = {}
    for key in ("misread", "disputed", "unanswered"):
        for cell in cells.get(key) or ():
            flags[f"{cell.get('shot')}/{cell.get('attribute')}"] = key
    return flags


def data(score: dict, report: dict, plates: list, key: str = "main") -> dict:
    """One run, arranged for the browser. Nothing here is computed, only sorted."""
    graded = _graded(score)
    flags = _cell_flags(score)
    repaired = {shot for shot, _ in plates}
    breaks: dict = {}
    for item in report.get("breaks") or ():
        breaks.setdefault(item["shot"], []).append(item)

    shots = []
    for shot in report.get("shots") or ():
        shot_id = shot.get("shot")
        shots.append({
            "id": shot_id,
            "state": shot.get("state") or {},
            "unanswered": list(shot.get("unanswered") or ()),
            "disputed": shot.get("disputed") or {},
            "frames": [
                {
                    "index": frame.get("index"),
                    "at": frame.get("at"),
                    "src": _frame_src(frame.get("path") or "", key),
                    "answers": frame.get("answers") or {},
                    "state": frame.get("state") or {},
                }
                for frame in shot.get("frames") or ()
            ],
            "breaks": breaks.get(shot_id) or [],
            "verdicts": graded.get(shot_id) or [],
            "flags": {
                key.split("/", 1)[1]: value
                for key, value in flags.items()
                if key.split("/", 1)[0] == shot_id
            },
            "repaired": shot_id in repaired,
            "plate": f"{assets_dir(key)}/{shot_id}.png" if shot_id in repaired else None,
        })

    cells = score.get("cells") or {}
    return {
        "key": key,
        # The cut this reading is of. `publish` fills it in for every film the
        # page does not already carry a player for, so the hero video above is
        # not drawn a second time inside the panel.
        "cut": None,
        "poster": None,
        "film": report.get("film") or "",
        "reader": report.get("reader") or "unknown",
        "model": report.get("model"),
        "at": report.get("at") or "",
        "planted": score.get("expected_breaks", 0),
        "found": score.get("found_breaks", 0),
        "cells": {"total": cells.get("total", 0), "agreed": cells.get("agreed", 0)},
        "questions": report.get("questions") or [],
        "shots": shots,
    }


STYLE = """
  #run { margin-top: 1rem; }
  #run .films { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: .75rem; }
  #run .films button { font: inherit; font-size: .95rem; color: var(--ink); cursor: pointer;
    background: #0f0c14; border: 1px solid var(--line); border-radius: 8px;
    padding: .5rem .9rem; text-align: left; }
  #run .films button[aria-pressed="true"] { border-color: #9fb8ff; background: #262038; }
  #run .films b { display: block; font-weight: 600; }
  #run .films small { color: var(--dim); }
  #run .summary { color: var(--dim); font-size: .9rem; margin: 0 0 1rem; }
  #run .cut { margin: 0 0 1rem; }
  #run .strip { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1rem; }
  #run .strip button { font: inherit; font-size: .95rem; color: var(--ink); cursor: pointer;
    background: var(--card); border: 1px solid var(--line); border-radius: 8px;
    padding: .45rem .8rem; display: flex; gap: .5rem; align-items: center; }
  #run .strip button[aria-pressed="true"] { border-color: #9fb8ff; background: #262038; }
  #run .dot { width: .55rem; height: .55rem; border-radius: 50%; background: #7fd48b; }
  #run .dot.broke { background: #f08a7a; }
  #run .dot.near { background: #e8c36a; }
  #run .stills { display: flex; gap: .75rem; flex-wrap: wrap; margin: 0 0 1rem; }
  #run .stills figure { margin: 0; flex: 1 1 12rem; }
  #run .stills figcaption { font-size: .8rem; }
  #run .verdict { margin: 0 0 1rem; padding: .6rem .8rem; border-radius: 8px;
    border: 1px solid var(--line); background: #0f0c14; font-size: .95rem; }
  #run .verdict span.hit { color: #7fd48b; }
  #run .verdict span.miss, #run .verdict span.alarm { color: #f08a7a; }
  #run .verdict span.near { color: #e8c36a; }
  #run .verdict b { font-weight: 600; }
  #run td.asked { color: var(--dim); }
  #run td.read { font-variant-numeric: tabular-nums; }
  #run tr.moved td.read { color: #f08a7a; }
  #run tr.misread td, #run tr.disputed td, #run tr.unanswered td { color: #e8c36a; }
  #run .hint { color: var(--dim); font-size: .85rem; }
  #run .plate { margin-top: 1rem; }
"""

MARKUP = """
<div id="run" class="card" hidden>
  <div class="films" role="group" aria-label="films"></div>
  <p class="summary"></p>
  <div class="cut"></div>
  <div class="strip" role="group" aria-label="shots"></div>
  <div class="panel"></div>
</div>
<noscript><p class="hint">The film-by-film inspector needs JavaScript. Everything it
shows is in <code>continuity.json</code> and <code>score.json</code> under <code>out/</code>
in the repository, and <code>python3 -m cinema check</code> prints the same reading.</p></noscript>
"""

SCRIPT = """
<script type="application/json" id="run-data">__DATA__</script>
<script>
(function () {
  var films = JSON.parse(document.getElementById('run-data').textContent).films;
  var root = document.getElementById('run');
  var picker = root.querySelector('.films');
  var summary = root.querySelector('.summary');
  var cutBox = root.querySelector('.cut');
  var strip = root.querySelector('.strip');
  var panel = root.querySelector('.panel');
  films = films.filter(function (f) { return f.shots.length; });
  if (!films.length) return;
  root.hidden = false;
  var run = films[0];

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'class') node.className = attrs[k];
      else if (k === 'text') node.textContent = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (kid) { node.appendChild(kid); });
    return node;
  }

  function tone(shot) {
    if (shot.verdicts.some(function (v) { return v.css === 'miss' || v.css === 'alarm'; })) return 'broke';
    if (shot.verdicts.some(function (v) { return v.css === 'near'; })) return 'near';
    return shot.breaks.length ? 'broke' : '';
  }

  var current = 0;

  function stills(shot) {
    var box = el('div', {class: 'stills'});
    shot.frames.forEach(function (frame) {
      box.appendChild(el('figure', {}, [
        el('img', {src: frame.src, alt: shot.id + ' frame ' + (frame.index + 1), loading: 'lazy'}),
        el('figcaption', {text: 'frame ' + (frame.index + 1) + ' \\u00b7 ' + frame.at + 's into the shot'})
      ]));
    });
    return box;
  }

  function answers(shot) {
    var table = el('table');
    var head = el('tr', {}, [el('th', {text: 'the checker was asked'}), el('th', {text: 'it answered'})]);
    shot.frames.forEach(function (frame) {
      head.appendChild(el('th', {text: 'frame ' + (frame.index + 1)}));
    });
    table.appendChild(head);
    run.questions.forEach(function (q) {
      var reading = shot.state[q.attribute];
      var flag = shot.flags[q.attribute] || '';
      var moved = shot.breaks.some(function (b) { return b.attribute === q.attribute; });
      var row = el('tr', {class: (flag ? flag + ' ' : '') + (moved ? 'moved' : '')}, [
        el('td', {class: 'asked', text: q.text}),
        el('td', {class: 'read', text: reading === undefined ? (flag || 'no reading') : reading})
      ]);
      shot.frames.forEach(function (frame) {
        var said = frame.answers[q.attribute];
        row.appendChild(el('td', {text: said === undefined || said === null ? '\\u2014' : String(said)}));
      });
      table.appendChild(row);
    });
    return table;
  }

  function verdict(shot) {
    var box = el('div', {class: 'verdict'});
    if (!shot.verdicts.length && !shot.breaks.length) {
      box.appendChild(el('span', {class: 'hit', text: 'nothing reported here'}));
      return box;
    }
    var lines = shot.verdicts.length ? shot.verdicts : shot.breaks.map(function (b) {
      return {label: 'reported', css: '', sentence: b.sentence};
    });
    lines.forEach(function (line) {
      box.appendChild(el('div', {}, [
        el('span', {class: line.css, text: line.label}),
        el('b', {text: ' \\u00b7 ' + line.sentence})
      ]));
    });
    return box;
  }

  function drawFilm(index) {
    run = films[index];
    Array.prototype.forEach.call(picker.children, function (button, i) {
      button.setAttribute('aria-pressed', i === index ? 'true' : 'false');
    });
    summary.textContent = run.film + ' \\u00b7 ' + run.planted + ' break' +
      (run.planted === 1 ? '' : 's') + ' planted, ' + run.found + ' found, ' +
      run.cells.agreed + ' of ' + run.cells.total + ' cells read as declared, on the ' +
      run.reader + ' reader' + (run.model ? ' (' + run.model + ')' : '') + '.';
    cutBox.textContent = '';
    if (run.cut) {
      var video = el('video', {controls: '', muted: '', playsinline: '', poster: run.poster || ''});
      video.appendChild(el('source', {src: run.cut, type: 'video/mp4'}));
      cutBox.appendChild(el('figure', {}, [
        video, el('figcaption', {text: 'The cut this reading is of.'})
      ]));
    }
    strip.textContent = '';
    run.shots.forEach(function (shot, i) {
      var button = el('button', {type: 'button', 'aria-pressed': 'false'}, [
        el('span', {class: 'dot ' + tone(shot)}),
        el('span', {text: shot.id + (shot.repaired ? ' \\u00b7 re-rendered' : '')})
      ]);
      button.addEventListener('click', function () { draw(i); });
      strip.appendChild(button);
    });
    draw(0);
  }

  function draw(index) {
    current = index;
    var shot = run.shots[index];
    Array.prototype.forEach.call(strip.children, function (button, i) {
      button.setAttribute('aria-pressed', i === index ? 'true' : 'false');
    });
    panel.textContent = '';
    panel.appendChild(stills(shot));
    panel.appendChild(verdict(shot));
    panel.appendChild(answers(shot));
    panel.appendChild(el('p', {class: 'hint', text: shot.frames.length +
      ' stills, read one at a time. The reader is given the questions above and the words it may' +
      ' answer with, and nothing else. Frames that disagree are left out of the reading rather' +
      ' than voted on.'}));
    if (shot.plate) {
      panel.appendChild(el('figure', {class: 'plate'}, [
        el('img', {src: shot.plate, alt: shot.id + ' before and after the re-render'}),
        el('figcaption', {text: shot.id + ' was re-rendered from the finding: the broken frame, then the fixed one.'})
      ]));
    }
  }

  films.forEach(function (film, i) {
    var button = el('button', {type: 'button', 'aria-pressed': 'false'}, [
      el('b', {text: film.film}),
      el('small', {text: film.planted + ' planted, ' + film.found + ' found'})
    ]);
    button.addEventListener('click', function () { drawFilm(i); });
    picker.appendChild(button);
  });
  // One film needs no picker. The control is the second film's, and showing it
  // alone would advertise a choice that is not there.
  if (films.length < 2) picker.hidden = true;

  document.addEventListener('keydown', function (event) {
    if (event.key === 'ArrowRight') draw((current + 1) % run.shots.length);
    else if (event.key === 'ArrowLeft') draw((current + run.shots.length - 1) % run.shots.length);
    else return;
    root.scrollIntoView({block: 'nearest'});
  });

  drawFilm(0);
})();
</script>
"""


def section(films: list) -> str:
    """The inspector: markup, and every run inlined beside it.

    `films` is what `data` returned for each run, in the order the picker
    offers them. The first is the one the page opens on.
    """
    payload = json.dumps({"films": list(films)}, separators=(",", ":"))
    # `</script` anywhere in a value would end the block early; escaping the
    # angle bracket is what keeps a film title out of the document's markup.
    payload = payload.replace("<", "\\u003c").replace("&", "\\u0026")
    return MARKUP + SCRIPT.replace("__DATA__", payload)
