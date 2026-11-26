#!/opt/video/bin/python
import os; os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
"""Mahra video editing toolkit. Run `mahra-edit <command> -h` for help."""
import argparse, json, os, subprocess, sys, shutil, tempfile, math
from pathlib import Path

MODELS = Path('/opt/video-models')
REMOTION = Path('/opt/remotion-studio')
BRANDS = MODELS / 'brands'
def load_brand(name):
    d = BRANDS / name
    if not (d / 'brand.json').exists():
        sys.exit(f"marca '{name}' não existe. Disponíveis: {', '.join(x.name for x in BRANDS.iterdir())}")
    b = json.loads((d / 'brand.json').read_text()); b['dir'] = d
    return b

def run(cmd, **kw):
    print('+', ' '.join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), check=True, **kw)

def probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', str(path)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    v = next((s for s in d['streams'] if s['codec_type'] == 'video'), None)
    info = {'duration': float(d['format']['duration']), 'has_audio': any(s['codec_type'] == 'audio' for s in d['streams'])}
    if v:
        w, h = int(v['width']), int(v['height'])
        rot = 0
        for sd in v.get('side_data_list', []):
            rot = int(sd.get('rotation', 0) or 0)
        if abs(rot) == 90: w, h = h, w
        num, den = map(int, v['r_frame_rate'].split('/'))
        info.update(width=w, height=h, fps=num / den)
    return info

# ---------------- audio ----------------
def cmd_clean_audio(a):
    """Isolate the voice with Demucs, then denoise/EQ/loudness-normalise and put it back on the video."""
    tmp = Path(tempfile.mkdtemp())
    wav = tmp / 'a.wav'
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', a.input, '-vn', '-ac', '2', '-ar', '44100', wav])
    voice = wav
    if not a.no_demucs:
        run([sys.executable, '-m', 'demucs', '--two-stems', 'vocals', '-n', 'htdemucs', '-d', 'cpu', '-o', tmp, wav])
        voice = tmp / 'htdemucs' / 'a' / 'vocals.wav'
    filt = 'highpass=f=80,afftdn=nf=-25,acompressor=threshold=-20dB:ratio=3:attack=5:release=80,loudnorm=I=-14:TP=-1.5:LRA=9'
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', a.input, '-i', voice, '-map', '0:v?', '-map', '1:a',
         '-af', filt, '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', a.output])

# ---------------- transcription ----------------
def cmd_transcribe(a):
    os.environ.setdefault('PYANNOTE_METRICS_ENABLED', '0')
    import re, whisperx, whisperx.alignment as wal
    class _Splitter:  # offline sentence splitter (replaces NLTK punkt download)
        def span_tokenize(self, text):
            for m in re.finditer(r'\S.*?(?:[.!?…]+(?=\s|$)|$)', text, flags=re.S):
                yield m.span()
    wal.nltk_load = lambda *_a, **_k: _Splitter()
    if a.vocab is None: a.vocab = load_brand(a.brand).get('vocab') or None
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    audio = whisperx.load_audio(a.input)
    model = whisperx.load_model(a.model, 'cpu', compute_type='int8', language=a.lang,
                                download_root=str(MODELS / 'whisper'),
                                asr_options={'initial_prompt': a.vocab} if a.vocab else None)
    res = model.transcribe(audio, batch_size=8, language=a.lang)
    am, meta = whisperx.load_align_model(language_code=a.lang, device='cpu')
    res = whisperx.align(res['segments'], am, meta, audio, 'cpu', return_char_alignments=False)
    words = []
    for seg in res['segments']:
        for w in seg.get('words', []):
            if 'start' in w and 'end' in w:
                words.append({'text': w['word'].strip(), 'start': round(w['start'], 3), 'end': round(w['end'], 3)})
            elif words:  # unaligned token (numbers etc.) -> attach to previous
                words[-1]['text'] += ' ' + w['word'].strip()
    (out / 'words.json').write_text(json.dumps(words, ensure_ascii=False, indent=1))
    def ts(t):
        h, r = divmod(t, 3600); m, s = divmod(r, 60)
        return f"{int(h):02}:{int(m):02}:{int(s):02},{int((s % 1) * 1000):03}"
    srt = []
    for i, seg in enumerate(res['segments'], 1):
        srt.append(f"{i}\n{ts(seg['start'])} --> {ts(seg['end'])}\n{seg['text'].strip()}\n")
    (out / 'legendas.srt').write_text('\n'.join(srt))
    (out / 'transcricao.txt').write_text('\n'.join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in res['segments']))
    print(f"{len(words)} palavras -> {out}/words.json, legendas.srt, transcricao.txt")

