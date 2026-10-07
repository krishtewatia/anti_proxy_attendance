# Capturing the Liveness Evaluation Set

This is the set used to measure the liveness gate and pick its threshold (ADR-011). It takes about 30 minutes.

**Rules**
- Your own face only, in every sample: live, printed, on the phone and in the video.
- Everything is saved under your fixtures folder, outside the repository. Never copy it into the repo.
- Use the same camera you use for attendance.

## What you need
1. **A printed photo of your face.** A4, colour if possible, your face roughly life-size, looking at the camera. A plain selfie printed on ordinary paper is the realistic attack.
2. **A phone showing a photo of your face**, full screen, brightness at maximum, auto-rotate and auto-lock off.
3. **A laptop (or tablet) playing a video of you**, 10 to 15 seconds, full screen, in which you look at the camera and turn your head slightly. Set it to loop.

## Set up (once)
1. Create the folder: `<your fixtures folder>/liveness` (for example `C:\Users\hp\Downloads\anti_proxy_fixtures\liveness`).
2. From the project root, start the capture page:
   ```bash
   python -m http.server 8765 --directory vision-service/tools
   ```
3. Open `http://localhost:8765/liveness_capture.html` in Chrome or Edge and allow the camera.
4. Click **Choose the liveness folder** and pick the folder from step 1. Allow the browser to save to it.
5. Pick the attendance camera in the **Camera** list.

The page records frames exactly as the teacher page sends them (640x480, JPEG quality 0.8) at 3 per second, and writes them to `liveness/<category>/attempt_NN/`. Nothing is uploaded.

## What to record
One **attempt** is one click of **Record one attempt**: a 3-second countdown, then 8 seconds of recording. Between attempts, change something (distance, angle, lighting), so the attempts are not copies of each other.

| Category | Attempts | What is in front of the camera |
|---|---|---|
| `live` | 10 | You, in person |
| `print` | 8 | The printed photo |
| `phone_screen` | 8 | The phone showing your photo |
| `laptop_replay` | 8 | The laptop playing your video |

For **every** category, split the attempts like this:

| Attempts | Lighting | Distance from the camera |
|---|---|---|
| First half | Normal room light, lit from the front | Half at about 40 cm, half at about 80 cm |
| Second half | Different light: near a window in daylight, or only a ceiling light | Half at about 40 cm, half at about 80 cm |

### Live (10 attempts)
Sit as a student would when being marked. Look at the camera; move naturally. Include two attempts with glasses on if you wear them, and one with your head turned slightly away.

### Attacks (8 attempts each)
Try to **succeed**: hold the photo or screen so that it looks as much like a real face to the camera as you can.
- Fill the same part of the frame your real face did.
- Hold it steady for a few seconds, then tilt and move it slowly, as someone would if it was not being accepted.
- In about half of the attempts keep the edges of the paper or the screen **out of view**; in the rest let them show.
- For screens, try to avoid reflections in some attempts and leave them in others.

Keep your real face out of the picture during attack attempts: hold the photo or screen in front of you, or stand aside.

## Check and run
1. The table at the bottom of the page should read 10 / 8 / 8 / 8.
2. Stop the capture page (Ctrl+C in its terminal).
3. Run the measurement:
   ```bash
   cd vision-service
   VISION_FIXTURES_DIR=/path/to/fixtures python evaluation/liveness_eval.py
   ```
   It prints, per threshold, how many spoof attempts were accepted and how many live frames and attempts were rejected, and recommends a threshold. Send the output; it contains scores and counts only.

## If something goes wrong
- **"Camera not available"**: another app or browser tab is using the camera, or permission was denied. Close the other app and reload.
- **"This browser cannot write to a folder"**: use Chrome or Edge on a computer.
- **A bad attempt** (wrong category, you walked into an attack shot): delete that `attempt_NN` folder and record it again.
- **Many frames with "no face detected"** in the report: the face was too small or too far to one side. Re-record those attempts closer to the camera.
