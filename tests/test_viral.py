"""The virality score, the cold-open teaser and loop-friendly endings. Runs against the code and ffmpeg; no AI is called."""
import json, os, subprocess, sys, tempfile
os.environ.setdefault("PEAKCUT_DATA", tempfile.mkdtemp(prefix="pc-viral-")); os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
from pathlib import Path
from studio import brain, render, jobs, tools
tools.setup()
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

# ---- the score
V = brain.virality
check("a perfect clip scores 100", V(100, 5, 5, 5, 5, True, 30), 100)
check("a clip with nothing going for it scores 0", V(0, 0, 0, 0, 0, False, 30), 0)
check("the hook counts more than the payoff", V(50, 5, 2, 2, 2, True, 30) > V(50, 2, 5, 2, 2, True, 30), True)
check("a clip that needs the video to make sense loses 10", V(50, 3, 3, 3, 3, True, 30) - V(50, 3, 3, 3, 3, False, 30), 10)
check("a 65 second clip loses 10 against a 30 second one", V(80, 4, 4, 3, 2, True, 30) - V(80, 4, 4, 3, 2, True, 65), 10)
check("up to 45 seconds there is no length penalty", V(80, 4, 4, 3, 2, True, 45), V(80, 4, 4, 3, 2, True, 20))

# ---- words: one every 0.4 s, 60 s of talk
text = ("so yesterday I tried the new update and honestly I did not expect much at all but then the boss "
        "spawned right behind me and I had one bullet left one single bullet and I hit the headshot from across "
        "the map and the whole chat went crazy nobody believed it was real so I clipped it and here it is").split()
words = [{"w": w, "s": round(i * 0.4, 2), "e": round(i * 0.4 + 0.3, 2)} for i, w in enumerate(text)]
dur = words[-1]["e"] + 1
s, e = words[0]["s"], words[-1]["e"] + 0.35

t = brain._teaser(words, "I hit the headshot from across", s, e)
i = text.index("hit") - 1
check("the teaser starts on its quoted words", t and abs(t[0] - (words[i]["s"] - 0.05)) < 0.01, True)
check("the teaser lasts 1 to 3.7 seconds", t and 1.0 <= t[1] - t[0] <= 3.7, True)
check("a teaser of the clip's first seconds is refused", brain._teaser(words, "so yesterday I tried the", s, e), None)
check("a quote that is not said is refused", brain._teaser(words, "this was never said here", s, e), None)
long_t = brain._teaser(words, "I had one bullet left one single bullet and I hit the headshot", s, e)
check("a long quote is cut to 3.5 seconds of whole words", long_t and long_t[1] - long_t[0] <= 3.7, True)

check("a tight end sits 0.15 s after the last word", brain._tight_end(words, s, e), round(words[-1]["e"] + 0.15, 2))

def fake(answer):
    return lambda prompt, schema=None, purpose="", timeout=None: (answer, "m", 10)
row = {"id": "C1", "hook": 2, "payoff": 5, "emotion": 4, "loop": 3, "stands_alone": True, "verdict": "keep",
       "first_words": "so yesterday I tried the", "last_words": "and here it is", "teaser_words": "I hit the headshot from across", "note": "ok"}
clip = {"start": s, "end": e, "score": 70, "hook": "X", "title": "t", "reason": "r"}
brain.ask_ai = fake([row])
out, _ = brain.review_clips([dict(clip)], words, "", 10, 60, dur)
c = out[0]
check("the review gives the new score", c["score"], V(70, 2, 5, 4, 3, True, c["end"] - c["start"]))
check("the parts of the score are kept for the app", c["virality"], {"hook": 2, "payoff": 5, "emotion": 4, "loop": 3, "alone": True})
check("a clip with a weak opening gets a teaser", "teaser" in c, True)
check("loop-friendly: the end is tight", c["end"], round(words[-1]["e"] + 0.15, 2))
brain.ask_ai = fake([dict(row, hook=4)])
out, _ = brain.review_clips([dict(clip)], words, "", 10, 60, dur)
check("a clip that already opens strong gets no teaser", "teaser" in out[0], False)
brain.ask_ai = fake([row])
out, _ = brain.review_clips([dict(clip)], words, "", 10, 60, dur, loop=False)
check("loop off: the end is left as it was", out[0]["end"], e)

# ---- options
check("new clips aim for 20 to 40 seconds", (jobs.DEFAULTS["min_len"], jobs.DEFAULTS["max_len"]), (20, 40))
check("both switches are on by default", (jobs.DEFAULTS["cold_open"], jobs.DEFAULTS["loop"]), (True, True))
check("the switches can be turned off", jobs.clean_options({"cold_open": False, "loop": False}), {"cold_open": False, "loop": False})
try:
    jobs.clean_options({"cold_open": "yes"}); check("a switch that is not on or off is refused", False)
except ValueError as x:
    check("a switch that is not on or off is refused", "Cold open" in str(x))

# ---- render
base = {"start": 10.0, "end": 30.0, "teaser": [20.0, 22.5]}
check("a teaser inside the clip is used", render.teaser_span(base), (20.0, 22.5))
check("cold open off: no teaser", render.teaser_span(dict(base, cold_open=False)), None)
check("a clip trimmed past its teaser plays without it", render.teaser_span(dict(base, end=21.0)), None)
check("a teaser in the first 2 seconds is not used", render.teaser_span(dict(base, teaser=[10.5, 12.5])), None)
check("a broken teaser is ignored", render.teaser_span(dict(base, teaser=["a", None])), None)
ws = [{"w": "one", "s": 20.1, "e": 20.6}, {"w": "two", "s": 21.0, "e": 21.5}, {"w": "start", "s": 10.0, "e": 10.4}]
mapped, a, b = render.teaser_words(ws, 10.0, 30.0, (20.0, 22.5))
check("the joined timeline is the teaser plus the clip", (a, b), (0.0, 22.5))
check("the teaser's words come first, from 0", [(w["w"], round(w["s"], 2)) for w in mapped[:2]], [("one", 0.1), ("two.", 1.0)])
check("the clip's words follow after the teaser", [round(w["s"], 2) for w in mapped if w["w"] == "start"], [2.5])
check("the teaser line plays again in its place in the clip", [round(w["s"], 2) for w in mapped if w["w"] == "one"], [0.1, 12.6])

work = Path(tempfile.mkdtemp(prefix="pc-viral-r-"))
src = work / "src.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=40",
                "-f", "lavfi", "-i", "sine=frequency=300:duration=40", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", str(src)], check=True)
def length(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(p)],
                         capture_output=True, text=True).stdout
    return float(json.loads(out)["format"]["duration"])
clip = {"start": 10.0, "end": 30.0, "teaser": [20.0, 22.5], "hook": "WAIT FOR IT", "style": "bounce", "layout": "blur"}
render.render_clip(src, work / "out", "cold", clip, ws, 640, 360)
check("a cold-open clip is the teaser plus the clip long", abs(length(work / "out" / "cold.mp4") - 22.5) < 0.3, True)
render.render_clip(src, work / "out", "plain", dict(clip, cold_open=False), ws, 640, 360)
check("with cold open off it is the clip alone", abs(length(work / "out" / "plain.mp4") - 20.0) < 0.3, True)
ass = (work / "out" / "cold.ass").read_text(encoding="utf-8")
check("the captions cover the joined video", "0:00:00.10" in ass and "0:00:02.50" in ass, True)

print("ALL PASSED" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