# ---------------- cutting ----------------
FILLERS = {'é...', 'éh', 'ãh', 'ah', 'hum', 'hmm', 'uhm', 'eh', 'tipo,', 'né,'}

def cmd_cut(a):
    """Remove silences (and optional filler words / explicit ranges) using word timestamps."""
    words = json.loads(Path(a.words).read_text())
    info = probe(a.input)
    drop = []
    for r in (a.remove or []):
        s, e = map(float, r.split('-')); drop.append((s, e))
    keep_words = []
    for w in words:  # alignment often stretches the last word of a phrase into the silence after it
        w = dict(w); w['end'] = min(w['end'], w['start'] + 0.09 * len(w['text']) + 0.35)
        if a.fillers and w['text'].lower().strip('.,!?') in {f.strip('.,') for f in FILLERS}:
            continue
        if any(w['start'] >= s and w['end'] <= e for s, e in drop):
            continue
        keep_words.append(w)
    segs = []
    for w in keep_words:
        s, e = max(0, w['start'] - a.pad), min(info['duration'], w['end'] + a.pad)
        if segs and s - segs[-1][1] <= a.gap:
            segs[-1][1] = max(segs[-1][1], e)
        else:
            segs.append([s, e])
    if not segs:
        sys.exit('nada para manter')
    # build filter
    parts, labels = [], ''
    for i, (s, e) in enumerate(segs):
        parts.append(f"[0:v]trim={s:.3f}:{e:.3f},setpts=PTS-STARTPTS[v{i}];[0:a]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,afade=t=out:st={max(0, e - s - 0.01):.3f}:d=0.01[a{i}]")
        labels += f"[v{i}][a{i}]"
    fc = ';'.join(parts) + f";{labels}concat=n={len(segs)}:v=1:a=1[v][a]"
    fcf = Path(tempfile.mktemp(suffix='.txt')); fcf.write_text(fc)
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', a.input, '-filter_complex_script', fcf, '-map', '[v]', '-map', '[a]',
         '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', a.output])
    # remap word times
    new, offset = [], 0.0
    for s, e in segs:
        for w in keep_words:
            if w['start'] >= s - 1e-6 and w['end'] <= e + 1e-6:
                new.append({'text': w['text'], 'start': round(w['start'] - s + offset, 3), 'end': round(w['end'] - s + offset, 3)})
        offset += e - s
    wout = Path(a.output).with_suffix('.words.json')
    wout.write_text(json.dumps(new, ensure_ascii=False, indent=1))
    print(f"{info['duration']:.1f}s -> {offset:.1f}s ({len(segs)} trechos). Palavras: {wout}")

def cmd_scenes(a):
    from scenedetect import detect, ContentDetector
    scenes = detect(a.input, ContentDetector(threshold=a.threshold))
    res = [{'start': round(s.get_seconds(), 3), 'end': round(e.get_seconds(), 3)} for s, e in scenes]
    print(json.dumps(res, indent=1))
    if a.out: Path(a.out).write_text(json.dumps(res, indent=1))

