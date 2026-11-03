# Saved waveform file format (`/Waveform/<n>.wav`)

Firmware: 2025-06-19 (`DPOS350P-FNIRSI-2025619.iso`). Addresses are for the EXE loaded at `0x40000000`.

The `.wav` written by **Save wave** is **not** RIFF/WAVE. It is a dump of the firmware's internal
serializer, and **every field is big-endian, including the samples**.

Validated against 26 files saved by a real unit (2-channel and single-channel captures, 5 ms/div to 2 s/div), and
against files produced by running the stock serializer under emulation (Unicorn).

## Firmware routines

| Address | Role |
|---|---|
| `0x40035bc4` | builds `/Waveform/<n>.wav` (number → ASCII + `.wav`) |
| `0x400360f0` | Save wave: serialize, then write |
| `0x400366a0` | load a saved waveform |
| `0x40045714` | **serializer**: builds the file in a RAM buffer at `G+0x360404` (`0x408A526C`) |
| `0x400456f4` | deserializer (same field routines, read mode) |
| `0x4004480c` | 7 × u32 header |
| `0x400448b4` | section A (settings) |
| `0x40045580` | section B (thumbnail) |
| `0x400455e4` | section C (samples) |
| `0x40067450` | `serialize(ptr, size)`: writes/reads one field **big-endian** and advances the stream position (`0x4091f38c`); mode flag at `0x4091f390` |

`G = 0x40544e68` is the global settings struct. Section A is a field-by-field copy of parts of `G`.

## Layout

```
0x00  u32 start_A   (always 0x32)
0x04  u32 size_A
0x08  u32 start_B
0x0C  u32 size_B
0x10  u32 start_C
0x14  u32 size_C
0x18  u32 total     (= file size)
0x1C..0x31  zero
A     settings (table below)
B     u16 W, u16 H, then W*H u16 RGB565  -> screen thumbnail (203 x 138 on real files)
C     u16 samples: N of CH1 (if CH1 enabled), then N of CH2 (if CH2 enabled)
```

Section A contains a variable-length block: the u16 at `0x1a4` (`G+0x5d0`) counts items of 3 × u32
inserted right after offset `0x26a`. All fields below are before that point.

## Key fields (file offset, type, struct field)

| Offset | Type | Field | Meaning |
|---|---|---|---|
| 0x036 | u16 | G+0x008 | graticule width, px (950) |
| 0x038 | u16 | G+0x00a | graticule height, px (503) |
| 0x04a | u16 | G+0x01c | px per horizontal div (95) |
| 0x04c | u16 | G+0x01e | horizontal divs (10) |
| 0x04e | u16 | G+0x020 | px per vertical div (63) |
| 0x050 | u16 | G+0x022 | vertical divs (8) |
| 0x065 | u8 | G+0x03e | CH1 enabled |
| 0x067 | u8 | G+0x040 | CH1 probe (0 = x1, 1 = x10, 2 = x100) |
| 0x068 | u8 | G+0x041 | CH1 V/div index (0 = 20 V … 12 = 2 mV, x1) |
| 0x06d | u64 | G+0x050 | **CH1 V/div in µV, probe included** |
| 0x07d | s32 | G+0x060 | CH1 vertical position (ground level, px from bottom) |
| 0x0a6 | u8 | G+0x102 | CH2 enabled |
| 0x0a8 | u8 | G+0x104 | CH2 probe |
| 0x0a9 | u8 | G+0x105 | CH2 V/div index |
| 0x0ae | u64 | G+0x110 | **CH2 V/div in µV, probe included** |
| 0x0be | s32 | G+0x120 | CH2 vertical position |
| 0x0da | u8 | G+0x1b0 | number of enabled channels |
| 0x0e0 | u32 | G+0x1bc | resolution shift |
| 0x0e4 | u32 | G+0x1c0 | resolution factor (64 = 1 << shift) |
| 0x0fe | u8 | G+0x27a | trigger mode (0 Auto, 1 Single, 2 Normal) |
| 0x0ff | u8 | G+0x27b | trigger edge (0 rising, 1 falling) |
| 0x100 | u8 | G+0x27c | trigger source (0 CH1, 1 CH2) |
| 0x101 | s16 | G+0x27e | trigger level, px from bottom (absolute, same scale as position) |
| 0x11d | u8 | G+0x2aa | zoom active |
| 0x120 | u32 | G+0x2b0 | N samples per channel (23752 with 2 ch, 47504 with 1 ch) |
| 0x17e | s64 | G+0x570 | horizontal offset; ÷ timebase_ps = px from screen centre (+ = right) |
| 0x18f | u8 | G+0x588 | timebase index |
| 0x190 | u64 | G+0x590 | **timebase, ps/div** |
| 0x198 | u8 | G+0x598 | zoom timebase index |
| 0x199 | u64 | G+0x5a0 | zoom timebase, ps/div |
| 0x21e | u8 | G+0x284 | HF suppression (0..3, names not mapped) |

