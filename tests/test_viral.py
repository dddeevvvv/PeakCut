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
clip = rclip = {"start": s, "end": e, "score": 70, "hook": "X", "title": "t", "reason": "r"}
brain.ask_ai = fake([row])
out, _ = brain.review_clips([dict(clip)], words, "", 10, 60, dur)
c = out[0]
check("the review gives the new score", c["score"], V(70, 2, 5, 4, 3, True, c["end"] - c["start"]))
check("the parts of the score are kept for the app", c["virality"], {"hook": 2, "payoff": 5, "emotion": 4, "loop": 3, "alone": True, "streamer": False})
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

# ---- auto-post guard for live clips
from studio import posting
brain.ask_ai = fake([dict(row, streamer_reacts=True)])
out, _ = brain.review_clips([dict(rclip)], words, "", 10, 60, dur)
check("the check says whether the streamer is in the clip", out[0]["virality"]["streamer"], True)
brain.ask_ai = fake([dict(row, verdict="drop")])
out, _ = brain.review_clips([dict(rclip)], words, "", 10, 60, dur)
check("a lone clip the check would drop is kept but marked weak", out[0].get("weak"), True)
(work / "clips").mkdir(exist_ok=True)
live = {"kind": "live", "dir": str(work)}
good = {"file": "../out/cold.mp4", "virality": {"streamer": True}}
brain.looks_like_cutscene = lambda jpeg, timeout=None: False
check("an uploaded video's clips get the same guard", "did not run" in posting.held_back({"kind": "video", "dir": str(work)}, {"file": "x.mp4"}), True)
check("a live clip the check never saw is held back", "did not run" in posting.held_back(live, {"file": "x.mp4"}), True)
check("a weak live clip is held back", "weak" in posting.held_back(live, dict(good, weak=True)), True)
check("a live clip with no streamer in it is held back", "not the streamer" in posting.held_back(live, {"file": "x.mp4", "virality": {"streamer": False}}), True)
check("a good gameplay clip with the streamer may post", posting.held_back(live, good), "")
brain.looks_like_cutscene = lambda jpeg, timeout=None: True
check("a cutscene is held back even when the streamer talks", "cutscene" in posting.held_back(live, good), True)
brain.looks_like_cutscene = lambda jpeg, timeout=None: None
check("when the picture check can't tell, the words checks decide", posting.held_back(live, good), "")
frames = posting._frames(work / "out" / "cold.mp4")
check("three frames of a clip make one picture for the check", frames[:2], b"\xff\xd8")

# ---- videos filed under no creator post with the auto-posting creator's settings
from studio import creators as _cr
real_all, real_get = _cr.all_creators, _cr.get
_cr.get = lambda cid: None
_cr.all_creators = lambda: [{"name": "Zed", "autopost": True, "accounts": ["a"], "post_footer": "Credit: Z"},
                            {"name": "Ann", "autopost": True, "accounts": ["b"], "post_footer": "Credit: A"},
                            {"name": "Off", "autopost": False, "accounts": ["c"], "post_footer": ""}]
p = posting.poster({"creator": None})
check("a video with no creator uses an auto-posting creator's settings", p["accounts"], ["b"])
check("...without that creator's own credit line", p["post_footer"], "")
_cr.all_creators = lambda: []
check("nothing auto-posts when no creator is set up for it", posting.poster({"creator": None}), None)
_cr.all_creators, _cr.get = real_all, real_get

# ---- the big text: the check writes a "don't miss this" line
brain.ask_ai = fake([dict(row, hook_text="wait for his reaction")])
out, _ = brain.review_clips([dict(rclip)], words, "", 10, 60, dur)
check("the check's big text replaces the first one", out[0]["hook"], "WAIT FOR HIS REACTION")
brain.ask_ai = fake([dict(row, hook_text="")])
out, _ = brain.review_clips([dict(rclip)], words, "", 10, 60, dur)
check("no big text from the check keeps the first one", out[0]["hook"], "X")

