# HomeCritters — Home Assistant integration

Home Assistant integration for **[HomeCritters](https://github.com/HomeCritters/homecritters-firmware)**:
a desk pet + smart speaker (a pixel-art ferret) running on a Spotpear/Xiaozhi
"Ball V2" (ESP32-S3, round touch display).

It talks to the device over the WebSocket the firmware already exposes on the
LAN — no cloud, `local_push`.

## Features

- **Sensors** — hunger, energy, joy, hygiene, battery, mood, current screen
- **Buttons** — feed, pet, bath
- **Switches** — sleep, idle clock
- **Numbers** — LED brightness, screen brightness
- **Media player** — HTTP audio playback on the critter's speaker (FLAC /
  MP3 / WAV): TTS announcements (the device shows an Alexa-style voice
  ring), HA media sources, Music Assistant tracks (the device throws a
  disco party 🪩), and AirPlay via Music Assistant's AirPlay receiver

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

## License

MIT
