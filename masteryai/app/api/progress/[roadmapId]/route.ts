import { NextRequest, NextResponse } from 'next/server'
import { getAuthUser, createClient } from '@/lib/supabase/server'

export async function GET(req: NextRequest, { params }: { params: Promise<{ roadmapId: string }> }) {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { roadmapId } = await params
  const supabase = await createClient()

  const [
    { data: modules },
    { data: streak },
    { data: quizAttempts },
    { data: progress },
  ] = await Promise.all([
    supabase.from('modules').select('id, lessons(id)').eq('roadmap_id', roadmapId),
    supabase.from('learning_streaks').select('*').eq('user_id', user.id).single(),
    supabase.from('quiz_attempts').select('score, completed_at, quiz:quizzes(lesson:lessons(title))').eq('user_id', user.id).order('completed_at', { ascending: false }).limit(30),
    supabase.from('lesson_progress').select('completed_at, time_spent_seconds').eq('user_id', user.id).not('completed_at', 'is', null),
  ])

  const allLessonIds = (modules ?? []).flatMap(m => (m.lessons ?? []).map((l: { id: string }) => l.id))
  const { data: completedProgress } = await supabase
    .from('lesson_progress')
    .select('lesson_id, completed_at')
    .eq('user_id', user.id)
    .not('completed_at', 'is', null)
    .in('lesson_id', allLessonIds)

  const lessonsDone = completedProgress?.length ?? 0
  const lessonsTotal = allLessonIds.length
  const quizScores = (quizAttempts ?? []).map(q => q.score)
  const quizAverage = quizScores.length > 0
    ? Math.round(quizScores.reduce((a, b) => a + b, 0) / quizScores.length)
    : 0
  const timeMinutes = Math.round(
    (progress ?? []).reduce((sum, p) => sum + (p.time_spent_seconds ?? 0), 0) / 60
  )

  // Activity by date (last 90 days)
  const activityByDate: Record<string, number> = {}
  ;(completedProgress ?? []).forEach(p => {
    if (p.completed_at) {
      const date = p.completed_at.split('T')[0]
      activityByDate[date] = (activityByDate[date] ?? 0) + 1
    }
  })

  // Recent quiz scores for chart
  const recentQuizScores = (quizAttempts ?? []).slice(0, 10).map(q => ({
    date: q.completed_at?.split('T')[0] ?? '',
    score: q.score,
    lesson: (q.quiz as unknown as { lesson: { title: string } })?.lesson?.title ?? 'Quiz',
  })).reverse()

  return NextResponse.json({
    lessons_completed: lessonsDone,
    lessons_total: lessonsTotal,
    quiz_average: quizAverage,
    time_studied_minutes: timeMinutes,
    current_streak: streak?.current_streak ?? 0,
    longest_streak: streak?.longest_streak ?? 0,
    recent_quiz_scores: recentQuizScores,
    activity_by_date: activityByDate,
  })
}
