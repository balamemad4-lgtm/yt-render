import asyncio, json, math, os, re, subprocess, sys, time, urllib.parse
import requests
import edge_tts

OUT, WORK = "out", "work"
W, H, FPS = 720, 1280, 25          # vertical 9:16 = YouTube Shorts
AUDIO_K = 64                       # audio kbps
TARGET_BYTES = 4_400_000           # stay under Make free plan 5 MB file limit
MAX_SECS = 58.0
MUSIC = "music/background.mp3"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
VOICES = {
    "english": "en-GB-RyanNeural", "arabic": "ar-SA-HamedNeural", "french": "fr-FR-HenriNeural",
    "spanish": "es-ES-AlvaroNeural", "german": "de-DE-ConradNeural", "turkish": "tr-TR-AhmetNeural",
}
VOICE = "en-GB-RyanNeural"
RATE = os.environ.get("VOICE_RATE", "-5%")


def run(cmd):
    print(">>", " ".join(cmd)[:300], flush=True)
    subprocess.run(cmd, check=True)


def set_output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


# ---------------------------------------------------------------- LLM (Groq)
def llm_json(system, prompt, schema, temperature=0.8):
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("GROQ_API_KEY is missing. Add it in Settings > Secrets and variables > Actions.")
    full_system = (system + "\nReturn ONLY a valid JSON object (no markdown, no commentary) "
                   "matching this JSON schema: " + json.dumps(schema, ensure_ascii=False))
    body = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": full_system},
            {"role": "user", "content": prompt + "\n\nRespond in JSON."},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    last = ""
    for attempt in range(6):
        try:
            r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}",
                                                 "Content-Type": "application/json"},
                              json=body, timeout=300)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"]
                return json.loads(content, strict=False)
            if r.status_code in (400, 401, 403):
                raise SystemExit(f"Groq rejected the request ({r.status_code}): {r.text[:300]}")
            last = f"HTTP {r.status_code}: {r.text[:300]}"
        except SystemExit:
            raise
        except Exception as e:
            last = str(e)
        print("LLM retry:", last, flush=True)
        time.sleep(10 * (attempt + 1))
    raise SystemExit("LLM failed: " + last)


def read_used():
    if not os.path.exists("used_topics.txt"):
        return []
    return [l.strip() for l in open("used_topics.txt", encoding="utf-8").read().splitlines() if l.strip()]


def remember(topic):
    with open("used_topics.txt", "a", encoding="utf-8") as f:
        f.write(topic.strip() + "\n")


def suggest_topic(lang):
    used = read_used()
    typ = "myth" if len(used) % 2 == 0 else "documentary"
    system = "You are the content planner of a YouTube channel about documentaries and mythical tales."
    prompt = (f"Suggest ONE new video topic for the type: {typ}. It must be specific, with a strong story and "
              "real curiosity value (for a myth: one specific tale; for a documentary: one specific, well "
              f"documented historical event, place, person or mystery). Write it in {lang} as a short topic phrase. "
              f"Do NOT repeat or closely resemble any of these already used topics: {used[-150:]}. "
              'Return ONLY JSON like {"topic": "..."}')
    schema = {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}
    data = llm_json(system, prompt, schema, 1.0)
    return typ, data["topic"].strip()


def get_topic():
    """Order: topic typed by hand -> next line of topics.txt -> topic invented by the LLM."""
    topic = os.environ.get("TOPIC", "").strip()
    typ = os.environ.get("TYPE", "").strip()
    lang = os.environ.get("LANGUAGE", "").strip() or "English"
    for name in ("topics.txt", "used_topics.txt"):
        if not os.path.exists(name):
            open(name, "a").close()
    if topic:
        return typ or "myth", topic, lang
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
        return typ or "myth", topic, lang
    typ2, topic = suggest_topic(lang)
    return typ or typ2, topic, lang


