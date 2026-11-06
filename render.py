import asyncio, json, math, os, re, subprocess, sys, time, urllib.parse
import requests
import edge_tts
 
OUT, WORK = "out", "work"
W, H, FPS = 1280, 720, 25
MUSIC = "music/background.mp3"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
VOICES = {
    "arabic": "ar-SA-HamedNeural", "english": "en-US-GuyNeural", "french": "fr-FR-HenriNeural",
    "spanish": "es-ES-AlvaroNeural", "german": "de-DE-ConradNeural", "turkish": "tr-TR-AhmetNeural",
}
VOICE = "en-US-GuyNeural"
RATE = os.environ.get("VOICE_RATE", "-5%")
 
 
def run(cmd):
    print(">>", " ".join(cmd)[:300], flush=True)
    subprocess.run(cmd, check=True)
 
 
def set_output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")
 
 
def get_topic():
    topic = os.environ.get("TOPIC", "").strip()
    typ = os.environ.get("TYPE", "").strip() or "myth"
    lang = os.environ.get("LANGUAGE", "").strip() or "Arabic"
    if topic:
        return typ, topic, lang, False
    if not os.path.exists("topics.txt"):
        return None
    lines = open("topics.txt", encoding="utf-8").read().splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split("|")]
        if len(parts) == 3:
            typ, topic, lang = parts
        else:
            topic = s
        del lines[i]
        with open("topics.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return typ, topic, lang, True
    return None
 
 
def generate_script(typ, topic, lang):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit("GEMINI_API_KEY is missing. Add it in Settings > Secrets and variables > Actions.")
    system = ("You are a senior scriptwriter for a YouTube channel that publishes documentaries and mythical tales. "
              "You write gripping, accurate narration for voice-over. You never invent facts. If something is legend, "
              "uncertain, or disputed, you say so in the narration. Plain spoken language: short sentences, no markdown, "
              "no stage directions inside narration.")
    prompt = f"""Write a video script.
 
TOPIC: {topic}
TYPE: {typ} (documentary or myth)
LANGUAGE: {lang}
TARGET LENGTH: 8 to 10 minutes (about 1300 to 1600 spoken words)
 
Write the title, description, tags, narration and thumbnail overlay_text in {lang}.
Write every image_prompt, the style_guide and thumbnail.image_prompt in English.
 
STRUCTURE:
1. Hook (first 15 seconds): a surprising question, image, or claim. No greetings.
2. Setup: context the viewer needs.
3. Three to five story beats, each building tension or curiosity.
4. Turning point or twist.
5. Resolution and reflection: what this story means or what historians still debate.
6. One short closing sentence inviting viewers to comment.
 
DOCUMENTARY: only state facts you are confident about, attribute disputed claims, list real sources in sources.
MYTH: tell it as a story, name the culture and original source texts, mention major variants.
 
SCENES: 10 to 16 scenes of 20 to 45 seconds each. For every scene write an image_prompt describing ONE concrete visual: subject, setting, lighting, composition. No text, logos or real living people in images. Keep the visual style consistent with style_guide.
 
TITLE: under 70 characters, curiosity-driven, no clickbait lies.
DESCRIPTION: 150 to 250 words, first two lines contain the main keywords, end with the sources list.
TAGS: 10 to 15 tags.
THUMBNAIL: 3 to 5 word overlay_text and an image_prompt with a strong single focal point.
 
Return ONLY the JSON object matching the schema."""
    S = lambda t: {"type": t}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.8, "responseMimeType": "application/json",
            "responseSchema": {"type": "OBJECT", "properties": {
                "title": S("STRING"), "description": S("STRING"),
                "tags": {"type": "ARRAY", "items": S("STRING")},
                "style_guide": S("STRING"),
                "sources": {"type": "ARRAY", "items": S("STRING")},
                "thumbnail": {"type": "OBJECT", "properties": {"overlay_text": S("STRING"), "image_prompt": S("STRING")},
                              "required": ["overlay_text", "image_prompt"]},
                "scenes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                    "id": S("INTEGER"), "narration": S("STRING"), "image_prompt": S("STRING")},
                    "required": ["id", "narration", "image_prompt"]}}},
                "required": ["title", "description", "tags", "style_guide", "sources", "thumbnail", "scenes"]}}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    last = ""
    for attempt in range(5):
        try:
            r = requests.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json=body, timeout=300)
            if r.status_code == 200:
                parts = r.json()["candidates"][0]["content"]["parts"]
                script = json.loads("".join(p.get("text", "") for p in parts), strict=False)
                if script.get("scenes"):
                    return script
                last = "no scenes in answer"
            elif r.status_code in (400, 401, 403):
                raise SystemExit(f"Gemini rejected the request ({r.status_code}): {r.text[:300]}")
            else:
                last = f"HTTP {r.status_code}: {r.text[:300]}"
        except SystemExit:
            raise
        except Exception as e:
            last = str(e)
        print("Gemini retry:", last, flush=True)
        time.sleep(10 * (attempt + 1))
    raise SystemExit("Gemini failed: " + last)
 
 
