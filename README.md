<p align="center">
  <img src="https://raw.githubusercontent.com/HomeCritters/homecritters-assets/main/logo/banner.png" width="640" alt="HomeCritters"/>
</p>

# HomeCritters — Home Assistant integration

Home Assistant integration for **[HomeCritters](https://github.com/HomeCritters/homecritters-firmware)**:
a desk pet + smart speaker (a pixel-art ferret) running on a Spotpear/Xiaozhi
"Ball V2" (ESP32-S3, round touch display).

It talks to the device over the WebSocket the firmware already exposes on the
LAN — no cloud, `local_push`.

## Features

- **Sensors** — hunger, energy, joy, hygiene, battery, mood, current screen
- **Buttons** — feed, pet, bath
- **Switches** — sleep, **night mode** (screen+LED off, pet asleep — great
  for schedule automations, with configurable sleep/wake sounds),
  **microphone** (privacy mute, mirrors the device's BOOT-tap mute), idle
  clock
- **Numbers / selects / text** — LED & screen brightness, pet name,
  timezone, time/date formats, timeouts — every device setting, organized
  in Controls / Configuration / Diagnostics
- **Media player** — HTTP audio playback on the critter's speaker (FLAC /
  MP3 / WAV): TTS announcements (the device shows an Alexa-style voice
  ring), HA media sources, Music Assistant tracks (the device throws a
  disco party 🪩), and AirPlay via Music Assistant's AirPlay receiver
- **Voice assistant** (`assist_satellite`) — **always-on wake word**: the
  device streams its mic to HA, openWakeWord (local) listens for the wake
  word and the Assist pipeline answers through the speaker. Persistent
  wake runs that re-arm themselves, pipeline states mirrored to the
  device's ring/LED, `continue_conversation` reopens the mic for
  follow-ups, and push-to-talk (hold BOOT) beats the wake word. The
  device's live-mic icon reflects *end-to-end* health (it only lights up
  when the pipeline is really consuming audio).
- **Weather location gift** — the device fetches real weather on its own
  (Open-Meteo, no HA required) and renders a distinct scene for every WMO
  condition: clear / mainly clear / partly cloudy / overcast, fog, drizzle,
  rain and showers by intensity, freezing rain, snow (incl. grains and
  snow showers), thunderstorms with visible lightning + thunder, and hail.
  If the device has no city configured, the hub sends HA's home location
  once — zero-config weather; manual settings are never overwritten.
- **"Casa" panel bridge** — pick entities (Configure dialog, drag to
  order) to show on the device's screen: lights/switches/fans/locks as
  tap-to-toggle tiles, temperature/humidity/illuminance/presence sensors
  read-only. Live updates both ways over the WebSocket.
- **Connections manager** — see paired clients, revoke one or all
  (per-client credentials; challenge-response auth, the token never
  travels on the wire)

Entity names are localized (English + Brazilian Portuguese).

## Install (HACS)

1. HACS → ⋮ → **Custom repositories**
2. Repository: `HomeCritters/homecritters-ha-plugin`, category **Integration**
3. Install **HomeCritters**, then restart Home Assistant
4. The device is auto-discovered via zeroconf (or add it manually with its
   host, e.g. `critter.local`)

## Music Assistant

The device works as a Music Assistant player through the
**Home Assistant MediaPlayers** provider:

1. In Music Assistant → Settings → Player providers, add/enable
   *Home Assistant MediaPlayers* and select the critter's media player.
2. In the player's settings, set the stream codec to **MP3 or FLAC**
   (⚠️ **not ALAC** — the firmware does not decode it). The device streams
   FLAC comfortably.
3. Optional: enable Music Assistant's **AirPlay receiver** provider and
   route it to the critter — your iPhone/Mac can then AirPlay straight to
   the pet.

## Requirements

- [HomeCritters firmware](https://github.com/HomeCritters/homecritters-firmware)
  with the `_critter._tcp` mDNS service, the `/info` endpoint and the
  media-streaming commands.
- Media URLs must be **http://** (the ESP32 does not do TLS); Home Assistant's
  internal media/TTS URLs already are on the LAN.
- For the voice assistant: an Assist pipeline with a **wake word engine**
  (e.g. the openWakeWord add-on), STT and TTS. The satellite uses HA's
  preferred pipeline; tool calling works best with a model that supports
  native tools (and fits your GPU — e.g. `qwen3:8b` on 8 GB via Ollama).

## License

MIT
