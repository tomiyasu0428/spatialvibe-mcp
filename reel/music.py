"""Synthesise the reel's music from its scene structure (no samples, no external audio).

120 BPM, 4/4, one scene = 1–3 bars. Each scene type maps to a musical section:
  drop → sparse intro, stamp/split → full groove, overflow → break + glitch,
  stretch → riser + snare roll, swap → impact (the drop), flow → groove + plucks per step,
  final → last chord and tail.
Returns stereo float audio and the list of hits the visuals pulse to.
"""
import wave

import numpy as np

SR = 44100
RNG = np.random.default_rng(7)

CHORDS = [  # Am, F, C, G  (pad voicing, bass root)
    ([220.00, 261.63, 329.63, 440.00], 110.00),
    ([174.61, 220.00, 261.63, 349.23], 87.31),
    ([261.63, 329.63, 392.00, 523.25], 130.81),
    ([196.00, 246.94, 293.66, 392.00], 98.00),
]


def _t(sec):
    return np.arange(int(sec * SR)) / SR


def kick(strength=1.0):
    t = _t(0.45)
    f = 44 + 90 * np.exp(-t * 28)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5)
    click = RNG.standard_normal(len(t)) * np.exp(-t * 500) * 0.25
    return np.tanh(1.6 * (body + click)) * strength


def clap():
    t = _t(0.28)
    n = np.diff(RNG.standard_normal(len(t) + 1))
    env = sum(np.exp(-np.clip(t - d, 0, None) * 220) * (t >= d) for d in (0, 0.011, 0.022)) * 0.5
    env += np.exp(-t * 22) * (t >= 0.022) * 0.6
    return n * env * 0.32


def hat(open_=False):
    t = _t(0.3 if open_ else 0.05)
    n = np.diff(np.diff(RNG.standard_normal(len(t) + 2)))
    return n * np.exp(-t * (14 if open_ else 90)) * 0.07


def saw(freq, sec, harmonics=8, detune=0.0):
    t = _t(sec)
    f = freq * (1 + detune)
    return sum(np.sin(2 * np.pi * k * f * t) / k for k in range(1, harmonics + 1) if k * f < SR / 2)


def bass(freq, sec):
    t = _t(sec)
    s = saw(freq, sec, 6) * 0.55 + np.sin(2 * np.pi * freq / 2 * t) * 0.6
    env = np.minimum(t / 0.004, 1) * np.exp(-t * 5)
    return np.tanh(1.4 * s * env) * 0.42


def pad(freqs, sec, harmonics=7, gain=0.05):
    t = _t(sec)
    s = np.zeros(len(t))
    for f in freqs:
        s += saw(f, sec, harmonics, -0.0018) + saw(f, sec, harmonics, 0.0018)
    env = np.minimum(t / 0.06, 1) * np.minimum((sec - t) / 0.12, 1)
    return s * env * gain


def pluck(freq):
    t = _t(0.6)
    s = np.sin(2 * np.pi * freq * t) + 0.45 * np.sin(4 * np.pi * freq * t) + 0.15 * np.sin(6 * np.pi * freq * t)
    return s * np.exp(-t * 7) * np.minimum(t / 0.002, 1) * 0.22


def riser(sec):
    t = _t(sec)
    ramp = (t / sec) ** 2.2
    noise = np.diff(RNG.standard_normal(len(t) + 1)) * 0.10
    sweep = np.sin(2 * np.pi * np.cumsum(300 * (5 ** (t / sec))) / SR) * 0.10
    return (noise + sweep) * ramp


def impact():
    t = _t(1.8)
    sub = np.sin(2 * np.pi * np.cumsum(38 + 60 * np.exp(-t * 18)) / SR) * np.exp(-t * 2.4)
    crash = np.diff(RNG.standard_normal(len(t) + 1)) * np.exp(-t * 2.8) * 0.16
    out = np.zeros(len(t))
    k = kick(1.3)
    out[:len(k)] += k
    return np.tanh(1.3 * (out + sub * 0.9 + crash))