def generate_script(typ, topic, lang):
    system = ("You are a senior scriptwriter for a YouTube channel that publishes documentaries and mythical tales. "
              "You write gripping, accurate, fast-paced narration for short vertical videos. You never invent facts. "
              "If something is legend, uncertain, or disputed, you say so in the narration. Plain spoken language: "
              "short sentences, no markdown, no stage directions inside narration.")
    prompt = f"""Write a script for a YouTube Short (vertical video).

TOPIC: {topic}
TYPE: {typ} (documentary or myth)
LANGUAGE: {lang}
LENGTH: 45 to 55 seconds when spoken = 110 to 130 words in total. Never more than 130 words.

Write the title, description, tags and narration in {lang}.
Write every image_prompt and the style_guide in English.

STRUCTURE (fast, punchy):
1. Hook in the first sentence: a surprising fact, question or claim. No greetings, no "welcome".
2. Three or four quick story beats that keep the viewer curious.
3. A twist or a striking final fact.
4. One short closing line that makes people want to comment or watch again.

DOCUMENTARY: only state facts you are confident about; attribute anything disputed.
MYTH: tell it as a story and say which culture or text it comes from.

SCENES: exactly 5 to 7 scenes of 6 to 10 seconds each. For every scene write an image_prompt describing ONE concrete
visual in vertical 9:16 composition: subject, setting, lighting. No text, logos or real living people in the images.
Keep the visual style consistent with style_guide.

TITLE: at most 60 characters, curiosity-driven, no clickbait lies, no hashtags.
DESCRIPTION: 2 to 3 sentences, then the hashtags #Shorts plus two topic hashtags.
TAGS: 8 to 12 tags.

Return ONLY the JSON object matching the schema."""
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "style_guide": {"type": "string"},
            "scenes": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "narration": {"type": "string"},
                    "image_prompt": {"type": "string"},
                },
                "required": ["id", "narration", "image_prompt"],
            }},
        },
        "required": ["title", "description", "tags", "style_guide", "scenes"],
    }
    for attempt in range(3):
        script = llm_json(system, prompt, schema, 0.8)
        if len(script.get("scenes", [])) >= 4:
            return script
        print("Script too short, trying again", flush=True)
    raise SystemExit("LLM returned a script with too few scenes.")


# ---------------------------------------------------------------- media helpers
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
    full = f"{style}, {prompt}, vertical composition"[:900]
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


def chunks(text, max_words=5):
    out = []
    for s in re.split(r"(?<=[.!?\u061f\u2026])\s+", text.strip()):
        words = s.split()
        for i in range(0, len(words), max_words):
            out.append(" ".join(words[i:i + max_words]))
    return [c for c in out if c]


