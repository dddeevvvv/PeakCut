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

print("ALL PASSED" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
