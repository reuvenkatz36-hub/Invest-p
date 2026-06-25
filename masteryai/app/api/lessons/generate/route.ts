import { NextRequest, NextResponse } from 'next/server'
import { getAuthUser, createClient, getUserPlan } from '@/lib/supabase/server'
import { anthropic, MODEL, lessonPrompt } from '@/lib/anthropic'
import { ExperienceLevel, LessonSection } from '@/lib/types'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { lesson_id } = await req.json()
  if (!lesson_id) return NextResponse.json({ error: 'Missing lesson_id' }, { status: 400 })

  const supabase = await createClient()

  // Fetch lesson with context
  const { data: lesson, error: lessonError } = await supabase
    .from('lessons')
    .select(`
      *,
      module:modules (
        title,
        roadmap:roadmaps ( goal, experience_level, user_id )
      )
    `)
    .eq('id', lesson_id)
    .single()

  if (lessonError || !lesson) {
    return NextResponse.json({ error: 'Lesson not found' }, { status: 404 })
  }

  // Verify ownership
  const roadmap = (lesson.module as unknown as { roadmap: { user_id: string; goal: string; experience_level: string } }).roadmap
  if (roadmap.user_id !== user.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  // Free plan gate: only first 3 lessons per module
  const plan = await getUserPlan(user.id)
  if (plan === 'free' && lesson.order_index >= 3) {
    return NextResponse.json({ error: 'upgrade_required', message: 'Free plan includes the first 3 lessons per module. Upgrade to unlock all lessons.' }, { status: 403 })
  }

  // Return cached content if already generated
  if (lesson.is_generated && lesson.content_json) {
    return NextResponse.json({ cached: true, content: lesson.content_json })
  }

  const moduleTitle = (lesson.module as unknown as { title: string }).title
  const prompts = lessonPrompt(moduleTitle, roadmap.goal, roadmap.experience_level as ExperienceLevel, lesson.title)

  // Stream response and parse NDJSON sections
  const stream = anthropic.messages.stream({
    model: MODEL,
    max_tokens: 6000,
    system: prompts.system,
    messages: [{ role: 'user', content: prompts.user }],
  })

  let buffer = ''
  const sections: LessonSection[] = []

  const readable = new ReadableStream({
    async start(controller) {
      const encoder = new TextEncoder()

      for await (const chunk of stream) {
        if (chunk.type === 'content_block_delta' && chunk.delta.type === 'text_delta') {
          const text = chunk.delta.text
          buffer += text

          // Parse complete lines as they arrive
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed) continue
            try {
              const section = JSON.parse(trimmed) as LessonSection
              sections.push(section)
              // Send the section to client
              controller.enqueue(encoder.encode(JSON.stringify(section) + '\n'))
            } catch {
              // Skip malformed lines
            }
          }
        }
      }

      // Handle remaining buffer
      if (buffer.trim()) {
        try {
          const section = JSON.parse(buffer.trim()) as LessonSection
          sections.push(section)
          controller.enqueue(encoder.encode(JSON.stringify(section) + '\n'))
        } catch {}
      }

      // Persist to DB
      if (sections.length > 0) {
        await supabase
          .from('lessons')
          .update({ content_json: sections, is_generated: true })
          .eq('id', lesson_id)

        // Create progress record (started)
        await supabase.from('lesson_progress').upsert({
          user_id: user.id,
          lesson_id,
          started_at: new Date().toISOString(),
        }, { onConflict: 'user_id,lesson_id' })
      }

      controller.close()
    },
  })

  return new Response(readable, {
    headers: {
      'Content-Type': 'application/x-ndjson',
      'Transfer-Encoding': 'chunked',
      'Cache-Control': 'no-cache',
    },
  })
}