# ---- facecam on top
f = render._filter("stack", 1920, (60, 300, 240, 135))
check("stack: the webcam fills a band on top and the game the rest", "vstack" in f and "crop=240:135:60:300" in f, True)
check("stack: the band follows the webcam's shape", render._stack_top((0, 0, 240, 135)), 608)
check("stack: a tall webcam band is capped", render._stack_top((0, 0, 100, 100)), 760)
check("stack with no webcam found: the game fills the screen", "vstack" not in render._filter("stack", 1920, None), True)
check("stack: the big text sits just below the face", render._hook_y("stack", 300, (0, 0, 240, 135)), 698)
render.render_clip(src, work / "out", "stack", dict(base, start=10.0, end=18.0, teaser=None, layout="stack", facecam=[60, 300, 240, 135], hook="X"), ws, 640, 360)
check("a stacked clip renders at full size", abs(length(work / "out" / "stack.mp4") - 8.0) < 0.3, True)

# ---- each streamer's own language
from studio import creators, transcribe
check("a creator can be set to Hindi", creators._clean({"lang": "HI"})["lang"], "hi")
check("a bad language falls back to the server's", creators._clean({"lang": "hindi!"})["lang"], "")
check("a video's options keep the language", jobs.clean_options({"lang": "hi"})["lang"], "hi")
check("no language set: the server's is used", transcribe.pick_lang(None), transcribe.config.ASR_LANG)
check("a mixed streamer is detected per piece", creators._clean({"lang": "auto"})["lang"], "auto")
check("a looping Whisper piece is dropped", transcribe._looping({"text": "I'm so out I'm so out I'm so out I'm so out I'm so out"}), True)
check("a normal Whisper piece is kept", transcribe._looping({"text": "bhai ye animation dekho kya mast hai yaar", "compression_ratio": 1.2}), False)
check("the creator's language wins", transcribe.pick_lang("hi"), "hi")

# ---- sound stays on time when the stream drops audio
import subprocess
import numpy as np
beep = work / "beep.ts"     # a beep at 15 s, then a 1 s hole in the sound before it
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=25", "-f", "lavfi",
                "-i", "aevalsrc='if(between(t,15,15.1),sin(2*PI*1000*t),0)':s=48000:d=25", "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-f", "mpegts", str(beep)], check=True)
gap = work / "gap.ts"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-copyts", "-i", str(beep), "-map", "0", "-c", "copy",
                "-bsf:a", "noise=drop='between(pts*tb-1.4,12,13)'", "-muxdelay", "0", "-muxpreload", "0", str(gap)], check=True)
render.render_clip(gap, work / "gapout", "crop", dict(base, start=10.0, end=18.0, teaser=None, layout="crop", hook="X"), ws, 640, 360)
pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(work / "gapout" / "crop.mp4"), "-map", "0:a:0", "-ac", "1", "-ar", "8000",
                      "-f", "s16le", "-"], capture_output=True).stdout
x = np.abs(np.frombuffer(pcm, np.int16).astype(float))
check("a hole in the sound is filled, so the beep stays on time", abs(np.argmax(x > x.max() / 2) / 8000 - 5.0) < 0.08, True)

# ---- Mixed language never comes out as Russian junk
import numpy as np
_asked = []
class _MW:
    def transcribe(self, seg, language=None, **k):
        _asked.append(language)
        if language == "hi" and len(_asked) == 4:
            return {"language": "hi", "segments": [{"text": "so out so out so out so out so out", "words": []}]}
        return {"language": language, "segments": [{"text": "bhai dekho", "words": [{"word": "bhai", "start": 0, "end": 0.5}]}]}
_old = transcribe._mlx_whisper
transcribe._mlx_whisper = lambda: _MW()
check("a Mixed piece is written in Hindi, never translated", [w["w"] for w in transcribe._transcribe_whisper(np.zeros(16000, np.int16), lang="auto")], ["bhai"])
check("the language asked: Hindi", _asked, ["hi"])
_asked.extend(["x", "y"])
transcribe._transcribe_whisper(np.zeros(16000, np.int16), lang="auto")
check("where Hindi loops, English is asked", _asked[3:], ["hi", "en"])
transcribe._mlx_whisper = _old

