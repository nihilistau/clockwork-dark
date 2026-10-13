# Media servers

What makes a phone story's pictures (READ RECEIPTS' photos, videos and
profile portraits) and its people's voice notes, how to point the game at
each, and what has and has not been run against a real server. The model servers that write the words are
[docs/MODEL_SERVERS.md](MODEL_SERVERS.md); hosting the image service for a
group is [docs/HOSTING.md § Phone media](HOSTING.md#phone-media-comfyui-as-a-hosted-service).

## The switch

```yaml
phone_media:
  provider: procedural   # procedural (off: no service) | comfyui | stub
  portraits: on_match    # off | on_match | on_view
  daily_job_cap: 40      # jobs per account per real day; past it, procedural
```

- **`procedural`** (the default): every photo, video and portrait is a tile
  the client draws, with its caption. Nothing is contacted, no job is made.
- **`comfyui`**: a ComfyUI server at `comfyui.base_url` makes them. Phone
  media read only `comfyui`'s CONNECTION keys (`base_url`, `api_key`,
  `auth_header`, the timeouts, `retries`, the size caps, the sampler keys
  and `workflows`) and never `comfyui.enabled`, which is the art pipeline's
  own switch (`scripts/generate_art.py`).
- **`stub`**: the same pipeline against a scripted stand-in --
  `scripts/comfy_stub.py` served on loopback for a hand test (point
  `comfyui.base_url` at its port), or `tests/comfy_stub.py::StubComfy` in
  process in the suite.

`portraits` decides when a person's profile picture is made: `on_match` (the
default: when you match, so swiping costs nothing), `on_view` (whenever their
card is shown: every card a job, until the day's cap) or `off`.

## What the engine asks for

A job is a workflow from `comfyui.workflows` bound with the request's values
(`engine/media/comfy/workflows.py`):

| Workflow | Made for | Template |
|---|---|---|
| `photo` | a photo a person sends; the player's own photo | `config/comfyui/photo_sdxl.json` (SDXL text-to-image, 832x1216) |
| `portrait` | a person's profile picture | the same template, 896x1152 |
| `video` | a video message, a person's or the player's own | `config/comfyui/video_wan.json` (Wan 2.1 text-to-video, 480x832, 49 frames at 16 fps: about 3 s); **unverified until run** |

Voice notes are not images: they are the speech server's ([Voice
notes](#voice-notes-voxtral-tts), below).

The positive prompt (`engine/social/media.py::photo_request`) is, joined by
commas: the person's fixed `appearance` (from `population.yaml`'s tables;
for the player's own photos, the player's creation profile), what the photo
shows (`media.yaml`'s subject `scene`), the caption the model wrote (cut to
200 characters, as written), the time of day and the person's status
(`evening, out`), and the story's `style`. There is no negative prompt, and
nothing reads, filters or rewrites the prompt or the image (AGENTS.md rule
12): the template's negative node is bound to nothing and stays as exported
(empty in the shipped one). The seed is fixed per medium (and per person for
portraits), so a resubmitted job is the same request.

### The video workflow

