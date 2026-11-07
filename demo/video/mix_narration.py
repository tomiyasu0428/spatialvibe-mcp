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
OUT = str(HERE / "demo_narrated.mp4")
VIDEO_DUR = 163.5
# (video_start_s, narration_start_s, narration_end_s, label)
CUES = [
    # dropped: 0.00-5.63 「この部品を、写真から作る話です」(冒頭を問いに変えたため。差し替えの録音があれば assets/narration_open.wav)
    (6.3, 6.76, 7.61, "トラクターに乗る"),
    (8.3, 8.35, 10.86, "ここに、ラズベリーパイのマウントを置きたい"),
    (11.0, 11.58, 12.99, "スマホホルダーも作りたい"),
    (13.1, 14.30, 18.28, "現場のオーダーメイド…3Dプリンター"),
    (17.1, 18.30, 22.05, "でも…分からない"),
    (21.6, 22.66, 25.47, "ぴったりの寸法に…難しい"),
    (24.6, 26.04, 27.56, "AIとのやりとりが面倒"),
    (26.3, 28.21, 31.01, "そんな問題を解決する、ぴったりMCP"),
    # dropped: 31.85-35.55 「現場の写真から…3Dプリントへ」(「写真と数か所の寸法から」に言い換えるため、録り直し待ち)
    # dropped: 36.24-40.15 「写真を送り、質問に答え、プレビューを見て、印刷する」(画面のチップで見せる)
    (33.5, 41.16, 44.50, "これまでは…合わない"),
    # dropped: 45.22-47.54 「聞かれるのは選択肢だけ」(寸法も測るので不正確。録り直し待ち)
    (39.5, 48.16, 49.60, "推定は推定と書く"),
    (41.1, 50.13, 53.31, "実行して検査し…印刷する"),
    (45.2, 54.23, 55.29, "人は写真を撮る"),
    (46.5, 55.76, 57.20, "Claudeが形を考える"),
    (48.1, 57.75, 60.20, "MCPの道具が、作って、確かめる"),
    (55.5, 60.96, 64.24, "写真から3Dプリントまで、この流れで進みます"),
    (62.8, 65.17, 66.38, "道具だけではありません"),
    (64.2, 66.83, 68.53, "進め方もClaudeに渡します"),
    (66.1, 69.20, 70.25, "まずプリンターを聞く"),
    (67.4, 70.72, 72.44, "選択肢で2〜4問だけ"),
    (69.3, 73.28, 75.78, "寸法は資料から。自分で見て、直す"),
    (72.0, 76.61, 78.50, "トラクターの中でも、ハウスの中でも"),
    (74.1, 79.00, 80.99, "ここからは、iPhoneの画面そのままです"),
    (76.3, 81.65, 82.97, "写真と一言を送る"),
    (79.2, 83.51, 85.00, "Claudeが選択肢で聞きます"),
    (80.9, 85.47, 89.24, "どんな状態で付けるか。どのくらい外すか。何をつなぐか"),
    (88.2, 90.05, 93.76, "寸法は、測った穴のピッチと、ARのための高さだけ"),
    (92.1, 94.47, 95.67, "形ができたら、プレビュー"),
    (94.2, 96.18, 97.62, "公開すると、ARのリンクが届く"),
    (97.2, 98.28, 100.77, "まだ推定の数字は、推定だと書いてあります"),
    (100.7, 101.36, 104.08, "リンクを開くと、その場で実寸の形が立つ"),
    (114.3, 104.75, 106.59, "そのリンクを、トラクターの中で開く"),
    (116.3, 107.15, 109.19, "ピラーの印の場所に、実寸のモデル"),
    (118.5, 109.87, 113.88, "ARは形と置き場所の目安で、強度や公差は保証しません"),
    (123.3, 114.65, 118.82, "使う素材を変えたので…ネジ穴へ"),
    (127.7, 119.37, 121.70, "版を重ねて、印刷して、ネジ穴に"),
    (131.0, 122.18, 122.58, "ぴったり"),
    (134.5, 123.54, 125.12, "Claudeが使う道具は6つ"),
    (136.3, 125.60, 128.65, "テンプレートは持たず…書きます"),
    (143.8, 129.29, 132.54, "決まったら…1つのフォルダに"),
    (147.2, 133.11, 134.90, "確認済みと推定は混ぜません"),
    (149.2, 135.52, 137.91, "スライスと印刷は、いつものスライサーで"),
    (152.8, 138.59, 142.77, "このMCPサーバーを入れれば…それができる"),
    (157.2, 143.27, 144.40, "あとは、印刷するだけ"),
    (158.5, 145.17, 147.32, "現場で必要なものを、最小限の手間で"),
    # dropped: 148.03-151.19 「現場の写真から、ぴったりの部品を3Dプリントへ」(締めの画面に同じ一文)
    (161.4, 151.70, 152.42, "ぴったり"),
]
PAD = 0.06
parts, mixes = [], []
for i, (v, a, b, _) in enumerate(CUES):
    a0, b0 = max(0, a - PAD), b + PAD
    delay = int(round(v * 1000))
    parts.append(f"[1:a]atrim={a0:.3f}:{b0:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.03,afade=t=out:st={b0 - a0 - 0.05:.3f}:d=0.05,"
                 f"adelay={delay}|{delay}[n{i}]")
    mixes.append(f"[n{i}]")
n = len(CUES)
# music: 0.28 under speech, 0.55 in the speech-free stretches (AR footage, tail), fade out at the end
quiet = [(104.3, 114.0), (162.6, VIDEO_DUR)]
expr = "+".join([f"0.27*between(t,{a},{b})" for a, b in quiet])
music = (f"[2:a]atrim=0:{VIDEO_DUR},asetpts=PTS-STARTPTS,afade=t=in:d=1,afade=t=out:st={VIDEO_DUR - 4}:d=4,"
         f"volume='0.28+{expr}':eval=frame[m]")
fc = ";".join(parts) + ";" + music + ";" + "".join(mixes) + f"amix=inputs={n}:normalize=0,aresample=48000,volume=1.6[nar];" \
     "[m][nar]amix=inputs=2:normalize=0,alimiter=limit=0.95[a]"
cmd = [FF, "-v", "error", "-y", "-i", VIDEO, "-i", NARR, "-stream_loop", "-1", "-i", MUSIC, "-filter_complex", fc,
       "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", OUT]
subprocess.run(cmd, check=True)
print(OUT, n, "cues")
