import asyncio, json, math, os, re, subprocess, time, urllib.parse
import requests
import edge_tts
 
OUT, WORK = "out", "work"
VOICE = os.environ.get("VOICE", "en-US-GuyNeural")
RATE = os.environ.get("VOICE_RATE", "-5%")
W, H, FPS = 1920, 1080, 25
MUSIC = "music/background.mp3"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
 
os.makedirs(OUT, exist_ok=True)
os.makedirs(WORK, exist_ok=True)
 
 
def run(cmd):
    print(">>", " ".join(cmd)[:300], flush=True)
    subprocess.run(cmd, check=True)
 
 
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
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x16213e:s={W}x{H}", "-frames:v", "1", path])
 
 
def ts(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"
 
 
def chunks(text, max_words=11):
    sentences = re.split(r"(?<=[.!?؟…])\s+", text.strip())
    out = []
    for s in sentences:
        words = s.split()
        for i in range(0, len(words), max_words):
            out.append(" ".join(words[i:i + max_words]))
    return [c for c in out if c]
 
 
def main():
    raw = os.environ["SCRIPT_JSON"].strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
    script = json.loads(raw)
    style = script.get("style_guide", "cinematic illustration, no text")
    scenes = script["scenes"]
 
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
        zoom = ("min(zoom+0.0005,1.12)" if i % 2 else "if(eq(on,1),1.12,max(zoom-0.0005,1.0))")
        vf = (f"scale=2400:-1,zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps={FPS},format=yuv420p")
        run(["ffmpeg", "-y", "-i", img, "-i", aud, "-vf", vf, "-af", "apad", "-t", f"{dur:.2f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", clip])
        clips.append(clip)
 
        parts = chunks(sc["narration"])
        total = sum(len(p) for p in parts) or 1
        cur = t0
        for p in parts:
            span = speech * len(p) / total
            srt.append(f"{idx}\n{ts(cur)} --> {ts(cur + span)}\n{p}\n")
            idx += 1
            cur += span
        t0 += dur
 
    with open(f"{WORK}/subs.srt", "w", encoding="utf-8") as f:
        f.write("\n".join(srt))
    with open(f"{WORK}/list.txt", "w") as f:
        for c in clips:
            f.write(f"file '{os.path.basename(c)}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{WORK}/list.txt",
         "-c", "copy", f"{WORK}/joined.mp4"])
 
    sub = (f"subtitles={WORK}/subs.srt:force_style='FontName=DejaVu Sans,FontSize=16,"
           "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=40'")
    if os.path.exists(MUSIC):
        run(["ffmpeg", "-y", "-i", f"{WORK}/joined.mp4", "-stream_loop", "-1", "-i", MUSIC,
             "-filter_complex",
             f"[0:v]{sub}[v];[1:a]volume=0.08[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", f"{OUT}/final.mp4"])
    else:
        run(["ffmpeg", "-y", "-i", f"{WORK}/joined.mp4", "-vf", sub, "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "23", "-c:a", "copy", "-movflags", "+faststart",
             f"{OUT}/final.mp4"])
 
    # Thumbnail
    th = script.get("thumbnail", {})
    base = f"{WORK}/thumb_base.jpg"
    if not fetch_image(th.get("image_prompt", scenes[0]["image_prompt"]), style, 999, base):
        fallback_image(base)
    words = th.get("overlay_text", script.get("title", "")).upper().split()
    mid = math.ceil(len(words) / 2) if len(words) > 2 else len(words)
    with open(f"{WORK}/thumb.txt", "w", encoding="utf-8") as f:
        f.write(" ".join(words[:mid]) + ("\n" + " ".join(words[mid:]) if words[mid:] else ""))
    run(["ffmpeg", "-y", "-i", base, "-vf",
         f"drawtext=fontfile={FONT}:textfile={WORK}/thumb.txt:fontsize=130:fontcolor=white:"
         "borderw=8:bordercolor=black:line_spacing=10:x=(w-text_w)/2:y=h-text_h-90",
         "-frames:v", "1", "-q:v", "3", f"{OUT}/thumb.jpg"])
    print("DONE", flush=True)
 
 
if __name__ == "__main__":
    main()
 
