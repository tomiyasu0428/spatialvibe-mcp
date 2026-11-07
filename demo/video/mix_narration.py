"""Place the recorded narration (assets/narration.wav) on the timeline cue by cue, duck the music, mux with clips/joined_silent.mp4.
Cue times were aligned to the real footage with Whisper word timestamps; two sentences are dropped (see comments)."""
import subprocess
from pathlib import Path
HERE = Path(__file__).resolve().parent
import imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()
NARR = str(HERE / "assets" / "narration.wav")      # Google AI Studio (Achernar), local only
VIDEO = str(HERE / "clips" / "joined_silent.mp4")
MUSIC = str(HERE / "assets" / "music.mp3")
FIX = str(HERE / "assets" / "narration_fix.wav")   # the three re-recorded lines, in order
OUT = str(HERE / "demo_narrated.mp4")
VIDEO_DUR = 136.75
# (video_start_s, src_start_s, src_end_s, label[, 'fix'])  — 'fix' = assets/narration_fix.wav, else assets/narration.wav
# chapter starts: tease 0, open 8.8 (holes 8.8, handrail 17.8, problems 21.8), process 34.8, how 43.8, field 50.3,
# phone 55.3..89.8, ar 89.8, done 98.8, tools 109.3, export 116.75, close 125.75
CUES = [
    (0.3, 0.00, 8.42, "【録り直し1】トラクターの柱に…作れるでしょうか", "fix"),
    (9.2, 8.35, 10.86, "ここに、ラズベリーパイのマウントを置きたい"),
    (11.9, 11.58, 12.99, "スマホホルダーも作りたい"),
    (13.5, 14.30, 18.28, "現場のオーダーメイド…3Dプリンター"),
    (18.0, 18.30, 22.05, "でも…分からない"),
    (22.6, 22.66, 25.47, "ぴったりの寸法に…難しい"),
    (25.6, 26.04, 27.56, "AIとのやりとりが面倒"),
    (27.3, 28.21, 31.01, "そんな問題を解決する、ぴったりMCP"),
    (30.3, 8.96, 15.18, "【録り直し2】現場の写真と、数か所の寸法から…3Dプリントへ", "fix"),
    # dropped (scene removed): これまでは…合わない / 録り直し3 / 推定は推定と書く / 実行して検査し…
    (37.0, 54.23, 55.29, "人は写真を撮る"),
    (38.3, 55.76, 57.20, "Claudeが形を考える"),
    (39.9, 57.75, 60.20, "MCPの道具が、作って、確かめる"),
    (44.1, 65.17, 66.38, "道具だけではありません"),
    (45.5, 66.83, 68.53, "進め方もClaudeに渡します"),
    (47.3, 70.72, 72.44, "選択肢で2〜4問だけ"),
    (49.2, 73.28, 75.78, "寸法は資料から。自分で見て、直す"),
    (52.0, 76.61, 78.50, "トラクターの中でも、ハウスの中でも"),
    (54.1, 79.00, 80.99, "ここからは、iPhoneの画面そのままです"),
    (56.1, 81.65, 82.97, "写真と一言を送る"),
    (59.0, 83.51, 85.00, "Claudeが選択肢で聞きます"),
    (60.7, 85.47, 89.24, "どんな状態で付けるか。どのくらい外すか。何をつなぐか"),
    (68.0, 90.05, 93.76, "寸法は、測った穴のピッチと、ARのための高さだけ"),
    (71.9, 94.47, 95.67, "形ができたら、プレビュー"),
    (74.0, 96.18, 97.62, "公開すると、ARのリンクが届く"),
    (77.0, 98.28, 100.77, "まだ推定の数字は、推定だと書いてあります"),
    (80.5, 101.36, 104.08, "リンクを開くと、その場で実寸の形が立つ"),
    (90.1, 104.75, 106.59, "そのリンクを、トラクターの中で開く"),
    (92.1, 107.15, 109.19, "ピラーの印の場所に、実寸のモデル"),
    (94.3, 109.87, 113.88, "ARは形と置き場所の目安で、強度や公差は保証しません"),
    (99.1, 119.37, 121.70, "版を重ねて、印刷して、ネジ穴に"),
    (106.3, 122.18, 122.58, "ぴったり"),
    (109.8, 123.54, 125.12, "Claudeが使う道具は6つ"),
    (111.6, 125.60, 128.65, "テンプレートは持たず…書きます"),
    (117.1, 129.29, 132.54, "決まったら…1つのフォルダに"),
    (120.5, 133.11, 134.90, "確認済みと推定は混ぜません"),
    (122.5, 135.52, 137.91, "スライスと印刷は、いつものスライサーで"),
    (126.1, 138.59, 142.77, "このMCPサーバーを入れれば…それができる"),
    (130.5, 143.27, 144.40, "あとは、印刷するだけ"),
    (131.8, 145.17, 147.32, "現場で必要なものを、最小限の手間で"),
    (134.8, 151.70, 152.42, "ぴったり"),
]
PAD = 0.06
parts, mixes = [], []
for i, cue in enumerate(CUES):
    v, a, b = cue[0], cue[1], cue[2]
    src = "3:a" if len(cue) > 4 and cue[4] == "fix" else "1:a"
    a0, b0 = max(0, a - PAD), b + PAD
    delay = int(round(v * 1000))
    parts.append(f"[{src}]atrim={a0:.3f}:{b0:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.03,afade=t=out:st={b0 - a0 - 0.05:.3f}:d=0.05,"
                 f"adelay={delay}|{delay}[n{i}]")
    mixes.append(f"[n{i}]")
n = len(CUES)
# music: 0.28 under speech, 0.55 in the speech-free stretches (AR footage, tail), fade out at the end
quiet = [(84.3, 89.8), (135.8, VIDEO_DUR)]
expr = "+".join([f"0.27*between(t,{a},{b})" for a, b in quiet])
music = (f"[2:a]atrim=0:{VIDEO_DUR},asetpts=PTS-STARTPTS,afade=t=in:d=1,afade=t=out:st={VIDEO_DUR - 4}:d=4,"
         f"volume='0.28+{expr}':eval=frame[m]")
fc = ";".join(parts) + ";" + music + ";" + "".join(mixes) + f"amix=inputs={n}:normalize=0,aresample=48000,volume=1.6[nar];" \
     "[m][nar]amix=inputs=2:normalize=0,alimiter=limit=0.95[a]"
cmd = [FF, "-v", "error", "-y", "-i", VIDEO, "-i", NARR, "-stream_loop", "-1", "-i", MUSIC, "-i", FIX, "-filter_complex", fc,
       "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", OUT]
subprocess.run(cmd, check=True)
print(OUT, n, "cues")