`video_wan.json` is written against ComfyUI's native video nodes
(`UNETLoader`, `CLIPLoader` with type `wan`, `VAELoader`,
`ModelSamplingSD3`, `EmptyHunyuanLatentVideo`, `KSampler`, `VAEDecode`,
`SaveWEBM`, and for the poster `ImageFromBatch` and `SaveImage`) and Wan 2.1's text-to-video 1.3B model:
`wan2.1_t2v_1.3B_fp16.safetensors` (diffusion_models),
`umt5_xxl_fp8_e4m3fn_scaled.safetensors` (text_encoders) and
`wan_2.1_vae.safetensors` (vae). The engine binds `positive`, `seed`,
`width`, `height`, `frames` (the latent's `length`; Wan takes 4n+1) and
`filename_prefix`; the sampler (30 steps, cfg 6, `uni_pc`, `simple`) is the
template's own, not the `comfyui.steps`/`cfg_scale` keys the image
workflows bind. Its negative encode is bound to nothing and stays empty, as
the photo template's does.

```yaml
comfyui:
  workflows:
    video:
      template: "config/comfyui/video_wan.json"
      bindings:
        positive: ["5", "text"]
        seed: ["8", "seed"]
        width: ["7", "width"]
        height: ["7", "height"]
        frames: ["7", "length"]
        filename_prefix: ["10", "filename_prefix"]
      output: {node: "10", kind: video, poster_node: "12"}
      size: {width: 480, height: 832, frames: 49}
```

The clip is typed by its magic bytes (WEBM or MP4); anything else fails the
job (`bad_type`) and the person's video is its tile. **The poster** is the
clip's first frame: `ImageFromBatch` (node 11) takes frame 0 of the decoded
batch and `SaveImage` (node 12) saves it, and `output.poster_node: "12"`
names that node, so the worker takes the first image file it lists under
`images` and stores it beside the clip as `<mid>-<digest>_poster.<ext>`.
`SaveWEBM` lists the clip itself under `images` too; the worker never
fetches it as a poster. With no `poster_node`, the poster is the output
node's first `images` file that is not the clip and is named as an image
(`.png`, `.jpg`, `.webp`), chosen before anything is downloaded; with none,
the procedural tile. A `poster_node` not in the template refuses to load. A
video job is heavier than a photo: `comfyui.job_timeout_seconds` (600 s)
bounds it.

### Using your own workflow

Export your graph from ComfyUI with **Save (API Format)**, point
`comfyui.workflows.photo.template` (or `portrait`) at it, and map each value
the engine fills to `[node id, input name]` in your graph:

```yaml
comfyui:
  workflows:
    photo:
      template: "config/comfyui/my_photo.json"
      bindings:
        checkpoint: ["1", "ckpt_name"]
        positive: ["2", "text"]
        width: ["4", "width"]
        height: ["4", "height"]
        seed: ["5", "seed"]
        steps: ["5", "steps"]
        cfg_scale: ["5", "cfg"]
        sampler: ["5", "sampler_name"]
        scheduler: ["5", "scheduler"]
        filename_prefix: ["7", "filename_prefix"]
        reference_image: ["12", "image"]     # optional: see below
      output: {node: "7", kind: image}
      size: {width: 832, height: 1216}
```

A binding naming a node or an input your graph does not have refuses to load
(the job fails with a `binding` error naming the key), never a graph sent
with the value silently ignored. Bind `reference_image` to a LoadImage node
(an IP-Adapter or similar chain) and every later photo of a person is sent
their first finished portrait, so they keep one face; the shipped template
binds none.

## A hosted ComfyUI

`comfyui.base_url` may be any `https` URL. A key is read from the gitignored
`comfyui_api_key.txt` or `CLOCKWORK_COMFYUI_API_KEY` (never put it in a
config file) and sent in `comfyui.auth_header` -- `Authorization` sends
`Bearer <key>`, any other header name the key as written. Each HTTP call is
bounded by `comfyui.timeout_seconds`, each attempt by
`comfyui.job_timeout_seconds` (then `/interrupt`, and the job fails), and a
fetched file by `comfyui.max_bytes`. docs/HOSTING.md covers the per-account
cap, storage and serving when several players share one server.

## What happens to a job

Jobs run on one background thread per process, never inside a player's
action: thread media first, then the player's own, then portraits; one at a
time. A finished file is stored under
`<storage root>/media/phone/<owner>/<save id>/<mid>-<digest>.<ext>` (the digest is the request's) and served at
`/api/phone/media/<save id>/<name>` to its owner only. A job that fails --
refused, an execution error past `comfyui.retries`, a timeout, a 401, a file
too big or not an image -- is the procedural tile for good: the person still
sent the photo; it did not load. A job unfinished when the game stops is
submitted again when the run is resumed.

## Voice notes: Voxtral TTS

A person's voice note is decided by the engine exactly as a photo is (the
`voice` budget, `ask {what: voice}`, `offer_voice`); the model writes only
what they say in it -- its transcript, checked as their messages are -- and
the engine cuts it by whole words to `media.yaml` `voice.max_seconds` (15 s)
at 150 words a minute (37 words) and to `tts.max_chars`. Nothing reads or rewrites what it says.

```yaml
tts:
  enabled: false                       # off by default: the transcript tile
  base_url: "http://127.0.0.1:8123"    # the Voxtral tts-server's /speak
  voices:                              # this build's voices, each tagged with a sex
    - {id: neutral_male, sex: male}
    - {id: neutral_female, sex: female}
    - {id: warm_female, sex: female}
    - {id: old_male, sex: male}
  max_bytes: 8388608                   # a larger answer is refused
  job_timeout_seconds: 1800            # a note not started by then is its tile
```

Each person draws one voice of their sex from `tts.voices` (the same list
the Settings panel offers for narration), so a person always sounds the
same. With `tts.enabled` the transcript is spoken in that voice by the
speech worker (one background thread, `engine/media/tts.py`), uncached: the
WAV -- typed by its magic bytes, at most `tts.max_bytes`, at most twice
`voice.max_seconds` long -- is stored with the save's other media
(`<mid>-<digest>.wav`) and served at the same owner-scoped route. With TTS
off, the server down, an answer that is no WAV or too long, a wait past
`tts.job_timeout_seconds`, a person with no voice of their sex, or the
account's `phone_media.daily_job_cap` spent (a voice note is one of the
day's jobs, counted with its images and videos), the note is its
**transcript tile**: a waveform, the estimated duration and the
transcript. The player's own voice notes (push-to-talk, transcribed by
`POST /api/voice/transcribe`) are sent as their transcript; their audio is
never kept.

