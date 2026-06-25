import { NextRequest, NextResponse } from 'next/server'
import { getAuthUser, createClient } from '@/lib/supabase/server'
import { anthropic, MODEL, assignmentFeedbackPrompt } from '@/lib/anthropic'
import { extractJSON } from '@/lib/utils'

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { id: assignmentId } = await params
  const { response_text } = await req.json()
  const supabase = await createClient()

  const { data: assignment } = await supabase
    .from('assignments')
    .select('prompt, lesson:lessons(module:modules(roadmap:roadmaps(goal, user_id)))')
    .eq('id', assignmentId)
    .single()

  if (!assignment) return NextResponse.json({ error: 'Assignment not found' }, { status: 404 })

  const roadmap = ((assignment.lesson as unknown as { module: { roadmap: { goal: string; user_id: string } } }).module).roadmap
  if (roadmap.user_id !== user.id) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const prompts = assignmentFeedbackPrompt(assignment.prompt, response_text, roadmap.goal)

  const message = await anthropic.messages.create({
    model: MODEL,
    max_tokens: 1024,
    system: prompts.system,
    messages: [{ role: 'user', content: prompts.user }],
  })

  const rawText = (message.content[0] as { type: string; text: string }).text
  let feedback: { feedback: string; score: number; key_takeaways: string[] }

  try {
    feedback = JSON.parse(extractJSON(rawText))
  } catch {
    feedback = { feedback: rawText, score: 75, key_takeaways: [] }
  }

  const { data: submission } = await supabase
    .from('assignment_submissions')
    .upsert({
      user_id: user.id,
      assignment_id: assignmentId,
      response_text,
      ai_feedback: feedback.feedback,
      score: feedback.score,
    }, { onConflict: 'user_id,assignment_id' })
    .select()
    .single()

  return NextResponse.json({ ...feedback, submission_id: submission?.id })
}
