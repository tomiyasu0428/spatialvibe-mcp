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
VIDEO_DUR = 139.25
# (video_start_s, src_start_s, src_end_s, label[, 'fix'])  — 'fix' = assets/narration_fix.wav, else assets/narration.wav
# chapter starts: tractor 0, tease 2.5 (Pi 2.5, holes 5.5), open 11.3 (holes 11.3, handrail 20.3, problems 24.3), process 37.3, how 46.3,
# field 52.8, phone 57.8..92.3, ar 92.3, done 101.3, tools 111.8, export 119.25, close 128.25
CUES = [
        (0.3, 0.00, 2.60, "【録り直し1a】トラクターの柱に、ラズベリーパイ", "fix"),
    (5.9, 3.36, 8.42, "【録り直し1b】この穴に合う部品…作れるでしょうか", "fix"),
    (11.7, 8.35, 10.86, "ここに、ラズベリーパイのマウントを置きたい"),
    (14.4, 11.58, 12.99, "スマホホルダーも作りたい"),
    (16.0, 14.30, 18.28, "現場のオーダーメイド…3Dプリンター"),
    (20.5, 18.30, 22.05, "でも…分からない"),
    (25.1, 22.66, 25.47, "ぴったりの寸法に…難しい"),
    (28.1, 26.04, 27.56, "AIとのやりとりが面倒"),
    (29.8, 28.21, 31.01, "そんな問題を解決する、ぴったりMCP"),
    (32.8, 8.96, 15.18, "【録り直し2】現場の写真と、数か所の寸法から…3Dプリントへ", "fix"),
    # dropped (scene removed): これまでは…合わない / 録り直し3 / 推定は推定と書く / 実行して検査し…
    (39.5, 54.23, 55.29, "人は写真を撮る"),
    (40.8, 55.76, 57.20, "Claudeが形を考える"),
    (42.4, 57.75, 60.20, "MCPの道具が、作って、確かめる"),
    (46.6, 65.17, 66.38, "道具だけではありません"),
    (48.0, 66.83, 68.53, "進め方もClaudeに渡します"),
    (49.8, 70.72, 72.44, "選択肢で2〜4問だけ"),
    (51.7, 73.28, 75.78, "寸法は資料から。自分で見て、直す"),
    (54.5, 76.61, 78.50, "トラクターの中でも、ハウスの中でも"),
    (56.6, 79.00, 80.99, "ここからは、iPhoneの画面そのままです"),
    (58.6, 81.65, 82.97, "写真と一言を送る"),
    (61.5, 83.51, 85.00, "Claudeが選択肢で聞きます"),
    (63.2, 85.47, 89.24, "どんな状態で付けるか。どのくらい外すか。何をつなぐか"),
    (70.5, 90.05, 93.76, "寸法は、測った穴のピッチと、ARのための高さだけ"),
    (74.4, 94.47, 95.67, "形ができたら、プレビュー"),
    (76.5, 96.18, 97.62, "公開すると、ARのリンクが届く"),
    (79.5, 98.28, 100.77, "まだ推定の数字は、推定だと書いてあります"),
    (83.0, 101.36, 104.08, "リンクを開くと、その場で実寸の形が立つ"),
    (92.6, 104.75, 106.59, "そのリンクを、トラクターの中で開く"),
    (94.6, 107.15, 109.19, "ピラーの印の場所に、実寸のモデル"),
    (96.8, 109.87, 113.88, "ARは形と置き場所の目安で、強度や公差は保証しません"),
    (101.6, 119.37, 121.70, "版を重ねて、印刷して、ネジ穴に"),
    (108.8, 122.18, 122.58, "ぴったり"),
    (112.3, 123.54, 125.12, "Claudeが使う道具は6つ"),
    (114.1, 125.60, 128.65, "テンプレートは持たず…書きます"),
    (119.6, 129.29, 132.54, "決まったら…1つのフォルダに"),
    (123.0, 133.11, 134.90, "確認済みと推定は混ぜません"),
    (125.0, 135.52, 137.91, "スライスと印刷は、いつものスライサーで"),
    (128.6, 138.59, 142.77, "このMCPサーバーを入れれば…それができる"),
    (133.0, 143.27, 144.40, "あとは、印刷するだけ"),
    (134.3, 145.17, 147.32, "現場で必要なものを、最小限の手間で"),
    (137.3, 151.70, 152.42, "ぴったり"),
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
quiet = [(86.8, 92.3), (138.3, VIDEO_DUR)]
expr = "+".join([f"0.27*between(t,{a},{b})" for a, b in quiet])
music = (f"[2:a]atrim=0:{VIDEO_DUR},asetpts=PTS-STARTPTS,afade=t=in:d=1,afade=t=out:st={VIDEO_DUR - 4}:d=4,"
         f"volume='0.28+{expr}':eval=frame[m]")
fc = ";".join(parts) + ";" + music + ";" + "".join(mixes) + f"amix=inputs={n}:normalize=0,aresample=48000,volume=1.6[nar];" \
     "[m][nar]amix=inputs=2:normalize=0,alimiter=limit=0.95[a]"
cmd = [FF, "-v", "error", "-y", "-i", VIDEO, "-i", NARR, "-stream_loop", "-1", "-i", MUSIC, "-i", FIX, "-filter_complex", fc,
       "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", OUT]
subprocess.run(cmd, check=True)
print(OUT, n, "cues")
