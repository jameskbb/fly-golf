#!/usr/bin/env python3
"""Synthesize the short's music bed and crowd cheer. Pure standard library, deterministic.

Writes 48 kHz 16-bit stereo WAVs next to the other effects:
  audio/music.wav  25.0 s funky bed, arranged to this exact cut (see SECTIONS below)
  audio/cheer.wav   2.3 s golf-gallery clap for the putt that drops at 21.2 s
  audio/ooh.wav     1.1 s gallery groan for the 4-footer that slides by at 16.45 s

Nothing here is sampled: every sound is an oscillator or filtered noise, like tools/make-sfx.sh.
The bed is written at a low level on purpose; edl.json sets the final mix with gain_db.

Usage: python3 tools/make-music.py
"""
import math
import struct
import wave
from pathlib import Path

SR = 48000
OUT = Path(__file__).resolve().parent.parent / "audio"

# ---------------------------------------------------------------- deterministic noise
class Rng:
    """Tiny LCG, so every render of the track is bit-identical."""

    def __init__(self, seed=1):
        self.s = seed & 0xFFFFFFFF

    def f(self):  # uniform -1..1
        self.s = (1664525 * self.s + 1013904223) & 0xFFFFFFFF
        return self.s / 2147483648.0 - 1.0


# ---------------------------------------------------------------- tempo / arrangement
BPM = 125.0
BEAT = 60.0 / BPM            # 0.5195 s
STEP = BEAT / 4              # one sixteenth
BAR = BEAT * 4               # 1.92 s; at 125 BPM the cuts at 7.2/9.6/17.3/18.7 land on beats
DUR = 25.0
N = int(DUR * SR)

# The cut this bed is written for (edl.json): what plays when.
#   (start, end, kick+snare, hats, bass, stabs, level)
SECTIONS = [
    (0.00,  2.30, True,  True,  True,  False, 0.85),  # hook: groove from frame 1, no fade-in
    (2.30,  4.60, False, False, True,  False, 0.72),  # brain card: drop the drums, keep the pulse
    (4.60,  7.20, False, True,  True,  False, 0.70),  # back on the tee
    (7.20,  9.58, True,  True,  True,  False, 0.85),  # club reveal -> swing, drums back in
    (9.58, 15.80, True,  True,  True,  True,  1.00),  # full groove: carries the ball flight
    (15.80, 18.62, False, True,  True,  False, 0.78),  # the putts: pull back for the tension
    (18.62, 19.80, False, False, False, False, 0.00),  # LIP-OUT: dead silence for the boom gag
    (19.80, 21.20, False, True,  True,  False, 0.45),  # sneaking back in under the tap-in
    (21.20, 25.00, True,  True,  True,  True,  1.00),  # it drops: everything back, biggest section
]


def section_at(t):
    for s in SECTIONS:
        if s[0] <= t < s[1]:
            return s
    return SECTIONS[-1]


# ---------------------------------------------------------------- voices
buf = [0.0] * N


def add(i0, samples, gain=1.0):
    for k, v in enumerate(samples):
        i = i0 + k
        if 0 <= i < N:
            buf[i] += v * gain


def kick(t, amp=1.0):
    """Sine whose pitch falls 115 -> 45 Hz: the body of the groove."""
    n = int(0.42 * SR)
    ph = 0.0
    out = []
    for k in range(n):
        x = k / SR
        f = 45 + 70 * math.exp(-x * 28)
        ph += 2 * math.pi * f / SR
        env = math.exp(-x * 9) * (1 - math.exp(-x * 900))
        out.append(math.sin(ph) * env)
    add(int(t * SR), out, 0.95 * amp)


