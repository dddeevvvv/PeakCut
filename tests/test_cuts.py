"""Where clips start and end. YouTube's transcript has no full stops and fast talkers rarely pause, so the AI quotes
the first and last words of each clip and the cut is made on those words. Runs against the code; no AI is called."""
import os, sys, tempfile
os.environ.setdefault("PEAKCUT_DATA", tempfile.mkdtemp(prefix="pc-cuts-")); os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
from studio import brain
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

# 60 seconds of fast talk: one word every 0.4 s, never a pause, no punctuation (like YouTube's transcript)
text = ("lekin 19 november ko jab gta 6 launch hoga to gta 5 ki ye saari aadatein tumhare liye problem banne "
        "waali hain kyunki gta 6 mein tum har weapon apne saath carry nahi kar sakte aap limited weapons hi "
        "rakh sakte ho bhai game bahut tough hone wala hai ab yahan ek interesting change hai police ko "
        "automatically pata chalega aur phir dekhte hain kya hota hai").split()
words = [{"w": w, "s": round(i * 0.4, 2), "e": round(i * 0.4 + 0.35, 2)} for i, w in enumerate(text)]
lines = brain.make_lines(words)
dur = words[-1]["e"] + 1

first = next(i for i, w in enumerate(words) if w["w"] == "kyunki")
last = next(i for i, w in enumerate(words) if w["w"] == "tough") + 3       # "...tough hone wala hai"
clip = {"start": words[first]["s"] + 2.5, "end": words[last]["e"] - 3.0,   # seconds a little off, as AIs give them
        "first_words": "kyunki GTA 6 mein tum", "last_words": "bahut tough hone wala hai"}
s, e = brain._snap(brain._pin(dict(clip), words), lines, words, 10, 60, dur)
check("the clip starts on the first quoted word, not on a nearby line", abs(s - (words[first]["s"] - 0.15)) < 0.01, True)
check("the clip ends on the last quoted word, plus a short breath", words[last]["e"] <= e <= words[last]["e"] + 0.36, True)

check("a quote that is not in the transcript is ignored", brain.locate(words, "completely different words here", 10), None)
check("one word is not enough to cut on", brain.locate(words, "kyunki", 20), None)
check("a quote is only looked for near where the AI said", brain.locate(words, "kyunki gta 6 mein", 200), None)
check("small spelling differences still match", brain.locate(words, "kyunki GTA-6 mein tum har", words[first]["s"]), words[first]["s"])

# without quotes it works as before: the seconds are used
s2, e2 = brain._snap(brain._pin({"start": 0.0, "end": 20.0}, words), lines, words, 10, 60, dur)
check("no quotes: the old way still gives a clip of an allowed length", 10 <= e2 - s2 <= 60.5, True)

# a quoted end that would make the clip too long is not used as it is
long_clip = dict(clip, last_words="dekhte hain kya hota hai")
s3, e3 = brain._snap(brain._pin(long_clip, words), lines, words, 10, 20, dur)
check("the length limit still wins over a quote", e3 - s3 <= 20.5, True)

# ---- "most replayed": YouTube's graph of what viewers replayed, shown to the AI as (HOT)
from studio import media
url = "https://www.youtube.com/watch?v=test"
media._HEAT[url] = [{"start_time": i * 10.0, "end_time": i * 10.0 + 10, "value": 1.0 if i == 3 else 0.2} for i in range(20)]
check("the most replayed stretch is found", media.replay_peaks(url), [(30.0, 40.0)])
media._HEAT[url] = [{"start_time": i * 10.0, "end_time": i * 10.0 + 10, "value": 0.3} for i in range(20)]
check("a flat graph has no peaks", media.replay_peaks(url), [])
check("no graph, no peaks", media.replay_peaks("https://www.youtube.com/watch?v=none"), [])
marked = brain._fmt(brain.make_lines(words, hot=lambda s, e: s < 5))
check("lines in a replayed stretch are marked (HOT) for the AI", marked.splitlines()[0].count("(HOT)") == 1 and "(HOT)" not in marked.splitlines()[-1], True)

