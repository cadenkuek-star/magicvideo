# Verification on real footage

Automated tests (`pytest`) cover everything that doesn't need a trained model or a real camera file. Each item below needs one short manual run. Record the result and date in the table.

## How to run the first check

Use a test trip with 5–10 short clips:

- one clip per camera (X6 `.insv` + `.lrv` + its Studio export, Osmo Nano, Pocket 4P, phone)
- at least one conversation between the two of you
- one clip where a guide or waiter speaks
- one vertical selfie
- one shaky walk

## Checklist

| # | Check | How | Expected | Result |
|---|---|---|---|---|
| 1 | Camera detection | `magicvideo analyze`, then open `inventory.json` | Nano → `action`, Pocket 4P → `gimbal`, X6 → `360`; correct `capture_start` per camera | |
| 2 | X6 file layout | `inventory.json` entries for the X6 group | `.insv` role `source` with `render_path` = Studio export, `.lrv` role `lrv`; projection of the export `equirect` | |
| 3 | X6 fisheye FOV | only if rendering `.insv` directly (`insta360.allow_unstitched_render`) | seam acceptable at `insta360.fisheye_fov_deg` (default 200) | |
| 4 | Whisper transcripts | `analysis/<clip>/transcript.json` | words with sensible timestamps, in the spoken language(s) | |
| 5 | Voice enrollment | `magicvideo enroll`, listen to the `voice_NNN` folders | two folders are clearly you two; guide or waiter in another folder | |
| 6 | Face enrollment | `faces/review/<trip>/person_NNN` | two folders are clearly you two | |
| 7 | Speaker labels | storyboard: guide-only speech shows as `third_party`, your talk as `conversation` | correct on the test clips | |
| 8 | Jitter thresholds | `analysis/<clip>/quality.json`, jitter p90 of the shaky walk vs. a Pocket clip | shaky ≥ `quality.jitter.medium` (0.006), Pocket < it; otherwise tune `quality.jitter` | |
| 9 | Scene tags | `analysis/<clip>/tags.json` | food, transit and landmark frames tagged sensibly; `frames_sent` matches expectations | |
| 10 | Stabilization look | render and watch the shaky walk | steadier, no wobbling borders | |
| 11 | Vertical selfie in a landscape film | watch | face-centred crop (4K vertical) or still blurred background; nothing moving at the sides | |
| 12 | 360 virtual camera | watch an X6 conversation | camera on the speaker, slow eased moves, horizon level | |
| 13 | Rendered speech check | `magicvideo qc` with Whisper installed | `speech.partner_words_rendered` ≥ 0.90 | |
| 14 | Resolve import | File → Import → Timeline → `output/<Name>_vNNN.otio` | clips link to the original files; V2 cutaways line up | |