def snare(t, rng, amp=1.0):
    """Clap-ish: three noise bursts a few ms apart, band-passed, plus a little tone."""
    n = int(0.30 * SR)
    out = []
    lp = hp = 0.0
    for k in range(n):
        x = k / SR
        burst = 1.0
        for d in (0.000, 0.011, 0.021):
            if x >= d:
                burst = max(burst, math.exp(-(x - d) * 60))
        v = rng.f() * math.exp(-x * 24) * burst
        hp = 0.90 * (hp + v)
        lp += (hp - lp) * 0.35
        tone = 0.25 * math.sin(2 * math.pi * 190 * x) * math.exp(-x * 30)
        out.append(lp * 0.9 + tone)
    add(int(t * SR), out, 0.55 * amp)


def hat(t, rng, amp=1.0, open_=False):
    n = int((0.18 if open_ else 0.055) * SR)
    out = []
    hp = 0.0
    for k in range(n):
        x = k / SR
        v = rng.f()
        hp = 0.93 * (hp + v)  # high-pass: only the sizzle
        out.append(hp * math.exp(-x * (16 if open_ else 55)))
    add(int(t * SR), out, 0.14 * amp)


def bass(t, dur, f, amp=1.0):
    """Funk bass: saw + square through a plucky low-pass, with a short slide in."""
    n = int(dur * SR)
    out = []
    ph = 0.0
    lp1 = lp2 = 0.0
    for k in range(n):
        x = k / SR
        f_now = f * (1 + 0.06 * math.exp(-x * 60))   # tiny slide onto the note
        ph += f_now / SR
        ph -= math.floor(ph)
        saw = 2 * ph - 1
        sq = 1.0 if ph < 0.5 else -1.0
        env = min(1.0, x * 220) * math.exp(-x * 3.4)
        cut = 0.055 + 0.30 * math.exp(-x * 16)       # filter envelope = the "pluck"
        v = saw * 0.75 + sq * 0.25
        lp1 += (v - lp1) * cut
        lp2 += (lp1 - lp2) * cut
        out.append(lp2 * env)
    add(int(t * SR), out, 0.75 * amp)


def stab(t, freqs, amp=1.0):
    """Short clav-like chord stab (the funky off-beat chirp)."""
    n = int(0.20 * SR)
    out = []
    lp = 0.0
    for k in range(n):
        x = k / SR
        v = 0.0
        for f in freqs:
            p = (f * x) % 1.0
            v += (2 * p - 1) * 0.5 + math.sin(2 * math.pi * f * x) * 0.5
        v /= len(freqs)
        env = math.exp(-x * 26) * min(1.0, x * 900)
        lp += (v - lp) * 0.45
        out.append(lp * env)
    add(int(t * SR), out, 0.26 * amp)


# ---------------------------------------------------------------- the arrangement
NOTE = {  # A minor pentatonic, low
    "A1": 55.00, "C2": 65.41, "D2": 73.42, "E2": 82.41, "G2": 98.00, "A2": 110.00,
}
# Two-bar funk riff as (sixteenth, length in sixteenths, note)
RIFF = [
    (0, 3, "A1"), (4, 1, "A1"), (6, 1, "A2"), (7, 2, "G2"), (10, 2, "E2"), (13, 2, "A1"),
    (16, 3, "A1"), (20, 1, "A1"), (22, 1, "C2"), (23, 2, "D2"), (26, 2, "E2"), (29, 2, "G2"),
]
KICKS = {0, 6, 10, 16, 19, 26}          # over two bars (32 sixteenths)
SNARES = {4, 12, 20, 28}
STABS = {3, 11, 14, 19, 27, 30}
AM7 = [220.0, 261.63, 329.63, 392.00]   # A C E G
D9 = [293.66, 349.23, 440.00, 523.25]   # D F A C

rng = Rng(7)
step = 0
while step * STEP < DUR:
    t = step * STEP
    s16 = step % 32
    sec = section_at(t)
    _, _, drums, hats, has_bass, stabs_on, lvl = sec
    if lvl > 0:
        if hats:
            accent = 1.0 if s16 % 4 == 0 else 0.62
            hat(t, rng, amp=accent * lvl, open_=(s16 % 8 == 6))
        if drums:
            if s16 in KICKS:
                kick(t, amp=lvl)
            if s16 in SNARES:
                snare(t, rng, amp=lvl)
        if has_bass:
            for st, ln, nm in RIFF:
                if st == s16:
                    bass(t, ln * STEP * 0.92, NOTE[nm], amp=lvl)
        if stabs_on and s16 in STABS:
            stab(t, AM7 if s16 < 16 else D9, amp=lvl)
    step += 1