def render(scenes, bpm=120):
    beat = 60 / bpm
    bar = 4 * beat
    total = sum(s["bars"] for s in scenes) * bar
    n = int(total * SR) + 1
    L, R = np.zeros(n), np.zeros(n)
    pad_bus = np.zeros(n)
    duck = np.ones(n)
    hits = []

    def add(sig, at, gain=1.0, pan=0.0, bus=None):
        i = int(at * SR)
        if i >= n:
            return
        sig = sig[: n - i] * gain
        if bus is not None:
            bus[i:i + len(sig)] += sig
            return
        L[i:i + len(sig)] += sig * min(1, 1 - pan)
        R[i:i + len(sig)] += sig * min(1, 1 + pan)

    def k(at, v=1.0):
        add(kick(v), at)
        hits.append({"t": round(at * 1000), "k": "kick", "v": v})
        i = int(at * SR)
        t = _t(0.3)
        seg = 1 - 0.65 * v * np.exp(-t / 0.11)
        j = min(n, i + len(seg))
        duck[i:j] = np.minimum(duck[i:j], seg[: j - i])

    def c(at, v=1.0):
        add(clap(), at, v)
        hits.append({"t": round(at * 1000), "k": "clap", "v": v})

    bar_i = 0
    for si, s in enumerate(scenes):
        typ = s["type"]
        for b in range(s["bars"]):
            t0 = bar_i * bar
            chord, root = CHORDS[bar_i % 4]
            first, last = si == 0, si == len(scenes) - 1
            full = typ in ("stamp", "split", "flow", "swap") or (typ == "stretch")
            # pads (ducked by the kick → the "heartbeat" pump)
            if not (last and b > 0):
                add(pad(chord, bar, 4 if first or typ == "overflow" else 7, 0.045), t0, bus=pad_bus)
            # drums
            if typ == "drop":
                for q in (0, 2):
                    k(t0 + q * beat, 0.9)
                for e in range(8):
                    add(hat(), t0 + e * beat / 2, 0.6, (-0.3, 0.3)[e % 2])
            elif typ == "overflow":
                for e in range(16):
                    add(hat(), t0 + e * beat / 4, 0.5 + 0.4 * (e % 4 == 0), (-0.4, 0.4)[e % 2])
                c(t0 + 3 * beat, 0.8)
                for j, off in enumerate((3, 3.25, 3.5, 3.625, 3.75, 3.875)):
                    k(t0 + off * beat, 0.45 + 0.08 * j)
            elif full:
                for q in range(4):
                    if typ == "swap" and b == 0 and q == 0:
                        add(impact(), t0)
                        hits.append({"t": round(t0 * 1000), "k": "impact", "v": 1.0})
                        k(t0, 0.0)  # duck only
                    else:
                        k(t0 + q * beat)
                for q in (1, 3):
                    c(t0 + q * beat)
                for e in range(8):
                    add(hat(e % 2 == 1 and typ != "stretch"), t0 + e * beat / 2, 0.8, (-0.35, 0.35)[e % 2])
                for e in range(8):  # bass on eighths, root/octave
                    add(bass(root * (2 if e % 4 == 3 else 1), beat / 2 * 0.92), t0 + e * beat / 2, 1.0)
                if typ == "stretch" and b == s["bars"] - 1:
                    add(riser(bar), t0, 1.0)
                    for j in range(8):
                        c(t0 + 3 * beat + j * beat / 8, 0.35 + 0.08 * j)
                if typ == "flow":  # one pluck per step, a step every two beats
                    notes = [root * 4, root * 5, root * 6, root * 8]
                    for j in range(2):
                        add(pluck(notes[(b * 2 + j) % 4]), t0 + j * 2 * beat, 1.0, (-0.25, 0.25)[j])
                        hits.append({"t": round((t0 + j * 2 * beat) * 1000), "k": "step", "v": 1.0})
            elif typ == "final":
                if b == 0:
                    add(impact(), t0, 0.85)
                    hits.append({"t": round(t0 * 1000), "k": "impact", "v": 1.0})
                    k(t0, 0.0)
                    add(pad(chord, bar * 2, 9, 0.07), t0, bus=pad_bus)
                    k(t0 + 2 * beat, 0.7)
                    for e in range(4):
                        add(hat(), t0 + e * beat, 0.5)
                else:
                    k(t0, 0.55)
                    add(pluck(root * 8), t0, 0.8)
            bar_i += 1

    pad_bus *= duck
    L += pad_bus * 1.02
    R += pad_bus * 0.98
    st = np.stack([L, R], axis=1)
    # gentle fade-out over the final 0.4 s, then master: normalise + soft clip
    fade = np.ones(n)
    m = int(0.4 * SR)
    fade[-m:] = np.linspace(1, 0, m)
    st *= fade[:, None]
    st /= max(1e-9, np.abs(st).max())
    st = np.tanh(st * 1.25) / np.tanh(1.25) * 0.92
    hits.sort(key=lambda h: h["t"])
    return st.astype(np.float32), hits


def write_wav(path, st, sr=SR):
    data = (np.clip(st, -1, 1) * 32767).astype("<i2")
    with wave.open(path if hasattr(path, "write") else str(path), "wb") as w:
        w.setnchannels(st.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


def mono_22k(st):
    m = st.mean(axis=1)
    m = (m[0::2][: len(m[1::2])] + m[1::2]) / 2
    return m[:, None]