# ---- -copyts recordings: the first piece's list entry spans the stream's whole clock
from studio import live
import threading
rec = work / "rec"; rec.mkdir()
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=20", "-c:v", "libx264",
                "-g", "60", "-preset", "ultrafast", "-output_ts_offset", "24271", "-f", "mpegts", str(rec / "v.ts")], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=18", "-c:a", "aac", "-output_ts_offset", "24273",
                "-f", "mpegts", str(rec / "a.ts")], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-copyts", "-i", str(rec / "v.ts"), "-i", str(rec / "a.ts"), "-map", "0:v:0", "-map", "1:a:0",
                "-c", "copy", "-f", "segment", "-segment_time", "6", "-reset_timestamps", "1", "-segment_format", "mpegts",
                "-segment_list", str(rec / "p01.csv"), "-segment_list_type", "csv", str(rec / "p01_%05d.ts")], check=True)
sess = object.__new__(live.Session)
sess.lock, sess.buf, sess.part, sess.csv_seen, sess.segments, sess.seg_clock = threading.RLock(), rec, 1, {}, [], 0.0
sess.settings = {"buffer_min": 20}
sess._scan_segments()
check("a -copyts recording's pieces keep their real lengths", all(0 < b - a < 8 for _, a, b in sess.segments) and sess.seg_clock < 25, True)

# ---- disk: old source cuts and ended recordings' buffers are cleared, finished clips stay
from studio import disk
import time
dd = work / "disk"; (dd / "clips").mkdir(parents=True); (dd / "buffer").mkdir()
for n in ("clips/c1.src.ts", "clips/c1.mp4", "clips/c2.src.ts", "buffer/p01_00001.ts"):
    (dd / n).write_bytes(b"x" * 1000)
djob = {"id": "dj", "kind": "live", "dir": str(dd), "status": "done", "clips": [
    {"id": "c1", "status": "done", "made_at": time.time() - 3 * 86400, "src": str(dd / "clips/c1.src.ts"), "src_offset": 1},
    {"id": "c2", "status": "done", "made_at": time.time() - 3600, "src": str(dd / "clips/c2.src.ts")}]}
_aj, _sv = jobs.all_jobs, jobs.save
jobs.all_jobs, jobs.save = (lambda: [djob]), (lambda j: None)
freed = disk.sweep()
jobs.all_jobs, jobs.save = _aj, _sv
check("a 3-day-old source cut is cleared, the clip stays", [(dd / "clips/c1.src.ts").exists(), (dd / "clips/c1.mp4").exists(), djob["clips"][0].get("src_gone")], [False, True, True])
check("a 1-hour-old source cut stays", (dd / "clips/c2.src.ts").exists(), True)
check("an ended recording's buffer is cleared", list((dd / "buffer").glob("*")), [])
check("bytes freed are counted", freed, 2000)

# ---- YouTube live chat
from studio import ytchat
page = {"continuationContents": {"liveChatContinuation": {
    "continuations": [{"timedContinuationData": {"continuation": "NEXT", "timeoutMs": 3000}}],
    "actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {"timestampUsec": "1700000000500000", "authorExternalChannelId": "UCa"}}}},
                {"addChatItemAction": {"item": {"liveChatPaidMessageRenderer": {"timestampUsec": "1700000001000000", "authorExternalChannelId": "UCb"}}}},
                {"markChatItemAsDeletedAction": {}}]}}}
got, nxt = ytchat.messages(page)
check("chat messages are read with their time, author and Super Chat", got, [(1700000000.5, "UCa", False), (1700000001.0, "UCb", True)])
check("the next chat page and the wait are read", nxt, ("NEXT", 3.0))
check("an empty chat page ends the reading", ytchat.messages({}), ([], (None, 5.0)))

print("ALL PASSED" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