# Final accent on the end card, left ringing.
kick(24.55, amp=1.0)
stab(24.55, AM7, amp=1.3)

# ---------------------------------------------------------------- shape, fade, write
def fade_region(a, b, fade=0.035):
    """Fade the bed out/in around a silent section so nothing clicks."""
    f = int(fade * SR)
    for k in range(f):
        g = k / f
        i = int(a * SR) - f + k
        if 0 <= i < N:
            buf[i] *= 1 - g
        j = int(b * SR) + k
        if 0 <= j < N:
            buf[j] *= g


for s in SECTIONS:
    if s[6] == 0.0:
        fade_region(s[0], s[1])

# Sidechain-style ducks so the club impacts and the caption pop read over the bed.
for t_duck, depth in ((2.28, 0.45), (9.58, 0.45), (13.60, 0.60), (21.20, 0.60)):
    i0 = int(t_duck * SR)
    for k in range(int(0.34 * SR)):
        i = i0 + k
        if 0 <= i < N:
            buf[i] *= depth + (1 - depth) * min(1.0, k / (0.30 * SR))
# gentle fade at the very end
for k in range(int(0.35 * SR)):
    i = N - 1 - k
    buf[i] *= k / (0.35 * SR)


def peak_norm(samples, db):
    pk = max(abs(v) for v in samples) or 1.0
    return [v * (10 ** (db / 20)) / pk for v in samples]


def write(path, mono, width=0.10):
    """Stereo with a touch of width (a short Haas offset on one side)."""
    d = int(width * 0.004 * SR)
    frames = bytearray()
    for i, v in enumerate(mono):
        l = v
        r = mono[i - d] if i - d >= 0 else 0.0
        frames += struct.pack("<hh", int(max(-1, min(1, l)) * 32767), int(max(-1, min(1, r)) * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))
    print(f"  {path.name}  {len(mono)/SR:.2f} s")


write(OUT / "music.wav", peak_norm(buf, -3.0))

# ---------------------------------------------------------------- cheer (applause)
# Applause modelled the way it actually works: ~30 separate people, each clapping at their own
# tempo and slightly out of step, each pair of hands with its own resonance, spread across the
# stereo field at different distances, then all of it fed through a small room reverb so the claps
# bind into one sound instead of reading as separate ticks.

def clap_into(chL, chR, t, amp, f0, panL, panR, decay):
    """One clap: a noise burst through a resonant band-pass (the cavity between cupped hands)."""
    n = int(0.09 * SR)
    i0 = int(t * SR)
    lo = bp = 0.0
    f = 2 * math.sin(math.pi * f0 / SR)        # state-variable filter coefficients
    q = 0.62
    for k in range(n):
        x = k / SR
        drive = crng.f() * math.exp(-x * decay) * (1.0 if k > 2 else 3.0)   # a sharp transient first
        hi = drive - lo - q * bp
        bp += f * hi
        lo += f * bp
        v = (bp * 1.5 + hi * 0.35) * amp
        j = i0 + k
        if 0 <= j < len(chL):
            chL[j] += v * panL
            chR[j] += v * panR
    return

