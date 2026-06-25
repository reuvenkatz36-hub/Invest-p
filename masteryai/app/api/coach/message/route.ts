import { NextRequest, NextResponse } from 'next/server'
import { getAuthUser, createClient, getUserPlan } from '@/lib/supabase/server'
import { anthropic, MODEL, coachSystemPrompt } from '@/lib/anthropic'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  // Premium gate
  const plan = await getUserPlan(user.id)
  if (plan !== 'premium') {
    return NextResponse.json({ error: 'upgrade_required' }, { status: 403 })
  }

  const { message } = await req.json()
  const supabase = await createClient()

  // Save user message
  await supabase.from('coach_messages').insert({
    user_id: user.id,
    role: 'user',
    content: message,
  })

  // Fetch last 20 messages for context
  const { data: history } = await supabase
    .from('coach_messages')
    .select('role, content')
    .eq('user_id', user.id)
    .order('created_at', { ascending: false })
    .limit(20)

  const messages = (history ?? []).reverse().map(m => ({
    role: m.role as 'user' | 'assistant',
    content: m.content,
  }))

  // Get user context
  const [{ data: roadmap }, { data: streak }, { data: lastQuiz }] = await Promise.all([
    supabase.from('roadmaps').select('goal, experience_level').eq('user_id', user.id).eq('is_active', true).order('created_at', { ascending: false }).limit(1).single(),
    supabase.from('learning_streaks').select('*').eq('user_id', user.id).single(),
    supabase.from('quiz_attempts').select('score').eq('user_id', user.id).order('completed_at', { ascending: false }).limit(1).single(),
  ])

  const systemPrompt = coachSystemPrompt(
    roadmap?.goal ?? 'your goals',
    roadmap?.experience_level ?? 'beginner',
    null,
    streak?.current_streak ?? 0,
    0, 0,
    lastQuiz?.score ?? null
  )

  const stream = anthropic.messages.stream({
    model: MODEL,
    max_tokens: 300,
    system: systemPrompt,
    messages,
  })

  let fullResponse = ''

  const readable = new ReadableStream({
    async start(controller) {
      const encoder = new TextEncoder()
      for await (const chunk of stream) {
        if (chunk.type === 'content_block_delta' && chunk.delta.type === 'text_delta') {
          fullResponse += chunk.delta.text
          controller.enqueue(encoder.encode(chunk.delta.text))
        }
      }
      controller.close()

      // Save assistant response
      await supabase.from('coach_messages').insert({
        user_id: user.id,
        role: 'assistant',
        content: fullResponse,
      })
    },
  })

  return new Response(readable, {
    headers: { 'Content-Type': 'text/plain', 'Transfer-Encoding': 'chunked' },
  })
}
