# Presentation Extensions

Companion avatar rendering and speech output belong to the presentation layer.
They should subscribe to normalized run events and must not become dependencies
of the Agent runtime or workflow executor.

The current trace protocol already provides lifecycle events such as
`workflow_started`, `node_started`, `llm_completed`, `tool_completed`,
`workflow_completed`, and `workflow_failed`. A future web event stream can add
presentation events with stable payloads:

| Event | Payload | Consumer |
| --- | --- | --- |
| `assistant_started` | `run_id` | Avatar state |
| `assistant_chunk` | `run_id`, `text`, `sequence` | Streaming text and speech queue |
| `speech_started` | `run_id`, `utterance_id` | Avatar mouth animation |
| `speech_finished` | `run_id`, `utterance_id` | Avatar idle state |
| `assistant_finished` | `run_id` | Avatar idle state |

The chat page polls the active run's cumulative draft while the model streams.
When a Qwen3-TTS node is connected to reply voice output, it sends completed
sentences from that draft to TTS and plays the returned PCM chunks through one
AudioWorklet queue. The final audio is retained in browser memory for replay.
Dedicated `assistant_chunk` and speech lifecycle events remain a future trace
contract; the current UI consumes the existing draft field.

## Theme Extensions

The web shell exposes `registerTheme(id, definition)` from `web/src/theme.jsx`.
Definitions provide `label`, `canvas`, `panel`, `accent`, and `line` colors.
Theme CSS variables are `--canvas`, `--panel`, `--green`, `--line`, and
`--theme-image`; a plugin can add theme presets without changing the chat or
workflow components.
