"""The shot bible: what is true of the film, decided before a frame exists.

The checker is only asking Gemini for an opinion unless it has a ground truth to
compare a frame against. This module is that ground truth, and it does three
jobs that have to agree with each other or the entry does not work:

1. **It writes the prompt.** Every wardrobe and prop clause a shot is rendered
   with comes from here, so the thing generation was asked for and the thing the
   check looks for are the same sentence.
2. **It gives the checker its questions.** One question per attribute, with the
   words an answer is allowed to use, so "crimson" and "red" are one value
   rather than two.
3. **It decides what counts as a break.** This is the part a bigger prompt
   cannot do. Not everything that changes is an error: the courier's jacket must
   never change colour, and the light must go from dusk to night. A checker that
   flags both is worthless, and one that flags neither is worse.

That third job is a per-attribute rule:

  `constant`     the value must equal `canon` in every shot. Wardrobe, a
                 character's face, whether the parcel is still being carried.
  `progressive`  the value moves along `order` and never backwards. Time of day,
                 weather closing in, an injury getting worse.
  `declared`     `constant`, except at the shots listed in `changes_at`, where
                 the author has said the change is the story.

`derive_breaks` applies those rules to a sequence of per-shot states. The states
can come from two places, and that is the whole design: the *declared* state in
film.yaml gives the answer key, and the *observed* state Gemini reads out of the
frames gives the finding. The same function judges both, so a break the checker
reports means exactly what a break in the answer key means.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CONSTANT = "constant"
PROGRESSIVE = "progressive"
DECLARED = "declared"
RULES = (CONSTANT, PROGRESSIVE, DECLARED)


class BibleError(ValueError):
    """The bible is wrong in a way that would make the check meaningless."""


def fold(text) -> str:
    """A value as it is compared: lowercase, unpunctuated, single-spaced.

    Gemini answers in prose, so 'Dark red.' and 'dark  red' have to arrive at
    the same key as the synonym table's 'dark red'.
    """
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


@dataclass(frozen=True)
class Subject:
    """A character or a prop the attributes hang off."""

    id: str
    kind: str  # "character" or "prop"
    name: str
    description: str


@dataclass(frozen=True)
class Attribute:
    name: str
    rule: str
    canon: str
    values: tuple
    question: str
    subject: str | None = None
    clauses: dict = field(default_factory=dict)  # value -> the prompt clause
    lookup: dict = field(default_factory=dict)  # folded word -> canonical value
    order: tuple = ()  # progressive only
    changes_at: dict = field(default_factory=dict)  # declared only: shot -> value
    # Values at which the subject is not in the shot at all. A prompt that
    # describes the parcel in detail and then asks for no parcel gets a parcel,
    # so the description is withheld rather than contradicted.
    hides_subject: tuple = ()

    def normalise(self, answer):
        """A checker's answer as one of `values`, or None if it is not one.

        None is a real outcome and must not be read as agreement: it means the
        frame was described in words the bible never offered, which is a
        question the author has to answer, not a break to report.
        """
        if answer is None:
            return None
        return self.lookup.get(fold(answer))

    def clause(self, value) -> str:
        return self.clauses.get(value, f"{self.name} is {value}")

    def position(self, value) -> int:
        return self.order.index(value)


@dataclass(frozen=True)
class Break:
    """One continuity error: an attribute of one shot that is not what it should be."""

    shot: str
    attribute: str
    before: str
    after: str
    # Why the rule was broken. Useful in a report, and deliberately outside
    # equality so a derived break compares equal to a hand-written answer key.
    rule: str = field(default="", compare=False)

    def sentence(self) -> str:
        return f"{self.shot}: {self.attribute} was {self.before}, is {self.after}"


@dataclass(frozen=True)
class Question:
    """What the checker asks about one frame."""

    attribute: str
    text: str
    values: tuple
    subject: str | None = None


@dataclass(frozen=True)
class Bible:
    subjects: dict = field(default_factory=dict)
    attributes: tuple = ()

    @property
    def names(self) -> list:
        return [a.name for a in self.attributes]

    def attribute(self, name) -> Attribute:
        for a in self.attributes:
            if a.name == name:
                return a
        raise BibleError(f"no attribute {name!r} in the bible")

    # -- what the checker is given -------------------------------------------
    #
    # Questions and vocabulary only. The bible's `canon`, the per-shot declared
    # state and `expected_breaks` are all withheld: a checker told the answer
    # cannot be scored on finding it.

    def questions(self) -> list:
        return [
            Question(a.name, a.question, tuple(a.values), a.subject)
            for a in self.attributes
        ]

    def read(self, answers: dict) -> dict:
        """One frame's answers, normalised. Unrecognised words are dropped."""
        state = {}
        for name, answer in answers.items():
            value = self.attribute(name).normalise(answer)
            if value is not None:
                state[name] = value
        return state

    # -- what generation is given --------------------------------------------

    def prompt_for(self, shot) -> str:
        """The shot's own line, plus the continuity it has to hold.

        Composed rather than hand-written, so a wardrobe change is made in one
        place and cannot disagree with what the checker asks about.
        """
        if not self.attributes:
            return shot.prompt

        clauses, mentioned, hidden = [], [], set()
        for a in self.attributes:
            value = shot.continuity.get(a.name)
            if value is None:
                continue
            clauses.append(a.clause(value))
            if not a.subject:
                continue
            if value in a.hides_subject:
                hidden.add(a.subject)
            elif a.subject not in mentioned:
                mentioned.append(a.subject)

        lines = [shot.prompt]
        if clauses:
            lines.append("Continuity, to hold exactly: " + "; ".join(clauses) + ".")
        for subject_id in mentioned:
            if subject_id in hidden:
                continue
            subject = self.subjects[subject_id]
            lines.append(f"{subject.name}: {subject.description}")
        return "\n".join(lines)


