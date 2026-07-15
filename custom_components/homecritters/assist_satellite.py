"""Assist satellite: voice pipeline for the HomeCritters device.

Phase 2 (push-to-talk): the user holds BOOT on the ball, which streams mic
audio (16 kHz mono 16-bit PCM, as binary WS frames) and pushes "evt:ptt:start"
/ "evt:ptt:end". We feed that audio into an Assist pipeline starting at STT,
and play the spoken reply back through the device speaker via the existing
"media:play:" path. Wake word (Phase 3) will start the pipeline at WAKE_WORD
instead and re-arm on its own.
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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: FerretHub = entry.runtime_data
    async_add_entities([FerretAssistSatellite(hub)])


class FerretAssistSatellite(FerretEntity, AssistSatelliteEntity):
    """A push-to-talk Assist satellite backed by the ball's mic."""

    _attr_translation_key = "assistant"
    # No ANNOUNCE for now: replies are played via the media_player path.
    _attr_supported_features = AssistSatelliteEntityFeature(0)

    def __init__(self, hub: FerretHub) -> None:
        super().__init__(hub, "assist")
        self._audio_queue: asyncio.Queue[bytes | None] | None = None
        self._run_task: asyncio.Task | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._hub.set_event_cb(self._on_device_event)

    async def async_will_remove_from_hass(self) -> None:
        self._hub.set_event_cb(None)
        self._hub.set_audio_sink(None)
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
        await super().async_will_remove_from_hass()

    # --- device -> HA events (runs on the event loop, from the hub task) ---
    @callback
    def _on_device_event(self, event: str) -> None:
        if event == "ptt:start":
            self._start_turn()
        elif event == "ptt:end":
            self._end_turn()

    @callback
    def _start_turn(self) -> None:
        if self._run_task and not self._run_task.done():
            return  # a turn is already running
        _LOGGER.debug("voice turn: starting pipeline")
        self._audio_queue = asyncio.Queue()
        self._hub.set_audio_sink(self._audio_queue)
        self._run_task = self.hass.async_create_task(self._run_pipeline())

    @callback
    def _end_turn(self) -> None:
        if self._audio_queue is not None:
            self._audio_queue.put_nowait(None)  # sentinel: end of speech

    async def _run_pipeline(self) -> None:
        try:
            await self.async_accept_pipeline_from_satellite(
                audio_stream=self._audio_stream(),
                start_stage=PipelineStage.STT,
                end_stage=PipelineStage.TTS,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let a bad turn kill the entity
            _LOGGER.exception("Voice pipeline failed")
        finally:
            self._hub.set_audio_sink(None)

    async def _audio_stream(self):
        """Yield mic frames from the queue until the end-of-speech sentinel."""
        assert self._audio_queue is not None
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:  # ptt:end
                break
            yield chunk

    # --- pipeline -> us ---
    def on_pipeline_event(self, event: PipelineEvent) -> None:
        if event.type is PipelineEventType.TTS_END and event.data:
            output = event.data.get("tts_output") or {}
            url = output.get("url")
            if url:
                self.hass.async_create_task(self._play_media(url))

    async def _play_media(self, url: str) -> None:
        full_url = async_process_play_media_url(self.hass, url)
        await self._hub.send(f"media:play:{full_url}")

    # --- satellite configuration (no on-device wake words in push-to-talk) ---
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
        # Wake word runs on HA (openWakeWord), not on the device.
        return