# ---------------------------------------------------------------- main job
def main():
    global VOICE
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    typ, topic, lang = get_topic()
    remember(topic)
    set_output("has_topic", "true")
    VOICE = os.environ.get("VOICE", "").strip() or VOICES.get(lang.lower(), "en-GB-RyanNeural")
    print(f"Topic: {topic} | type: {typ} | language: {lang} | voice: {VOICE}", flush=True)

    script = generate_script(typ, topic, lang)
    scenes = script["scenes"]
    style = script.get("style_guide", "cinematic illustration, no text")
    with open(f"{OUT}/script.json", "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    title = script["title"].strip().replace("#Shorts", "").strip()[:88]
    title = f"{title} #Shorts"
    desc = script["description"].strip()
    if "#shorts" not in desc.lower():
        desc += "\n\n#Shorts"
    desc += "\n\nVisuals and narration in this video are AI-generated."
    tags, total_len = [], 0
    for t in script.get("tags", []):
        t = t.replace(",", " ").strip()
        if t and total_len + len(t) < 450:
            tags.append(t)
            total_len += len(t) + 1
    with open(f"{OUT}/meta.json", "w", encoding="utf-8") as f:
        json.dump({"title": title, "description": desc, "tags": tags}, f, ensure_ascii=False)
    with open(f"{OUT}/youtube_info.txt", "w", encoding="utf-8") as f:
        f.write(f"TITLE:\n{title}\n\nDESCRIPTION:\n{desc}\n\nTAGS:\n{', '.join(tags)}\n")

    clips, spans = [], []
    for i, sc in enumerate(scenes, start=1):
        print(f"=== Scene {i}/{len(scenes)}", flush=True)
        aud, img, clip = f"{WORK}/s{i}.mp3", f"{WORK}/s{i}.jpg", f"{WORK}/c{i}.mp4"
        tts(sc["narration"], aud)
        speech = duration(aud)
        dur = speech + 0.4
        if not fetch_image(sc["image_prompt"], style, i, img):
            fallback_image(img)
        time.sleep(2)
        frames = int(dur * FPS) + 1
        zoom = "min(zoom+0.0006,1.15)" if i % 2 else "if(eq(on,1),1.15,max(zoom-0.0006,1.0))"
        vf = (f"scale=1080:-1,zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps={FPS},format=yuv420p")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", img, "-i", aud, "-vf", vf, "-af", "apad",
             "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", clip])
        clips.append(clip)
        spans.append((sc["narration"], speech, dur))

    total = sum(d for _, _, d in spans)
    speed = min(total / (MAX_SECS - 1), 1.25) if total > MAX_SECS else 1.0
    final_dur = total / speed
    print(f"Total {total:.1f}s, speed x{speed:.2f}, final {final_dur:.1f}s", flush=True)

    srt, t0, idx = [], 0.0, 1
    for text, speech, dur in spans:
        parts = chunks(text)
        tot = sum(len(p) for p in parts) or 1
        cur = t0
        for p in parts:
            span = speech * len(p) / tot
            srt.append(f"{idx}\n{ts(cur / speed)} --> {ts((cur + span) / speed)}\n{p}\n")
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

    sub = (f"subtitles={WORK}/subs.srt:force_style='FontName=DejaVu Sans,Bold=1,FontSize=14,Alignment=2,"
           "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,MarginV=80'")
    vchain = (f"setpts=PTS/{speed:.4f}," if speed > 1.001 else "") + sub + ",format=yuv420p"
    achain = f"atempo={speed:.4f}" if speed > 1.001 else "anull"
    has_music = os.path.exists(MUSIC)
    if has_music:
        fc = (f"[0:v]{vchain}[v];[0:a]{achain}[a0];[1:a]volume=0.08[m];"
              "[a0][m]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        fc = f"[0:v]{vchain}[v];[0:a]{achain}[a]"

    vk = max(150, int(TARGET_BYTES * 8 / final_dur / 1000) - AUDIO_K)
    for attempt in range(3):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", f"{WORK}/joined.mp4"]
        if has_music:
            cmd += ["-stream_loop", "-1", "-i", MUSIC]
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{vk}k", "-maxrate", f"{vk}k",
                "-bufsize", f"{2 * vk}k", "-c:a", "aac", "-b:a", f"{AUDIO_K}k", "-ac", "1", "-ar", "44100",
                "-t", f"{final_dur + 0.1:.2f}", "-movflags", "+faststart", f"{OUT}/final.mp4"]
        run(cmd)
        size = os.path.getsize(f"{OUT}/final.mp4")
        print(f"final.mp4: {size / 1e6:.2f} MB at {vk} kbps video", flush=True)
        if size <= 4_700_000:
            break
        vk = int(vk * 0.8)
    print("DONE", flush=True)


def notify():
    url = os.environ.get("MAKE_WEBHOOK_URL", "").strip()
    if not url:
        print("No MAKE_WEBHOOK_URL secret set, skipping.")
        return
    meta = json.load(open(f"{OUT}/meta.json", encoding="utf-8"))
    base = f"https://github.com/{os.environ['REPO']}/releases/download/{os.environ['TAG']}"
    payload = {**meta, "tags_csv": ",".join(meta["tags"]), "video_url": f"{base}/final.mp4",
               "script_url": f"{base}/script.json"}
    r = requests.post(url, json=payload, timeout=60)
    print("Make answered", r.status_code, r.text[:200])
    r.raise_for_status()


if __name__ == "__main__":
    notify() if len(sys.argv) > 1 and sys.argv[1] == "notify" else main()
