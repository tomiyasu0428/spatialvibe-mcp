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
VIDEO_DUR = 164.95
# (video_start_s, src_start_s, src_end_s, label[, 'fix'])  — 'fix' = assets/narration_fix.wav, else assets/narration.wav
# chapter starts: tease 0, boarding 8.8, open 13.3 (holes 13.3, handrail 22.3, problems 26.3), ba 39.3, process 47.3,
# how 62.5, field 70.5, phone 75.5..114.0, ar 114.0, done 123.0, tools 133.5, export 140.95, close 149.95
CUES = [
        (0.3, 0.00, 8.42, "【録り直し1】トラクターの柱に…作れるでしょうか", "fix"),
        (13.7, 8.35, 10.86, "ここに、ラズベリーパイのマウントを置きたい"),
        (16.4, 11.58, 12.99, "スマホホルダーも作りたい"),
        (18.0, 14.30, 18.28, "現場のオーダーメイド…3Dプリンター"),
        (22.5, 18.30, 22.05, "でも…分からない"),
        (27.1, 22.66, 25.47, "ぴったりの寸法に…難しい"),
        (30.1, 26.04, 27.56, "AIとのやりとりが面倒"),
        (31.8, 28.21, 31.01, "そんな問題を解決する、ぴったりMCP"),
        (34.8, 8.96, 15.18, "【録り直し2】現場の写真と、数か所の寸法から…3Dプリントへ", "fix"),
        (41.2, 41.16, 44.50, "これまでは…合わない"),
        (44.7, 15.72, 19.85, "【録り直し3】ぴったりなら、聞かれるのは選択肢と、数か所の寸法だけ", "fix"),
        (49.0, 48.16, 49.60, "推定は推定と書く"),
        (50.6, 50.13, 53.31, "実行して検査し…印刷する"),
    (58.0, 54.23, 55.29, "人は写真を撮る"),
    (59.3, 55.76, 57.20, "Claudeが形を考える"),
    (60.9, 57.75, 60.20, "MCPの道具が、作って、確かめる"),
    (66.8, 65.17, 66.38, "道具だけではありません"),
    (68.2, 66.83, 68.53, "進め方もClaudeに渡します"),
    (70.1, 69.20, 70.25, "まずプリンターを聞く"),
    (71.3, 70.72, 72.44, "選択肢で2〜4問だけ"),
    (73.3, 73.28, 75.78, "寸法は資料から。自分で見て、直す"),
    (76.0, 76.61, 78.50, "トラクターの中でも、ハウスの中でも"),
    (78.1, 79.00, 80.99, "ここからは、iPhoneの画面そのままです"),
    (80.3, 81.65, 82.97, "写真と一言を送る"),
    (83.2, 83.51, 85.00, "Claudeが選択肢で聞きます"),
    (84.9, 85.47, 89.24, "どんな状態で付けるか。どのくらい外すか。何をつなぐか"),
    (92.2, 90.05, 93.76, "寸法は、測った穴のピッチと、ARのための高さだけ"),
    (96.1, 94.47, 95.67, "形ができたら、プレビュー"),
    (98.2, 96.18, 97.62, "公開すると、ARのリンクが届く"),
    (101.2, 98.28, 100.77, "まだ推定の数字は、推定だと書いてあります"),
    (104.7, 101.36, 104.08, "リンクを開くと、その場で実寸の形が立つ"),
    (118.3, 104.75, 106.59, "そのリンクを、トラクターの中で開く"),
    (120.3, 107.15, 109.19, "ピラーの印の場所に、実寸のモデル"),
    (122.5, 109.87, 113.88, "ARは形と置き場所の目安で、強度や公差は保証しません"),
    # dropped: 114.65-118.82 「使う素材を変えたので…」(不要)
    (127.6, 119.37, 121.70, "版を重ねて、印刷して、ネジ穴に"),
    (135.0, 122.18, 122.58, "ぴったり"),
    (138.0, 123.54, 125.12, "Claudeが使う道具は6つ"),
    (139.8, 125.60, 128.65, "テンプレートは持たず…書きます"),
    (145.3, 129.29, 132.54, "決まったら…1つのフォルダに"),
    (148.7, 133.11, 134.90, "確認済みと推定は混ぜません"),
    (150.7, 135.52, 137.91, "スライスと印刷は、いつものスライサーで"),
    (154.3, 138.59, 142.77, "このMCPサーバーを入れれば…それができる"),
    (158.7, 143.27, 144.40, "あとは、印刷するだけ"),
    (160.0, 145.17, 147.32, "現場で必要なものを、最小限の手間で"),
    (163.0, 151.70, 152.42, "ぴったり"),
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
quiet = [(8.8, 13.3), (108.5, 118.0), (164.0, VIDEO_DUR)]
expr = "+".join([f"0.27*between(t,{a},{b})" for a, b in quiet])
music = (f"[2:a]atrim=0:{VIDEO_DUR},asetpts=PTS-STARTPTS,afade=t=in:d=1,afade=t=out:st={VIDEO_DUR - 4}:d=4,"
         f"volume='0.28+{expr}':eval=frame[m]")
fc = ";".join(parts) + ";" + music + ";" + "".join(mixes) + f"amix=inputs={n}:normalize=0,aresample=48000,volume=1.6[nar];" \
     "[m][nar]amix=inputs=2:normalize=0,alimiter=limit=0.95[a]"
cmd = [FF, "-v", "error", "-y", "-i", VIDEO, "-i", NARR, "-stream_loop", "-1", "-i", MUSIC, "-i", FIX, "-filter_complex", fc,
       "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", OUT]
subprocess.run(cmd, check=True)
print(OUT, n, "cues")