# ---------------- reframe (YuNet / MediaPipe) ----------------
def cmd_reframe(a):
    import cv2, numpy as np
    info = probe(a.input)
    W, H = info['width'], info['height']
    rw, rh = map(int, a.ratio.split(':'))
    cw = min(W, int(round(H * rw / rh / 2) * 2)); ch = min(H, int(round(cw * rh / rw / 2) * 2))
    cap = cv2.VideoCapture(a.input)
    det = cv2.FaceDetectorYN.create(str(MODELS / 'yunet/face_detection_yunet_2023mar.onnx'), '', (320, 320), 0.7)
    xs, ys, n, step = [], [], 0, max(1, int(info['fps'] / 6))
    last = (W / 2, H / 2)
    while True:
        ok = cap.grab()
        if not ok: break
        if n % step == 0:
            _, f = cap.retrieve()
            sc = 640 / max(f.shape[:2]); small = cv2.resize(f, None, fx=sc, fy=sc)
            det.setInputSize((small.shape[1], small.shape[0]))
            _, faces = det.detect(small)
            if faces is not None and len(faces):
                fbest = max(faces, key=lambda r: r[2] * r[3])
                last = ((fbest[0] + fbest[2] / 2) / sc, (fbest[1] + fbest[3] / 2) / sc)
        xs.append(last[0]); ys.append(last[1]); n += 1
    cap.release()
    xs = np.array(xs, float)
    # smooth: hold camera still unless subject moves out of a dead-zone, then ease
    k = max(1, int(info['fps'] * a.smooth))
    xs = np.convolve(np.pad(xs, (k, k), mode='edge'), np.ones(2 * k + 1) / (2 * k + 1), mode='valid')
    cam, out = xs[0], []
    for x in xs:
        if abs(x - cam) > cw * 0.08: cam += (x - cam) * 0.08
        out.append(int(np.clip(cam - cw / 2, 0, W - cw)))
    cap = cv2.VideoCapture(a.input)
    ow, oh = a.width, int(a.width * rh / rw)
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{ow}x{oh}',
                           '-r', str(info['fps']), '-i', '-', '-i', a.input, '-map', '0:v', '-map', '1:a?',
                           '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-shortest', a.output],
                          stdin=subprocess.PIPE)
    y0 = (H - ch) // 2
    for x in out:
        ok, f = cap.read()
        if not ok: break
        crop = f[y0:y0 + ch, x:x + cw]
        ff.stdin.write(cv2.resize(crop, (ow, oh), interpolation=cv2.INTER_LANCZOS4).tobytes())
    ff.stdin.close(); ff.wait()
    print('ok', a.output)

# ---------------- BEN2 background removal ----------------
def load_ben2():
    sys.path.insert(0, str(MODELS / 'ben2-src'))
    import torch, BEN2
    from huggingface_hub import hf_hub_download
    m = BEN2.BEN_Base().eval()
    m.loadcheckpoints(hf_hub_download('PramaLLC/BEN2', 'BEN2_Base.pth', cache_dir=str(MODELS / 'hf')))
    return m

def cmd_cutout(a):
    """Cut the subject out of a video/image (BEN2). Video -> WebM with alpha (for text-behind-person)."""
    from PIL import Image
    import cv2, numpy as np, torch
    torch.set_num_threads(os.cpu_count())
    m = load_ben2()
    if a.input.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        img = Image.open(a.input).convert('RGB')
        m.inference(img).save(a.output); print('ok', a.output); return
    info = probe(a.input)
    cap = cv2.VideoCapture(a.input)
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f"{info['width']}x{info['height']}",
                           '-r', str(info['fps']), '-i', '-', '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-b:v', '0', '-crf', '30', '-row-mt', '1', a.output],
                          stdin=subprocess.PIPE)
    i = 0
    while True:
        ok, f = cap.read()
        if not ok: break
        rgba = m.inference(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)))
        ff.stdin.write(np.asarray(rgba.convert('RGBA')).tobytes()); i += 1
        if i % 30 == 0: print(f'{i} frames', flush=True)
    ff.stdin.close(); ff.wait(); print('ok', a.output)

# ---------------- Depth Anything ----------------
def cmd_depth(a):
    """Depth map (Depth Anything V2). Image -> PNG. Video -> grayscale depth video. --blur makes a fake 'cinema lens' background blur."""
    from transformers import pipeline
    from PIL import Image
    import cv2, numpy as np
    pipe = pipeline('depth-estimation', model='depth-anything/Depth-Anything-V2-Small-hf', device='cpu')
    def proc(img_bgr):
        d = np.array(pipe(Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)))['depth'], dtype=np.float32)
        d = cv2.resize(d, (img_bgr.shape[1], img_bgr.shape[0])); d = (d - d.min()) / (np.ptp(d) + 1e-6)
        if not a.blur: return cv2.cvtColor((d * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
        bl = cv2.GaussianBlur(img_bgr, (0, 0), a.blur)
        m = np.clip((d - 0.35) / 0.3, 0, 1)[..., None]  # near = sharp
        return (img_bgr * m + bl * (1 - m)).astype(np.uint8)
    if a.input.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        cv2.imwrite(a.output, proc(cv2.imread(a.input))); print('ok', a.output); return
    info = probe(a.input); cap = cv2.VideoCapture(a.input)
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f"{info['width']}x{info['height']}",
                           '-r', str(info['fps']), '-i', '-', '-i', a.input, '-map', '0:v', '-map', '1:a?', '-c:a', 'copy',
                           '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-shortest', a.output], stdin=subprocess.PIPE)
    while True:
        ok, f = cap.read()
        if not ok: break
        ff.stdin.write(proc(f).tobytes())
    ff.stdin.close(); ff.wait(); print('ok', a.output)

