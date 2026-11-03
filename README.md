# DPOS350P-wav-tools

Decoder, viewer and measurements for the waveform files saved by the **FNIRSI DPOS350P**
oscilloscope, plus notes on two firmware issues found while decoding them.

Everything refers to the **2025-06-19 firmware** and was checked against 26 captures from a real unit.

## Contents

| Path | What |
|---|---|
| [`docs/waveform_file_format.md`](docs/waveform_file_format.md) | The `.wav` written by *Save wave*: a big-endian dump of the firmware serializer. Covers the header, settings map, samples (screen px × 64), trigger point and screen thumbnail |
| [`docs/fra_bode_axis.md`](docs/fra_bode_axis.md) | Why the FRA/Bode frequency grid is wrong for spans other than 3 decades, with a proposed fix |
| [`docs/adc_interleave_offset.md`](docs/adc_interleave_offset.md) | Period-4 per-phase offset in slow-timebase captures (the fs/4 FFT spur) and how to remove it |
| [`tools/wav/`](tools/wav/) | Python decoder/viewer: volts, t = 0 at trigger, measurements, FFT, HTML plots, CSV, thumbnail PNG, tests |

## Quick start

```
cd tools/wav
pip install -r requirements.txt
python dpos350p_wav.py 1.wav --plot --html   # writes 1_onda.html
python -m pytest -q
```

See [`tools/wav/README.md`](tools/wav/README.md) for all options.

## Related work

- [mkubi/FNIRSI-DPOS350P-Hack](https://github.com/mkubi/FNIRSI-DPOS350P-Hack): hardware, flash map,
  update container and checksum, FEL, FPGA interface
- [mkubi/FNIRSI-DPOS350P-Boot](https://github.com/mkubi/FNIRSI-DPOS350P-Boot): custom boot manager
- [EEVblog thread](https://www.eevblog.com/forum/testgear/fnirsi-dpos350p-reverse-engineering-custom-firmware/)

## Notes

- No FNIRSI binaries and no captures are included. The tests that need real files are skipped unless
  a folder `tools/wav/Ondas/` with `.wav` captures exists.
- These tools only read files. They do not modify the instrument.
- Analysis was done with the help of an AI assistant (Claude, by Anthropic). The results were
  reviewed and checked on real device files.

License: MIT.
