"""Assist satellite: voice pipeline for the HomeCritters device.

Two modes, both fed by the device's continuous binary mic stream (16 kHz
mono 16-bit PCM over the WS):

- Always-on wake word (Phase 3): while the mic switch is on, we keep a
  persistent pipeline run armed at WAKE_WORD (openWakeWord runs locally on
  this HA). When a run ends (answer spoken, error, no speech) we re-arm.
- Push-to-talk (Phase 2): holding BOOT streams audio + evt:ptt:start/end;
  we cancel any armed wake run and pipe straight into STT.

The spoken reply goes back through the device speaker via "media:play:" and
the pipeline states are mirrored to the device ("voice:listening" etc.) to
drive the on-screen ring. If the assistant's reply asks a follow-up question
(continue_conversation), we reopen the mic straight into STT after the reply
finishes playing - no wake word needed to answer.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.assist_pipeline import (
    PipelineEvent,
    PipelineEventType,
    PipelineStage,
)
from homeassistant.components.assist_satellite import (
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityFeature,
)
from homeassistant.components.media_player import async_process_play_media_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FerretEntity
from .hub import FerretHub

_LOGGER = logging.getLogger(__name__)

# How long to wait for the TTS reply to finish playing on the device before
# re-arming (guards against a missed media state update).
MEDIA_DONE_TIMEOUT = 60


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: FerretHub = entry.runtime_data
    async_add_entities([FerretAssistSatellite(hub)])


class FerretAssistSatellite(FerretEntity, AssistSatelliteEntity):
    """An always-on (wake word) + push-to-talk Assist satellite."""

    _attr_translation_key = "assistant"
    _attr_supported_features = AssistSatelliteEntityFeature(0)

    def __init__(self, hub: FerretHub) -> None:
        super().__init__(hub, "assist")
        self._audio_queue: asyncio.Queue[bytes | None] | None = None
        self._run_task: asyncio.Task | None = None
        self._mode: str | None = None  # "wake" | "stt" (current run)
        self._continue_conversation = False
        self._tts_played = False
        self._media_done: asyncio.Event = asyncio.Event()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._hub.set_event_cb(self._on_device_event)
        if self._hub.available:
            self._arm_wake()

    async def async_will_remove_from_hass(self) -> None:
        self._hub.set_event_cb(None)
        self._hub.set_audio_sink(None)
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
        await super().async_will_remove_from_hass()

    # --- hub state updates (device WS state, incl. media + availability) ---
    @callback
    def _on_update(self) -> None:
        super()._on_update()
        # TTS finished playing on the device -> unblock the re-arm waiter.
        if self._hub.data.get("media") == "idle":
            self._media_done.set()
        # Hub (re)connected or mic switch flipped on: make sure we're armed.
        if (
            self._hub.available
            and self._hub.mic_enabled
            and (self._run_task is None or self._run_task.done())
        ):
            self._arm_wake()
        # Mic switch flipped off: tear the run down.
        if not self._hub.mic_enabled and self._run_task and not self._run_task.done():
            self._run_task.cancel()
            self._send("mic:off")
            self._send("voice:idle")

    def _send(self, cmd: str) -> None:
        """Fire-and-forget a WS command to the device (never raises)."""

        async def _do() -> None:
            try:
                await self._hub.send(cmd)
            except Exception:  # noqa: BLE001 - device offline is normal here
                _LOGGER.debug("send %r failed (device offline?)", cmd)

        self.hass.async_create_task(_do())

    # --- arming / turns ---
    @callback
    def _arm_wake(self) -> None:
        """Start (or restart) the persistent wake word run."""
        if not self._hub.mic_enabled:
            return
        # A live run blocks re-arming - unless WE are that run (re-arm from
        # _after_run happens inside the finishing task, which isn't done yet).
        if (
            self._run_task
            and not self._run_task.done()
            and self._run_task is not asyncio.current_task()
        ):
            return
        self._start_run(PipelineStage.WAKE_WORD)
        self._send("mic:on")

    @callback
    def _start_run(self, stage: PipelineStage) -> None:
        self._mode = "wake" if stage is PipelineStage.WAKE_WORD else "stt"
        self._continue_conversation = False
        self._tts_played = False
        self._audio_queue = asyncio.Queue()
        self._hub.set_audio_sink(self._audio_queue)
        self._run_task = self.hass.async_create_task(self._run_pipeline(stage))

    async def _run_pipeline(self, stage: PipelineStage) -> None:
        # Capture OUR queue: by the time a cancelled run cleans up, a new run
        # may already own the sink - only clear it if it's still ours.
        q = self._audio_queue
        try:
            await self.async_accept_pipeline_from_satellite(
                audio_stream=self._audio_stream(),
                start_stage=stage,
                end_stage=PipelineStage.TTS,
            )
        except Exception:  # noqa: BLE001 - never let a bad turn kill the entity
            _LOGGER.exception("Voice pipeline failed")
            await asyncio.sleep(5)  # don't hot-loop on a persistent error
        finally:
            if q is not None:
                self._hub.clear_audio_sink(q)
        await self._after_run()

    async def _after_run(self) -> None:
        """Wait out TTS playback, then idle + re-arm (or continue listening)."""
        if self._tts_played:
            # The reply is (about to be) playing; wait until the device goes
            # back to media idle so we don't capture our own TTS.
            self._media_done.clear()
            if self._hub.data.get("media") != "play":
                # play command may still be in flight; give it a moment
                await asyncio.sleep(1.5)
            if self._hub.data.get("media") == "play":
                try:
                    async with asyncio.timeout(MEDIA_DONE_TIMEOUT):
                        await self._media_done.wait()
                except TimeoutError:
                    _LOGGER.warning("TTS playback end never seen; re-arming anyway")
        if not (self._hub.available and self._hub.mic_enabled):
            self._send("voice:idle")
            return
        if self._continue_conversation:
            # The assistant asked a follow-up: reopen the mic straight into
            # STT so the user can just answer (no wake word).
            self._send("voice:listening")
            self._start_run(PipelineStage.STT)
        else:
            self._send("voice:idle")
            self._arm_wake()

    async def _audio_stream(self):
        """Yield mic frames until the end-of-speech sentinel (PTT release)."""
        assert self._audio_queue is not None
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                break
            yield chunk

    # --- device -> HA events (push-to-talk) ---
    @callback
    def _on_device_event(self, event: str) -> None:
        if event == "ptt:start":
            # Button beats wake word - AND beats a stale STT turn (the device
            # only emits ptt:start on a fresh press, so whatever run exists is
            # either the armed wake run or a zombie; never block the button).
            if self._run_task and not self._run_task.done():
                self._run_task.cancel()
            self._start_run(PipelineStage.STT)
        elif event == "ptt:end":
            if self._audio_queue is not None and self._mode == "stt":
                self._audio_queue.put_nowait(None)  # end of speech

    # --- pipeline -> us ---
    def on_pipeline_event(self, event: PipelineEvent) -> None:
        if event.type is PipelineEventType.WAKE_WORD_END:
            self._send("voice:listening")
        elif event.type is PipelineEventType.STT_END:
            self._send("voice:thinking")
        elif event.type is PipelineEventType.INTENT_END and event.data:
            output = event.data.get("intent_output") or {}
            self._continue_conversation = bool(output.get("continue_conversation"))
        elif event.type is PipelineEventType.TTS_END and event.data:
            output = event.data.get("tts_output") or {}
            url = output.get("url")
            if url:
                self._tts_played = True
                self._send("voice:speaking")
                self.hass.async_create_task(self._play_media(url))

    async def _play_media(self, url: str) -> None:
        full_url = async_process_play_media_url(self.hass, url)
        await self._hub.send(f"media:play:{full_url}")

    # --- satellite configuration (wake word runs on HA, not on-device) ---
    @callback
    def async_get_configuration(self) -> AssistSatelliteConfiguration:
        return AssistSatelliteConfiguration(
            available_wake_words=[],
            active_wake_words=[],
            max_active_wake_words=0,
        )

    async def async_set_configuration(
        self, config: AssistSatelliteConfiguration
    ) -> None:
        return