# ---------------- CLAP music matching ----------------
def cmd_music(a):
    """Rank music files in a folder by how well they match a text description (CLAP)."""
    from transformers import ClapModel, ClapProcessor
    import librosa, torch
    m = ClapModel.from_pretrained('laion/clap-htsat-unfused').eval(); p = ClapProcessor.from_pretrained('laion/clap-htsat-unfused')
    files = [f for f in sorted(Path(a.folder).iterdir()) if f.suffix.lower() in ('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac')]
    with torch.no_grad():
        t = m.get_text_features(**p(text=[a.prompt], return_tensors='pt', padding=True))
        t = t / t.norm(dim=-1, keepdim=True)
        res = []
        for f in files:
            y, _ = librosa.load(f, sr=48000, mono=True, offset=a.offset, duration=30)
            au = m.get_audio_features(**p(audios=[y], sampling_rate=48000, return_tensors='pt'))
            au = au / au.norm(dim=-1, keepdim=True)
            res.append((float((t @ au.T)[0, 0]), f.name))
    for s, n in sorted(res, reverse=True): print(f'{s:.3f}  {n}')

def cmd_mix(a):
    """Add background music under the voice, with automatic ducking."""
    d = probe(a.video)['duration']
    fc = (f"[1:a]volume={a.music_db}dB,afade=t=in:d=0.8,afade=t=out:st={max(0, d - 1.5):.2f}:d=1.5[m];"
          f"[0:a]asplit[v1][v2];[m][v2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[md];"
          f"[v1][md]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', a.video, '-stream_loop', '-1', '-i', a.music, '-filter_complex', fc,
         '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', f'{d:.3f}', a.output])

# ---------------- Remotion render ----------------
def cmd_render(a):
    """Render captions / titles / CTA over the video with Remotion (brand style)."""
    info = probe(a.video)
    b = load_brand(a.brand)
    style = a.style or b['style']
    cta = b['cta'] if a.cta is None else a.cta
    logo = a.logo or (str(b['dir'] / b['logo']) if b.get('logo') and not a.no_logo else None)
    pub = REMOTION / 'public'; pub.mkdir(exist_ok=True)
    for f in pub.iterdir():
        if f.is_file(): f.unlink()
    shutil.copy(a.video, pub / 'input.mp4')
    props = {
        'video': 'input.mp4', 'words': json.loads(Path(a.words).read_text()) if a.words else [],
        'titles': json.loads(Path(a.titles).read_text()) if a.titles else [],
        'durationSec': info['duration'], 'fps': round(info['fps']), 'width': info['width'], 'height': info['height'],
        'style': style, 'cta': cta or '', 'ctaSec': a.cta_sec if cta else 0,
        'fontTitle': b['fontTitle'], 'fontCaption': b['fontCaption'],
        'maxWordsPerLine': a.words_per_line, 'captionY': a.caption_y, 'colors': b['colors'],
    }
    if logo: shutil.copy(logo, pub / ('logo' + Path(logo).suffix)); props['logo'] = 'logo' + Path(logo).suffix
    if a.fg: shutil.copy(a.fg, pub / 'fg.webm'); props['fgVideo'] = 'fg.webm'
    pf = Path(tempfile.mktemp(suffix='.json')); pf.write_text(json.dumps(props, ensure_ascii=False))
    out = Path(a.output).resolve()
    if a.still is not None:
        run(['npx', 'remotion', 'still', 'src/index.ts', 'Reel', out, f'--frame={a.still}', f'--props={pf}'], cwd=REMOTION)
    else:
        run(['npx', 'remotion', 'render', 'src/index.ts', 'Reel', out, f'--props={pf}', '--codec=h264', '--crf=18',
             f'--concurrency={os.cpu_count()}', '--audio-codec=aac'], cwd=REMOTION)

