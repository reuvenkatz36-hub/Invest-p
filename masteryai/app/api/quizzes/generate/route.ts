import { NextRequest, NextResponse } from 'next/server'
import { getAuthUser, createClient } from '@/lib/supabase/server'
import { anthropic, MODEL, quizPrompt } from '@/lib/anthropic'
import { QuizQuestion, LessonSection } from '@/lib/types'
import { extractJSON } from '@/lib/utils'

export async function POST(req: NextRequest) {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { lesson_id } = await req.json()
  const supabase = await createClient()

  // Check if quiz already exists
  const { data: existing } = await supabase
    .from('quizzes')
    .select('*')
    .eq('lesson_id', lesson_id)
    .single()

  if (existing) return NextResponse.json(existing)

  const { data: lesson } = await supabase
    .from('lessons')
    .select('title, content_json, module:modules(roadmap:roadmaps(user_id))')
    .eq('id', lesson_id)
    .single()

  if (!lesson) return NextResponse.json({ error: 'Lesson not found' }, { status: 404 })
  const roadmap = (lesson.module as unknown as { roadmap: { user_id: string } }).roadmap
  if (roadmap.user_id !== user.id) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const contentText = (lesson.content_json as LessonSection[] | null)
    ?.map(s => `${s.title}\n${s.content}`)
    .join('\n\n') ?? ''

  const prompts = quizPrompt(lesson.title, contentText)

  const message = await anthropic.messages.create({
    model: MODEL,
    max_tokens: 2048,
    system: prompts.system,
    messages: [{ role: 'user', content: prompts.user }],
  })

  const rawText = (message.content[0] as { type: string; text: string }).text
  let questions: QuizQuestion[]

  try {
    questions = JSON.parse(extractJSON(rawText))
  } catch {
    return NextResponse.json({ error: 'Failed to parse quiz' }, { status: 500 })
  }

  const { data: quiz } = await supabase
    .from('quizzes')
    .insert({ lesson_id, questions_json: questions })
    .select()
    .single()

  return NextResponse.json(quiz)
}