cn = int(2.60 * SR)
L = [0.0] * cn
R = [0.0] * cn
crng = Rng(23)
PEOPLE = 30
for person in range(PEOPLE):
    # Each person: own tempo (3.0-4.6 claps/s), own start, own hands, own seat in the room.
    period = 0.215 + 0.115 * (crng.f() + 1) / 2
    t = 0.02 + 0.30 * (crng.f() + 1) / 2 * (0.4 if person < 6 else 1.0)   # front rows start first
    f0 = 850 + 1500 * (crng.f() + 1) / 2
    near = (crng.f() + 1) / 2                     # 1 = close to the camera, 0 = far back
    pan = crng.f()                                # -1 left .. +1 right
    panL = math.sqrt(max(0.0, (1 - pan) / 2))
    panR = math.sqrt(max(0.0, (1 + pan) / 2))
    level = (0.25 + 0.75 * near ** 2) * (0.8 + 0.4 * (crng.f() + 1) / 2)
    decay = 120 + 90 * (1 - near)                 # distant claps lose their tail into the room
    while t < 2.05:
        # applause decays as people stop, and nobody claps perfectly on their own beat
        fade = math.exp(-max(0.0, t - 0.9) * 1.15)
        clap_into(L, R, t, level * fade * (0.75 + 0.5 * (crng.f() + 1) / 2), f0 * (1 + 0.06 * crng.f()),
                  panL, panR, decay)
        t += period * (1 + 0.16 * crng.f())

# Small room: four combs plus two all-passes per channel (Schroeder), mixed in behind the claps.
def reverb(ch, combs=((1687, 0.76), (1759, 0.74), (1621, 0.78), (1549, 0.72)),
           allpasses=((605, 0.7), (481, 0.7)), wet=0.34):
    acc = [0.0] * len(ch)
    for d, g in combs:
        buf_c = [0.0] * d
        idx = 0
        for i, v in enumerate(ch):
            y = buf_c[idx]
            buf_c[idx] = v + y * g
            acc[i] += y * 0.25
            idx = idx + 1 if idx + 1 < d else 0
    for d, g in allpasses:
        buf_a = [0.0] * d
        idx = 0
        for i in range(len(acc)):
            bufd = buf_a[idx]
            y = -g * acc[i] + bufd
            buf_a[idx] = acc[i] + g * y
            acc[i] = y
            idx = idx + 1 if idx + 1 < d else 0
    lp = 0.0
    for i in range(len(ch)):
        lp += (acc[i] - lp) * 0.42          # the room is darker than the claps
        ch[i] = ch[i] + lp * wet
    return ch

reverb(L)
reverb(R)
for k in range(int(0.7 * SR)):              # tail out before the title card
    g = k / (0.7 * SR)
    L[cn - 1 - k] *= g
    R[cn - 1 - k] *= g

pk = max(max(abs(v) for v in L), max(abs(v) for v in R)) or 1.0
sc = (10 ** (-3.0 / 20)) / pk
frames = bytearray()
for i in range(cn):
    frames += struct.pack("<hh", int(max(-1, min(1, L[i] * sc)) * 32767),
                          int(max(-1, min(1, R[i] * sc)) * 32767))
with wave.open(str(OUT / "cheer.wav"), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(bytes(frames))
print(f"  cheer.wav  {cn/SR:.2f} s  ({PEOPLE} clappers + room)")

# ---------------------------------------------------------------- "ooh" (the putt that slides by)
on = int(1.10 * SR)
ooh = [0.0] * on
orng = Rng(91)
lp1 = lp2 = 0.0
for k in range(on):
    x = k / SR
    v = orng.f()
    lp1 += (v - lp1) * 0.10            # crowd murmur
    lp2 += (lp1 - lp2) * 0.10
    env = min(1.0, x * 6) * math.exp(-max(0.0, x - 0.35) * 3.2)
    # two low vowel formants sliding down: a disappointed "ooooh"
    f1 = 330 * (1 - 0.18 * min(1.0, x / 0.9))
    vowel = 0.5 * math.sin(2 * math.pi * f1 * x) + 0.25 * math.sin(2 * math.pi * f1 * 1.5 * x)
    ooh[k] = (lp2 * 6.0 * 0.6 + vowel * 0.22) * env
for k in range(int(0.30 * SR)):
    ooh[on - 1 - k] *= k / (0.30 * SR)

write(OUT / "ooh.wav", peak_norm(ooh, -3.0))
