"""What the picture of the hosted page is allowed to be.

Both of headless Chrome's failures here exit 0 and produce a file: a screenshot
of the wrong scroll offset is a blank rectangle, and a crop that lands off the
rendered page is the same rectangle in a different place. So the tests read the
picture rather than the exit code, and the geometry is arithmetic that can be
checked without a browser at all.

The end-to-end capture needs Chrome and ffmpeg. It is skipped where they are
missing rather than failing, because that is a fact about the machine and not
about the code.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import pageshot  # noqa: E402

PAGE = """<!doctype html><html><head><title>a page</title></head><body>
<h1>a heading, and a good deal of text above the fold so the card is not at the top</h1>
<p style="height: 900px; background: #241d33">something tall</p>
<div id="run" style="width: 800px; margin: 0 auto; background: #16121c">
  <div class="strip">
    <button type="button" onclick="document.querySelector('.panel').textContent = 's01'">s01</button>
    <button type="button" onclick="document.querySelector('.panel').textContent = 's03 chosen'">s03 &middot; re-rendered</button>
  </div>
  <div class="panel" style="height: 260px; color: #ece8f0">nothing picked</div>
  <table style="width: 100%; height: 200px; color: #ece8f0"><tr><td>asked</td><td>answered</td></tr></table>
</div>
<p style="height: 600px"></p>
</body></html>
"""


def chrome_available() -> bool:
    try:
        pageshot.browser()
    except pageshot.PageshotError:
        return False
    return True


class TheCropIsArithmetic(unittest.TestCase):
    """Where the picture is cut out of the render, checked without a browser."""

    def measured(self, **over):
        base = {"card": {"x": 212, "y": 1433, "w": 856, "h": 900}, "bottom": 1900, "page": 4213}
        base.update(over)
        return base

    def test_the_box_is_the_shape_of_the_frame(self):
        box = pageshot.crop_box(self.measured())
        self.assertAlmostEqual(box["w"] / box["h"], 16 / 9, places=2)

    def test_the_reading_is_never_cut_off_mid_row(self):
        """The box is anchored on the foot of the answers table, not the head."""
        box = pageshot.crop_box(self.measured())
        self.assertGreaterEqual(box["y"] + box["h"], 1900)

    def test_the_shot_strip_stays_in_the_picture(self):
        box = pageshot.crop_box(self.measured())
        self.assertLessEqual(box["y"], 1433)

    def test_a_taller_inspector_widens_the_box_rather_than_clipping_it(self):
        tall = pageshot.crop_box(self.measured(bottom=2600))
        self.assertGreaterEqual(tall["h"], 2600 - 1433)
        self.assertLessEqual(tall["y"], 1433)

    def test_the_box_stays_inside_the_render(self):
        for measured in (self.measured(), self.measured(bottom=2600), self.measured(card={"x": 0, "y": 0, "w": 1280, "h": 400}, bottom=380)):
            box = pageshot.crop_box(measured)
            self.assertGreaterEqual(box["x"], 0)
            self.assertGreaterEqual(box["y"], 0)
            self.assertLessEqual(box["x"] + box["w"], pageshot.CSS_WIDTH)


class TheProbe(unittest.TestCase):
    """The one thing the browser is told to do, and what it may not do."""

    def test_it_presses_the_shot_it_was_given(self):
        self.assertIn(json.dumps("s03"), pageshot._probe("s03"))

    def test_it_changes_no_text_on_the_page(self):
        script = pageshot._probe("s03")
        for edit in ("innerHTML", "textContent =", "style.", "remove()"):
            self.assertNotIn(edit, script, f"the probe rewrites the page: {edit}")


@unittest.skipUnless(chrome_available(), "no headless Chrome on this machine")
class TheCapture(unittest.TestCase):
    """A real render, read back as pixels rather than as an exit code."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name)
        (self.site / "index.html").write_text(PAGE)
        self.addCleanup(self.tmp.cleanup)

    def test_the_picture_is_the_size_asked_for_and_is_not_blank(self):
        dest = self.site / "page.png"
        box = pageshot.shoot(self.site, dest, shot="s03", width=640, height=360, log=lambda _m: None)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(dest)],
            capture_output=True, text=True, check=True,
        )
        stream = json.loads(probe.stdout)["streams"][0]
        self.assertEqual((stream["width"], stream["height"]), (640, 360))
        self.assertGreater(box["levels"], 8, "the picture is one flat colour")

    def test_the_chosen_shot_is_the_one_on_screen(self):
        """The click is proved by the panel it changed, read out of the render."""
        dest = self.site / "page.png"
        pageshot.shoot(self.site, dest, shot="s03", width=1280, height=720, log=lambda _m: None)
        first = self.site / "first.png"
        pageshot.shoot(self.site, first, shot="s01", width=1280, height=720, log=lambda _m: None)
        self.assertNotEqual(dest.read_bytes(), first.read_bytes())

    def test_a_shot_the_page_does_not_carry_is_a_refusal(self):
        with self.assertRaises(pageshot.PageshotError) as caught:
            pageshot.shoot(self.site, self.site / "no.png", shot="s99", width=640, height=360,
                           log=lambda _m: None)
        self.assertIn("s99", str(caught.exception))

    def test_a_page_with_no_inspector_is_a_refusal(self):
        (self.site / "index.html").write_text("<!doctype html><html><body><p>nothing</p></body></html>")
        with self.assertRaises(pageshot.PageshotError) as caught:
            pageshot.shoot(self.site, self.site / "no.png", shot="s03", width=640, height=360,
                           log=lambda _m: None)
        self.assertIn("inspector", str(caught.exception))

    def test_the_scratch_copy_does_not_survive_the_run(self):
        pageshot.shoot(self.site, self.site / "page.png", shot="s03", width=640, height=360,
                       log=lambda _m: None)
        self.assertFalse((self.site / "_pageshot.html").exists())
        self.assertEqual((self.site / "index.html").read_text(), PAGE)


if __name__ == "__main__":
    unittest.main()
