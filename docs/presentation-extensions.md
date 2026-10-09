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

The TTS provider should be a replaceable speech module. It consumes text chunks
and emits utterance lifecycle events; the avatar renderer only observes those
events. This keeps model choice, speech synthesis, and avatar appearance
independently replaceable. The current HTTP run endpoint returns a completed
answer, so chunk and speech events are a future streaming contract, not active
runtime behavior yet.

## Theme Extensions

The web shell exposes `registerTheme(id, definition)` from `web/src/theme.jsx`.
Definitions provide `label`, `canvas`, `panel`, `accent`, and `line` colors.
Theme CSS variables are `--canvas`, `--panel`, `--green`, `--line`, and
`--theme-image`; a plugin can add theme presets without changing the chat or
workflow components.