def derive_breaks(bible: Bible, states) -> list:
    """Every break implied by a run of per-shot states, in shot order.

    `states` is [(shot_id, {attribute: value}), ...]. A missing attribute is
    skipped rather than guessed (an unanswered question is not an error), and
    a value outside the attribute's vocabulary raises, because that is an author
    or a normalisation mistake and reporting it as a break would hide it.
    """
    breaks = []
    for attribute in bible.attributes:
        expected = attribute.canon
        for shot_id, state in states:
            if attribute.rule == DECLARED and shot_id in attribute.changes_at:
                expected = attribute.changes_at[shot_id]
                continue
            if attribute.name not in state:
                continue
            value = state[attribute.name]
            if value not in attribute.values:
                raise BibleError(
                    f"{shot_id} has {attribute.name}={value!r}, which is not one of "
                    f"{', '.join(attribute.values)}"
                )
            if attribute.rule == PROGRESSIVE:
                if attribute.position(value) < attribute.position(expected):
                    breaks.append(
                        Break(shot_id, attribute.name, expected, value, PROGRESSIVE)
                    )
                else:
                    expected = value
            elif value != expected:
                breaks.append(Break(shot_id, attribute.name, expected, value, attribute.rule))
    return sorted(breaks, key=lambda b: ([s for s, _ in states].index(b.shot), b.attribute))


# -- loading ----------------------------------------------------------------


def _subjects(raw) -> dict:
    subjects = {}
    for kind, key in (("character", "characters"), ("prop", "props")):
        for entry in raw.get(key) or []:
            subject = Subject(
                id=entry["id"],
                kind=kind,
                name=entry.get("name", entry["id"]),
                description=" ".join(str(entry.get("description", "")).split()),
            )
            if not subject.description:
                raise BibleError(f"{kind} {subject.id!r} has no description to render from")
            if subject.id in subjects:
                raise BibleError(f"two subjects share the id {subject.id!r}")
            subjects[subject.id] = subject
    return subjects


def _clauses(entry, name, values) -> dict:
    """`describe` as a value -> clause map, from either form it may be written in."""
    describe = entry.get("describe")
    if describe is None:
        raise BibleError(f"attribute {name!r} has no `describe`, so it cannot reach the prompt")
    if isinstance(describe, str):
        if "{value}" not in describe:
            raise BibleError(
                f"attribute {name!r} describes every value the same way: put {{value}} in the "
                "template, or write one clause per value"
            )
        return {v: describe.format(value=v) for v in values}
    if isinstance(describe, dict):
        missing = [v for v in values if v not in describe]
        if missing:
            raise BibleError(f"attribute {name!r} does not describe {', '.join(missing)}")
        return {v: " ".join(str(describe[v]).split()) for v in values}
    raise BibleError(f"attribute {name!r} has a `describe` that is neither a template nor a map")


