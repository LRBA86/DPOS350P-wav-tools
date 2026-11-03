# 4-phase interleave offset in saved waveforms

Saved waveforms at slow timebases show a pattern with period 4 samples. Samples `i % 4 = 0..3` each
carry their own constant offset. In the spectrum this is a spur at fs/4 (1.188 kHz at 500 ms/div
with 4.75 kS/s), which matches user reports of FFT spurs.

## Measured offsets (px; 1 px = 1/63 div)

| Files | Mode | Offsets, phase 0..3 | Significance |
|---|---|---|---|
| 1–15 | 2 ch, 200–500 ms/div | ≈ −1.0, +0.1, +0.85, 0.0 (both channels, every file) | 5–25 σ |
| 22–23 | 1 ch, 500 ms – 2 s/div | ≈ +0.17, +0.73, −0.7, −0.2 | > 5 σ |
| 16–21 | 1 ch, 5 ms/div | < 0.06 | negligible |
| 24–26 | 2 ch, 2 s/div, broadband audio | not significant | — |

≈ 1 px is 1.6 % of a division, for example 0.16 V at 10 V/div. Whether the pattern comes from the
ADC cores or from the FPGA decimation path is not known. The firmware has no per-phase correction:
the system calibration only searches a per-channel offset.

## Estimation without being fooled by the signal

A plain per-phase mean is dominated by the signal itself on broadband captures. The decoder instead
uses the second difference

```
r[i] = x[i] - (x[i-1] + x[i+1]) / 2
```

which removes slow content. For a period-4 pattern `o_k`, the mean of `r` on phase k is
`o_k - (o_{k-1} + o_{k+1})/2`; in a 4-point DFT that multiplies harmonic m by `1 - cos(pi*m/2)`,
which is invertible for m = 1, 2, 3 (m = 0 is DC, not an offset). Clipped samples are excluded.

The correction is applied only when the spread is ≥ 0.3 px **and** ≥ 5 standard errors.
Unit tests inject a known pattern and recover it, and check that pure noise is left untouched.

A firmware-side fix would add the 4 per-phase offsets to the existing calibration.
