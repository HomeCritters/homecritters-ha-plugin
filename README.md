# HomeCritters — Home Assistant integration

Home Assistant integration for **HomeCritters**: a desk tamagotchi (a
pixel-art ferret) running on a Spotpear/Xiaozhi "Ball V2" (ESP32-S3, round
touch display).

It talks to the device over the WebSocket the firmware already exposes on the
LAN — no cloud, `local_push`.

## Features

- **Sensors** — hunger, energy, joy, hygiene, battery, mood, current screen
- **Buttons** — feed, pet, bath
- **Switches** — sleep, idle clock
- **Numbers** — LED brightness, screen brightness
- **Media player** — HTTP MP3 playback on the critter's speaker: TTS
  announcements, HA media sources, and Music Assistant (enable the
  *Home Assistant MediaPlayers* provider and set the stream codec to MP3)

Entity names are localized (English + Brazilian Portuguese).

## Install (HACS)

1. HACS → ⋮ → **Custom repositories**
2. Repository: `HomeCritters/homecritters-ha-plugin`, category **Integration**
3. Install **HomeCritters**, then restart Home Assistant
4. The device is auto-discovered via zeroconf (or add it manually with its
   host, e.g. `critter.local`)

## Requirements

- HomeCritters firmware with the `_critter._tcp` mDNS service, the `/info`
  endpoint and the media-streaming commands (device side, kept separately).
- Media URLs must be **http://** (the ESP32 does not do TLS); Home Assistant's
  internal media/TTS URLs already are on the LAN.

## License

MIT
