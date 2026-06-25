import { NextRequest, NextResponse } from 'next/server'
import { getAuthUser, createClient } from '@/lib/supabase/server'

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { id: lessonId } = await params
  const { time_spent_seconds } = await req.json()
  const supabase = await createClient()

  // Verify lesson exists and user owns it
  const { data: lesson } = await supabase
    .from('lessons')
    .select('id, module_id, order_index, module:modules(roadmap_id, order_index, roadmap:roadmaps(user_id))')
    .eq('id', lessonId)
    .single()

  if (!lesson) return NextResponse.json({ error: 'Lesson not found' }, { status: 404 })
  const roadmap = (lesson.module as unknown as { roadmap: { user_id: string } }).roadmap
  if (roadmap.user_id !== user.id) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  // Mark lesson complete
  await supabase.from('lesson_progress').upsert({
    user_id: user.id,
    lesson_id: lessonId,
    completed_at: new Date().toISOString(),
    time_spent_seconds: time_spent_seconds ?? 0,
  }, { onConflict: 'user_id,lesson_id' })

  // Update streak
  const today = new Date().toISOString().split('T')[0]
  const { data: streak } = await supabase
    .from('learning_streaks')
    .select('*')
    .eq('user_id', user.id)
    .single()

  if (streak) {
    const lastDate = streak.last_activity_date
    const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0]
    let newStreak = streak.current_streak

    if (lastDate === today) {
      // Already studied today, no change
    } else if (lastDate === yesterday) {
      newStreak = streak.current_streak + 1
    } else {
      newStreak = 1
    }

    await supabase.from('learning_streaks').update({
      current_streak: newStreak,
      longest_streak: Math.max(streak.longest_streak, newStreak),
      last_activity_date: today,
    }).eq('user_id', user.id)
  } else {
    await supabase.from('learning_streaks').insert({
      user_id: user.id,
      current_streak: 1,
      longest_streak: 1,
      last_activity_date: today,
    })
  }

  // Check if all lessons in module are complete
  const { data: moduleLessons } = await supabase
    .from('lessons')
    .select('id')
    .eq('module_id', lesson.module_id)

  const { data: completedLessons } = await supabase
    .from('lesson_progress')
    .select('lesson_id')
    .eq('user_id', user.id)
    .not('completed_at', 'is', null)
    .in('lesson_id', (moduleLessons ?? []).map(l => l.id))

  let unlockedModuleId: string | null = null

  if ((completedLessons?.length ?? 0) >= (moduleLessons?.length ?? 1)) {
    // Unlock next module
    const currentModuleIndex = (lesson.module as unknown as { order_index: number }).order_index
    const { data: nextModule } = await supabase
      .from('modules')
      .select('id')
      .eq('roadmap_id', (lesson.module as unknown as { roadmap_id: string }).roadmap_id)
      .eq('order_index', currentModuleIndex + 1)
      .single()

    if (nextModule) {
      await supabase.from('modules').update({ is_locked: false }).eq('id', nextModule.id)
      unlockedModuleId = nextModule.id

      // Update knowledge node for completed module
      const moduleTitle = (lesson.module as unknown as { title?: string }).title
      if (moduleTitle) {
        await supabase.from('knowledge_nodes')
          .update({ is_completed: true })
          .eq('roadmap_id', (lesson.module as unknown as { roadmap_id: string }).roadmap_id)
          .eq('skill_name', moduleTitle)
      }
    }
  }

  return NextResponse.json({ success: true, unlocked_module_id: unlockedModuleId })
}
