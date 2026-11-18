"""YouTube live chat, read the way the chat pop-out reads it: no API key, no sign-in.

Only what the clip finder needs comes out: for each message, when it was sent, who sent it, and whether it was a
Super Chat. Subscriber-only chats still show their messages to everyone, so they are counted too."""
import json
import re
import time
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_KEY = re.compile(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"')
_VER = re.compile(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"')
_CONT = re.compile(r'"continuation"\s*:\s*"([^"]+)"')


def _get(url, body=None, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                                          **({"Content-Type": "application/json"} if body is not None else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def start(video_id):
    """(api key, client version, first continuation) for a live video's chat. Raises if it has no live chat."""
    html = _get(f"https://www.youtube.com/live_chat?is_popout=1&v={video_id}")
    key, ver, cont = _KEY.search(html), _VER.search(html), _CONT.search(html)
    if not (ver and cont):
        raise RuntimeError("This stream has no live chat to read.")
    return (key.group(1) if key else ""), ver.group(1), cont.group(1)


def messages(data: dict):
    """[(sent at, epoch seconds; author id; is a Super Chat)], and (next continuation, wait in seconds)."""
    lc = (data.get("continuationContents") or {}).get("liveChatContinuation") or {}
    out = []
    for a in lc.get("actions") or []:
        item = (a.get("addChatItemAction") or {}).get("item") or {}
        for kind, paid in (("liveChatTextMessageRenderer", False), ("liveChatPaidMessageRenderer", True),
                           ("liveChatPaidStickerRenderer", True)):
            r = item.get(kind)
            if r:
                try:
                    t = int(r.get("timestampUsec", 0)) / 1e6
                except ValueError:
                    t = 0
                out.append((t or time.time(), r.get("authorExternalChannelId") or "", paid))
    nxt, wait = None, 5.0
    for c in lc.get("continuations") or []:
        for v in c.values():
            if isinstance(v, dict) and v.get("continuation"):
                nxt = v["continuation"]
                wait = max(1.0, min(10.0, int(v.get("timeoutMs", 5000)) / 1000))
                break
        if nxt:
            break
    return out, (nxt, wait)


def follow(video_id, on_message, stop):
    """Read the chat until `stop()` is true or the chat ends. on_message(sent_at, author, paid) for each one."""
    key, ver, cont = start(video_id)
    url = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat" + (f"?key={key}" if key else "")
    while cont and not stop():
        data = json.loads(_get(url, {"context": {"client": {"clientName": "WEB", "clientVersion": ver}},
                                     "continuation": cont}))
        got, (cont, wait) = messages(data)
        for m in got:
            on_message(*m)
        end = time.time() + wait
        while time.time() < end and not stop():
            time.sleep(0.5)