def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", path])
    return float(out)
 
 
def tts(text, path):
    for attempt in range(4):
        try:
            asyncio.run(edge_tts.Communicate(text, VOICE, rate=RATE).save(path))
            if os.path.getsize(path) > 1000:
                return
        except Exception as e:
            print("tts retry:", e)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("TTS failed for: " + text[:60])
 
 
def fetch_image(prompt, style, seed, path):
    full = f"{style}, {prompt}"[:900]
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(full) +
           f"?width={W}&height={H}&model=flux&nologo=true&seed={seed}")
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=180)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                with open(path, "wb") as f:
                    f.write(r.content)
                return True
            print("image status", r.status_code)
        except Exception as e:
            print("image retry:", e)
        time.sleep(8 * (attempt + 1))
    return False
 
 
def fallback_image(path):
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x16213e:s={W}x{H}",
         "-frames:v", "1", path])
 
 
def ts(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"
 
 
def chunks(text, max_words=9):
    out = []
    for s in re.split(r"(?<=[.!?\u061f\u2026])\s+", text.strip()):
        words = s.split()
        for i in range(0, len(words), max_words):
            out.append(" ".join(words[i:i + max_words]))
    return [c for c in out if c]
 
 
def main():
    global VOICE
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    picked = get_topic()
    if not picked:
        print("No topic found. Run the workflow with a topic, or add lines to topics.txt.")
        set_output("has_topic", "false")
        set_output("from_queue", "false")
        return
    typ, topic, lang, from_queue = picked
    set_output("has_topic", "true")
    set_output("from_queue", "true" if from_queue else "false")
    VOICE = os.environ.get("VOICE", "").strip() or VOICES.get(lang.lower(), "en-US-GuyNeural")
    print(f"Topic: {topic} | type: {typ} | language: {lang} | voice: {VOICE}", flush=True)
 
    script = generate_script(typ, topic, lang)
    scenes = script["scenes"]
    style = script.get("style_guide", "cinematic illustration, no text")
    with open(f"{OUT}/script.json", "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
 
    title = script["title"].strip()[:95]
    desc = script["description"].strip() + "\n\nVisuals and narration in this video are AI-generated."
    tags, total = [], 0
    for t in script.get("tags", []):
        t = t.replace(",", " ").strip()
        if t and total + len(t) < 450:
            tags.append(t)
            total += len(t) + 1
    with open(f"{OUT}/meta.json", "w", encoding="utf-8") as f:
        json.dump({"title": title, "description": desc, "tags": tags}, f, ensure_ascii=False)
    with open(f"{OUT}/youtube_info.txt", "w", encoding="utf-8") as f:
        f.write(f"TITLE:\n{title}\n\nDESCRIPTION:\n{desc}\n\nTAGS:\n{', '.join(tags)}\n")
 
    clips, srt, t0, idx = [], [], 0.0, 1
    for i, sc in enumerate(scenes, start=1):
        print(f"=== Scene {i}/{len(scenes)}", flush=True)
        aud, img, clip = f"{WORK}/s{i}.mp3", f"{WORK}/s{i}.jpg", f"{WORK}/c{i}.mp4"
        tts(sc["narration"], aud)
        speech = duration(aud)
        dur = speech + 0.5
        if not fetch_image(sc["image_prompt"], style, i, img):
            fallback_image(img)
        time.sleep(2)
        frames = int(dur * FPS) + 1
        zoom = "min(zoom+0.0005,1.12)" if i % 2 else "if(eq(on,1),1.12,max(zoom-0.0005,1.0))"
        vf = (f"scale=1920:-1,zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps={FPS},format=yuv420p")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", img, "-i", aud, "-vf", vf, "-af", "apad",
             "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
             "-maxrate", "900k", "-bufsize", "1800k", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "2", clip])
        clips.append(clip)
        parts = chunks(sc["narration"])
        tot = sum(len(p) for p in parts) or 1
        cur = t0
        for p in parts:
            span = speech * len(p) / tot
            srt.append(f"{idx}\n{ts(cur)} --> {ts(cur + span)}\n{p}\n")
            idx += 1
            cur += span
        t0 += dur
 
    with open(f"{WORK}/subs.srt", "w", encoding="utf-8") as f:
        f.write("\n".join(srt))
    with open(f"{WORK}/list.txt", "w") as f:
        for c in clips:
            f.write(f"file '{os.path.basename(c)}'\n")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{WORK}/list.txt",
         "-c", "copy", f"{WORK}/joined.mp4"])
 
    sub = (f"subtitles={WORK}/subs.srt:force_style='FontName=DejaVu Sans,FontSize=16,"
           "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=30'")
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-maxrate", "900k", "-bufsize", "1800k"]
    if os.path.exists(MUSIC):
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{WORK}/joined.mp4", "-stream_loop", "-1", "-i", MUSIC,
             "-filter_complex",
             f"[0:v]{sub}[v];[1:a]volume=0.08[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "[v]", "-map", "[a]", *enc, "-c:a", "aac", "-b:a", "96k",
             "-movflags", "+faststart", f"{OUT}/final.mp4"])
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{WORK}/joined.mp4", "-vf", sub, *enc,
             "-c:a", "copy", "-movflags", "+faststart", f"{OUT}/final.mp4"])
    print(f"final.mp4 size: {os.path.getsize(OUT + '/final.mp4') / 1e6:.1f} MB", flush=True)
 
    # Thumbnail
    th = script.get("thumbnail", {})
    base = f"{WORK}/thumb_base.jpg"
    if not fetch_image(th.get("image_prompt", scenes[0]["image_prompt"]), style, 999, base):
        fallback_image(base)
    text = th.get("overlay_text", title).strip()
    if re.search(r"[\u0600-\u06FF]", text):
        # drawtext cannot join Arabic letters correctly, so keep the picture clean
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", base, "-frames:v", "1", "-q:v", "3", f"{OUT}/thumb.jpg"])
    else:
        words = text.upper().split()
        mid = math.ceil(len(words) / 2) if len(words) > 2 else len(words)
        with open(f"{WORK}/thumb.txt", "w", encoding="utf-8") as f:
            f.write(" ".join(words[:mid]) + ("\n" + " ".join(words[mid:]) if words[mid:] else ""))
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", base, "-vf",
             f"drawtext=fontfile={FONT}:textfile={WORK}/thumb.txt:fontsize=90:fontcolor=white:"
             "borderw=6:bordercolor=black:line_spacing=8:x=(w-text_w)/2:y=h-text_h-60",
             "-frames:v", "1", "-q:v", "3", f"{OUT}/thumb.jpg"])
    print("DONE", flush=True)
 
 
def notify():
    url = os.environ.get("MAKE_WEBHOOK_URL", "").strip()
    if not url:
        print("No MAKE_WEBHOOK_URL secret set, skipping.")
        return
    meta = json.load(open(f"{OUT}/meta.json", encoding="utf-8"))
    base = f"https://github.com/{os.environ['REPO']}/releases/download/{os.environ['TAG']}"
    payload = {**meta, "tags_csv": ",".join(meta["tags"]), "video_url": f"{base}/final.mp4",
               "thumb_url": f"{base}/thumb.jpg", "script_url": f"{base}/script.json"}
    r = requests.post(url, json=payload, timeout=60)
    print("Make answered", r.status_code, r.text[:200])
    r.raise_for_status()
 
 
if __name__ == "__main__":
    notify() if len(sys.argv) > 1 and sys.argv[1] == "notify" else main()
 
