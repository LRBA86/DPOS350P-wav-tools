# Saved-waveform decoder and measurements

Reads the `.wav` files written by **Save wave** (format: `docs/waveform_file_format.md`) and computes
scope-style measurements.

```
pip install -r requirements.txt
python dpos350p_wav.py 1.wav --dump            # all decoded fields
python dpos350p_wav.py 1.wav --plot --html     # waveform + FFT + measurements + device thumbnail -> 1_onda.html
python dpos350p_wav.py 1.wav --csv             # samples in volts, t = 0 at the trigger point
python dpos350p_wav.py *.wav --resumo all.csv  # one measurement row per file/channel
python dpos350p_wav.py 1.wav --miniatura       # save the on-device thumbnail as PNG
python -m pytest -q                            # tests (real-file tests run if an Ondas/ folder with captures exists)
```

## What it does

- **Volts:** volts with the firmware's own cursor scaling. Samples are screen px × 64.
- **Time:** t = 0 at the trigger point, with the trigger level converted to volts.
- **Interleave correction:** removes the 4-phase interleave offset when it is statistically
  significant (`--bruto` disables it). See `docs/adc_interleave_offset.md`.
- **Measurements:** Vmax/Vmin/Vpp, top/base (histogram when two plateaus exist), mean, RMS / AC RMS,
  crest factor, over/preshoot, clipping %, frequency (zero crossings with hysteresis, and FFT),
  period jitter, duty, pulse widths, 10–90 % rise/fall, THD.
- **Channel pair:** CH2−CH1 delay (cross-correlation), phase, correlation and gain.
- **Irregular signals:** if the period varies more than 20 %, crossing-based results are suppressed
  and the FFT frequency is reported.

`bode_axis_reference.py` draws the FRA frequency axis as the firmware does and as it should be
(see `docs/fra_bode_axis.md`).

Code comments and CLI option names are in Portuguese (the author's language); the docs are in English.

Validation:
- 26 real captures (structure, known 440/221/130.6 Hz tones, trigger level/position).
- Synthetic signals: duty, rise time, THD, delay/phase, pulse trains, interleave injection.