**Why the transcript tile is the expected path on this machine.** Voxtral
synthesizes here at about 21x slower than realtime (73.9 s of compute for
3.44 s of audio at `euler_steps` 3, on a GPU it shares with the model
server), and serially: a full 15 s note is about five minutes of
synthesis, and several queued notes wait behind each other. Turned on, a
note arrives long after its message; left off (the default), it is the
transcript tile at once. A different TTS server speaking the same `/speak`
route with other voice names needs its own `tts.voices` list -- and since
a person's voice is drawn from that list, changing it can change who
sounds like whom (a docs/GOVERNANCE.md NOT WIRED row).

## Verified

- **Not verified live.** No ComfyUI server was running on the development
  machine during v0.22.0 T17-T19 (T19 probed `comfyui.base_url`,
  `http://localhost:8188`, and found nothing listening; `launcher.py --check`
  listed `comfyui` as not enabled, and nothing answered on its port). Nothing here has been run against a
  real ComfyUI: the `photo` template's node types and inputs are the stock
  SDXL graph the art provider always posted, but no image was generated.
- **Verified against the stub:** every protocol step and failure
  (`tests/test_comfy_jobs.py`), the end-to-end loopback stub in a separate
  process (`tests/test_comfy_stub_e2e.py`), and the phone's whole path -- a
  request decided, the caption written, the job made, stored, handed back
  and served (`tests/test_social_media.py`).
- **The video workflow is unverified until run.** No ComfyUI was listening on
  `comfyui.base_url` (`http://127.0.0.1:8188`) during v0.22.0 T20, so
  `video_wan.json`'s node types and inputs, the model file names and what
  `SaveWEBM` puts in `/history` were written from ComfyUI's native Wan
  example, not run. Verified against the stub: the shipped template loads
  and binds, and runs through the worker to a stored WEBM and its poster,
  including against a native-shaped history (the clip under `images` on
  node 10, the first frame on node 12: one clip download, no warning;
  `tests/test_comfy_jobs.py`), and a person's video goes from the request
  to a served clip and poster (`tests/test_social_media.py`).
- **Voice notes were not run against a live Voxtral server** in v0.22.0 T21
  (`tts.enabled` stays off; nothing was synthesized). Verified against the
  in-process stub (`tests/tts_stub.py::StubTTS`, an `httpx.MockTransport`):
  a person's note spoken in their own voice, stored, handed back and served,
  and the transcript tile for a server that is down, an answer that is no
  WAV or far too long, and a wait past the deadline
  (`tests/test_social_media.py`); the cache-key fix
  (`tests/test_tts_cache_key.py`).
