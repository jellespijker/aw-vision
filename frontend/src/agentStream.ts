import type { ChatMessage, ToolEvent } from './types'

/**
 * Consume the agent's SSE stream (`/api/query/stream`), surfacing each unified
 * ToolEvent live as it happens (pre-execution call, then the enriched result)
 * and resolving with the final answer + the authoritative event list.
 */
export async function streamAgentQuery(
  apiBase: string,
  prompt: string,
  history: ChatMessage[],
  onToolEvents: (events: ToolEvent[]) => void
): Promise<{ response: string; toolEvents: ToolEvent[] }> {
  const collected: ToolEvent[] = []
  let finalResponse = ''
  let errored = ''

  const resp = await fetch(`${apiBase}/api/query/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, history })
  })
  if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  // Parse the SSE byte stream into `data: {...}` events.
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const evt of events) {
      const line = evt.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      let data: any
      try {
        data = JSON.parse(line.slice(5).trim())
      } catch {
        continue
      }
      if (data.type === 'tool_call') {
        // Pre-execution: show the call immediately while the tool runs.
        collected.push({ tool: data.tool, args: data.args, source: 'builtin', result_preview: '' })
        onToolEvents([...collected])
      } else if (data.type === 'tool_result') {
        const ev = { ...data }
        delete ev.type
        if (collected.length) collected[collected.length - 1] = { ...collected[collected.length - 1], ...ev }
        else collected.push(ev)
        onToolEvents([...collected])
      } else if (data.type === 'final') {
        finalResponse = data.response
        if (Array.isArray(data.tool_events) && data.tool_events.length) {
          collected.splice(0, collected.length, ...data.tool_events)
        }
      } else if (data.type === 'error') {
        errored = data.detail || 'Unknown agent error'
      }
    }
  }

  if (errored) {
    const err: any = new Error(errored)
    err.toolEvents = collected
    throw err
  }
  return { response: finalResponse, toolEvents: collected }
}
