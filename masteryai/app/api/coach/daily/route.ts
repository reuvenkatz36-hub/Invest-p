import { NextResponse } from 'next/server'
import { getAuthUser, createClient } from '@/lib/supabase/server'
import { anthropic, MODEL, coachSystemPrompt } from '@/lib/anthropic'

export async function GET() {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const supabase = await createClient()

  // Get user context
  const [{ data: roadmap }, { data: streak }, { data: lastQuiz }] = await Promise.all([
    supabase.from('roadmaps').select('goal, experience_level').eq('user_id', user.id).eq('is_active', true).order('created_at', { ascending: false }).limit(1).single(),
    supabase.from('learning_streaks').select('*').eq('user_id', user.id).single(),
    supabase.from('quiz_attempts').select('score').eq('user_id', user.id).order('completed_at', { ascending: false }).limit(1).single(),
  ])

  const systemPrompt = coachSystemPrompt(
    roadmap?.goal ?? 'your learning goals',
    roadmap?.experience_level ?? 'beginner',
    null,
    streak?.current_streak ?? 0,
    0, 0,
    lastQuiz?.score ?? null
  )

  const message = await anthropic.messages.create({
    model: MODEL,
    max_tokens: 200,
    system: systemPrompt,
    messages: [{
      role: 'user',
      content: 'Give me a short, energizing daily motivation message. Be specific to my goal and progress. Max 2 sentences.',
    }],
  })

  const text = (message.content[0] as { type: string; text: string }).text

  return NextResponse.json({ message: text })
}
