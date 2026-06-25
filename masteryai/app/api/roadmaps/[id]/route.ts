import { NextRequest, NextResponse } from 'next/server'
import { getAuthUser, createClient } from '@/lib/supabase/server'

export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { id } = await params
  const supabase = await createClient()

  const { data: roadmap, error } = await supabase
    .from('roadmaps')
    .select(`
      *,
      modules (
        *,
        lessons (
          id, title, order_index, is_generated,
          lesson_progress!left ( completed_at, started_at )
        )
      )
    `)
    .eq('id', id)
    .eq('user_id', user.id)
    .single()

  if (error || !roadmap) {
    return NextResponse.json({ error: 'Roadmap not found' }, { status: 404 })
  }

  // Sort modules and lessons by order_index
  roadmap.modules = roadmap.modules
    .sort((a: { order_index: number }, b: { order_index: number }) => a.order_index - b.order_index)
    .map((m: { lessons: { order_index: number }[] } & Record<string, unknown>) => ({
      ...m,
      lessons: m.lessons.sort((a: { order_index: number }, b: { order_index: number }) => a.order_index - b.order_index),
    }))

  return NextResponse.json(roadmap)
}