V/div table (`G+0xef0`, filled by `0x4004a550`, probe applied by `0x4004a608`), µV:
20 000 000, 10 000 000, 5 000 000, 2 000 000, 1 000 000, 500 000, 200 000, 100 000, 50 000, 20 000,
10 000, 5 000, 2 000. Unit confirmed by the formatter at `0x4004a884` (÷1e9 "KV", ÷1e6 "V", ÷1e3 "mV").

Timebase table (`G+0xbd0`, filled by `0x4003a680`), ps/div: 1-2-5 sequence from 1 to 5e12.
Index 11 holds 5 000 000 instead of 5 000 (firmware bug; below the usable range).

## Samples are screen coordinates, not ADC codes

Each sample is the trace's vertical screen position in px from the graticule bottom, times the
resolution factor (64). On real files the maximum is always 32192 = 503 × 64 (top of screen) and the
mean of an AC signal sits exactly on the channel position. Conversion (same as the Y cursors,
`0x400317a8`):

```
px  = sample / factor                         (factor at 0x0e4, 64)
V   = (px - position_px) * (vdiv_uV / 1e6) / px_per_div_v
dt  = timebase_ps * 1e-12 * div_h / N
```

Samples equal to 0 or 503 × 64 are clipped.

`dt` is confirmed with audio captures at 5 ms/div: 440.1 Hz, 221 Hz and 130.6 Hz tones decode at
exactly those frequencies.

## Trigger point (t = 0)

```
trigger_V  = (level_px - position_px[source]) * vdiv / px_per_div_v
i_trigger  = N/2 + (G+0x570 / timebase_ps) * N / width_px
t[i]       = (i - i_trigger) * dt
```

- The on-screen trigger marker is drawn at `x = G+0x04 + G+0x570/G+0x590 + width/2`
  (`0x40023ea4`), which gives the unit and sign of the offset.
- On 6 triggered captures (Single/Normal, 5 ms/div) the edge crosses the level within 40 samples of N/2.
- The offset sign is from the firmware only. The real files with a non-zero offset are Auto-mode
  captures that cannot confirm it.

## Section B: screen thumbnail

`u16 W, u16 H` followed by `W*H` RGB565 pixels (big-endian). It is the 203 × 138 preview shown by
the on-device Waveform browser: trace colours, trigger marker, measurement bar and even the
colour-graded persistence view are visible.

## Notes on older community decoders

A Colab script that circulated for these files read the samples as little-endian `<u2`. With the bytes
swapped the trace is uncorrelated with the real signal (r = −0.01 and −0.30 on two test files). About
90 % of the swapped values still land in 1000..60000, so a range filter did not reveal the problem.
It also treated header words 4..6 as start/end offsets (they are start_C, size_C, total) and searched
the header for "Vpp" values, which do not exist as a field.
