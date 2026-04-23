# COMP2211 Batch Outputs

These files are sample batch ASR outputs generated on an `RTX 5090` with the
`scripts/process_input_output.sh throughput` workflow.

Included results:

- `16_GMT20260327-004652_Recording.cutfile.20260327155952203_2880x1920.srt`
- `16_GMT20260327-004652_Recording.cutfile.20260327155952203_2880x1920.txt`
- `17_GMT20260330-052220_Recording.cutfile.20260330141605757_2880x1920.srt`
- `17_GMT20260330-052220_Recording.cutfile.20260330141605757_2880x1920.txt`
- `6_GMT20260220-004030_Recording.cutfile.20260220135712947_2880x1920.srt`
- `6_GMT20260220-004030_Recording.cutfile.20260220135712947_2880x1920.txt`
- `1_GMT20260202-052523_Recording.cutfile.20260202133752063_2880x1920.srt`
- `1_GMT20260202-052523_Recording.cutfile.20260202133752063_2880x1920.txt`

Notes:

- `16`, `17`, and `6` are healthy source videos and produced near-complete subtitle coverage.
- `1` is included as a partial result because the source MP4 contains AAC corruption near the later portion of the lecture, so the subtitle output ends early.