# ---- the second look at every clip (the AI is replaced by fixed answers here)
base = [{"start": words[0]["s"], "end": words[40]["e"], "score": 70, "hook": "X", "title": "t", "reason": "r"},
        {"start": words[45]["s"], "end": words[-1]["e"], "score": 60, "hook": "Y", "title": "t", "reason": "r"}]
seen_prompt = []
def fake(answer):
    def ask(prompt, schema=None, purpose="", timeout=None):
        seen_prompt.append(prompt)
        return answer, "m", 1234
    return ask
brain.ask_ai = fake([{"id": "C1", "hook": 4, "payoff": 4, "stands_alone": True, "verdict": "trim",
                      "first_words": "kyunki gta 6 mein tum", "last_words": "tough hone wala hai", "note": "tighter"},
                     {"id": "C2", "hook": 0, "payoff": 1, "stands_alone": False, "verdict": "drop",
                      "first_words": "", "last_words": "", "note": "no payoff"}])
out, spent = brain.review_clips([dict(c) for c in base], words, "GTA 6", 10, 60, dur)
check("a weak clip is dropped", len(out), 1)
check("a trimmed clip starts on the new quoted words", abs(out[0]["start"] - (words[first]["s"] - 0.15)) < 0.01, True)
check("...and ends on them", words[last]["e"] <= out[0]["end"] <= words[last]["e"] + 0.36, True)
check("the tokens are counted", spent, 1234)
check("the check never sees the first pass's hook or score", "X" not in seen_prompt[-1].split("Video title")[1] and "70" not in seen_prompt[-1], True)
check("it sees the words after the clip, marked as not in it", "AFTER (not in the clip)" in seen_prompt[-1], True)

brain.ask_ai = fake([{"id": "C1", "hook": 0, "payoff": 0, "stands_alone": False, "verdict": "drop", "first_words": "", "last_words": "", "note": ""},
                     {"id": "C2", "hook": 1, "payoff": 1, "stands_alone": False, "verdict": "drop", "first_words": "", "last_words": "", "note": ""}])
out, _ = brain.review_clips([dict(c) for c in base], words, "", 10, 60, dur)
check("when every clip is dropped, the best one is still kept", [c["start"] for c in out], [base[1]["start"]])

def broken(*a, **k):
    raise RuntimeError("HTTP 500")
brain.ask_ai = broken
out, spent = brain.review_clips([dict(c) for c in base], words, "", 10, 60, dur)
check("when the AI fails, the clips come back unchanged", ([c["start"] for c in out], spent), ([c["start"] for c in base], 0))

# ---- Hindi from our own transcript: Whisper through mlx-whisper (replaced by a stand-in here)
import types
import numpy as np
from studio import config, transcribe
check("English by default: the fast English model, no language set", transcribe.language(), "")
config.ASR_LANG = "hi"
real = sys.modules.get("mlx_whisper")
sys.modules["mlx_whisper"] = None                      # not installed
check("Hindi asked for but mlx-whisper missing: the English model, said plainly", transcribe.language(), "")
calls = []
def fake_transcribe(audio, **kw):
    calls.append(kw)
    return {"segments": [{"words": [{"word": " GTA", "start": 0.0, "end": 0.4}, {"word": " \u092e\u0947\u0902", "start": 0.5, "end": 0.7},
                                     {"word": " ", "start": 0.8, "end": 0.9}]}]}
sys.modules["mlx_whisper"] = types.SimpleNamespace(transcribe=fake_transcribe)
check("with mlx-whisper the transcript is Hindi", transcribe.language(), "hi")
got = transcribe.transcribe(np.zeros(16000, dtype=np.int16))
check("Whisper's words come back in PeakCut's shape, empty ones left out", got, [{"w": "GTA", "s": 0.0, "e": 0.4}, {"w": "\u092e\u0947\u0902", "s": 0.5, "e": 0.7}])
check("Whisper is told the language and asked for word times", (calls[0]["language"], calls[0]["word_timestamps"]), ("hi", True))
config.ASR_LANG = "en"
if real is None: sys.modules.pop("mlx_whisper", None)
else: sys.modules["mlx_whisper"] = real

print("ALL PASSED" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