# ---------------- export ----------------
PRESETS = {'reels': (1080, 1920), 'tiktok': (1080, 1920), 'shorts': (1080, 1920), 'youtube': (1920, 1080), 'feed': (1080, 1350), 'quadrado': (1080, 1080)}
def cmd_export(a):
    w, h = PRESETS[a.preset]
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=30,format=yuv420p"
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', a.input, '-vf', vf, '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'slow',
         '-crf', '19', '-maxrate', '12M', '-bufsize', '24M', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
         '-af', 'loudnorm=I=-14:TP=-1.5', '-movflags', '+faststart', a.output])

def cmd_info(a): print(json.dumps(probe(a.input), indent=1))

def main():
    ap = argparse.ArgumentParser(prog='mahra-edit'); sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('info'); p.add_argument('input'); p.set_defaults(f=cmd_info)
    p = sp.add_parser('clean-audio'); p.add_argument('input'); p.add_argument('output'); p.add_argument('--no-demucs', action='store_true'); p.set_defaults(f=cmd_clean_audio)
    p = sp.add_parser('transcribe'); p.add_argument('input'); p.add_argument('--out', default='transcricao'); p.add_argument('--model', default='large-v3-turbo'); p.add_argument('--lang', default='pt')
    p.add_argument('--brand', default='mahra'); p.add_argument('--vocab', help='palavras/nomes que o Whisper deve reconhecer (padrão: o da marca)'); p.set_defaults(f=cmd_transcribe)
    p = sp.add_parser('cut'); p.add_argument('input'); p.add_argument('words'); p.add_argument('output')
    p.add_argument('--gap', type=float, default=0.35, help='silêncio máximo mantido entre palavras (s)'); p.add_argument('--pad', type=float, default=0.08)
    p.add_argument('--fillers', action='store_true'); p.add_argument('--remove', nargs='*', help='trechos a remover, ex: 12.5-18.2'); p.set_defaults(f=cmd_cut)
    p = sp.add_parser('scenes'); p.add_argument('input'); p.add_argument('--threshold', type=float, default=27); p.add_argument('--out'); p.set_defaults(f=cmd_scenes)
    p = sp.add_parser('reframe'); p.add_argument('input'); p.add_argument('output'); p.add_argument('--ratio', default='9:16'); p.add_argument('--width', type=int, default=1080); p.add_argument('--smooth', type=float, default=0.5); p.set_defaults(f=cmd_reframe)
    p = sp.add_parser('cutout'); p.add_argument('input'); p.add_argument('output'); p.set_defaults(f=cmd_cutout)
    p = sp.add_parser('depth'); p.add_argument('input'); p.add_argument('output'); p.add_argument('--blur', type=float, default=0); p.set_defaults(f=cmd_depth)
    p = sp.add_parser('music'); p.add_argument('folder'); p.add_argument('prompt'); p.add_argument('--offset', type=float, default=15); p.set_defaults(f=cmd_music)
    p = sp.add_parser('mix'); p.add_argument('video'); p.add_argument('music'); p.add_argument('output'); p.add_argument('--music-db', type=float, default=-18); p.set_defaults(f=cmd_mix)
    p = sp.add_parser('render'); p.add_argument('video'); p.add_argument('output'); p.add_argument('--words'); p.add_argument('--titles')
    p.add_argument('--brand', default='mahra'); p.add_argument('--no-logo', action='store_true')
    p.add_argument('--style', choices=['elegante', 'tiktok']); p.add_argument('--cta', help='texto final ("" = sem tela final)'); p.add_argument('--cta-sec', type=float, default=2.5)
    p.add_argument('--logo'); p.add_argument('--fg'); p.add_argument('--words-per-line', type=int, default=4); p.add_argument('--caption-y', type=float, default=0.72)
    p.add_argument('--still', type=int); p.set_defaults(f=cmd_render)
    p = sp.add_parser('export'); p.add_argument('input'); p.add_argument('output'); p.add_argument('--preset', choices=list(PRESETS), default='reels'); p.set_defaults(f=cmd_export)
    a = ap.parse_args(); a.f(a)

if __name__ == '__main__': main()