def _lookup(name, values, synonyms) -> dict:
    """Folded word -> canonical value, refusing any word that means two things."""
    table = {}
    for value in values:
        table[fold(value)] = value
    for value, words in (synonyms or {}).items():
        if value not in values:
            raise BibleError(f"attribute {name!r} has synonyms for {value!r}, which is not a value")
        for word in words:
            folded = fold(word)
            if folded in table and table[folded] != value:
                raise BibleError(
                    f"attribute {name!r}: {word!r} would mean both {table[folded]!r} and {value!r}"
                )
            table[folded] = value
    return table


def _attribute(entry, subjects) -> Attribute:
    name = entry["name"]
    rule = entry.get("rule", CONSTANT)
    if rule not in RULES:
        raise BibleError(f"attribute {name!r} has rule {rule!r}, not one of {', '.join(RULES)}")

    order = tuple(entry.get("order") or ())
    if rule == PROGRESSIVE and len(order) < 2:
        raise BibleError(f"attribute {name!r} is progressive but has no `order` to move along")
    if order and entry.get("values"):
        raise BibleError(f"attribute {name!r} gives both `order` and `values`; `order` is both")
    values = tuple(order or entry.get("values") or ())
    if len(values) < 2:
        raise BibleError(f"attribute {name!r} has fewer than two values, so it can never break")
    if len(set(values)) != len(values):
        raise BibleError(f"attribute {name!r} repeats a value")

    canon = entry.get("canon", values[0])
    if canon not in values:
        raise BibleError(f"attribute {name!r} has canon {canon!r}, which is not one of its values")

    question = " ".join(str(entry.get("question", "")).split())
    if not question:
        raise BibleError(f"attribute {name!r} has no `question`, so the checker cannot ask about it")

    subject = entry.get("subject")
    if subject is not None and subject not in subjects:
        raise BibleError(f"attribute {name!r} belongs to {subject!r}, which is not a declared subject")

    changes_at = {str(k): str(v) for k, v in (entry.get("changes_at") or {}).items()}
    if changes_at and rule != DECLARED:
        raise BibleError(
            f"attribute {name!r} lists changes_at but is {rule!r}: only a declared attribute "
            "may change on purpose"
        )
    for shot_id, value in changes_at.items():
        if value not in values:
            raise BibleError(f"attribute {name!r} changes to {value!r} at {shot_id}, which is not a value")

    hides = tuple(str(v) for v in (entry.get("hides_subject") or ()))
    for value in hides:
        if value not in values:
            raise BibleError(f"attribute {name!r} hides its subject at {value!r}, which is not a value")
    if hides and subject is None:
        raise BibleError(f"attribute {name!r} hides a subject but does not name one")

    return Attribute(
        name=name,
        rule=rule,
        canon=canon,
        values=values,
        question=question,
        subject=subject,
        clauses=_clauses(entry, name, values),
        lookup=_lookup(name, values, entry.get("synonyms")),
        order=order,
        changes_at=changes_at,
        hides_subject=hides,
    )


def load(raw) -> Bible:
    """Build a bible from the `bible:` mapping of the spec."""
    if not raw:
        return Bible()
    if not isinstance(raw, dict):
        raise BibleError("`bible` is not a mapping")

    subjects = _subjects(raw)
    attributes = []
    seen = set()
    for entry in raw.get("attributes") or []:
        attribute = _attribute(entry, subjects)
        if attribute.name in seen:
            raise BibleError(f"two attributes share the name {attribute.name!r}")
        seen.add(attribute.name)
        attributes.append(attribute)
    if not attributes:
        raise BibleError("the bible tracks no attributes: the checker would have nothing to ask")

    return Bible(subjects=subjects, attributes=tuple(attributes))
