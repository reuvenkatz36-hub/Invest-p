import { NextRequest, NextResponse } from 'next/server'
import { getAuthUser, createClient } from '@/lib/supabase/server'

export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { id } = await params
  const supabase = await createClient()

  const { data: lesson, error } = await supabase
    .from('lessons')
    .select(`
      *,
      module:modules (
        title, roadmap_id,
        roadmap:roadmaps ( goal, experience_level, user_id )
      ),
      lesson_progress ( * ),
      quizzes ( id, questions_json ),
      assignments ( * )
    `)
    .eq('id', id)
    .single()

  if (error || !lesson) {
    return NextResponse.json({ error: 'Lesson not found' }, { status: 404 })
  }

  const roadmap = (lesson.module as unknown as { roadmap: { user_id: string } }).roadmap
  if (roadmap.user_id !== user.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  return NextResponse.json(lesson)
}
