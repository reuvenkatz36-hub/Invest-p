import { createClient, getAuthUser } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'
import Link from 'next/link'
import { Plus, Flame, BookOpen, Clock, Target, TrendingUp, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { formatMinutes } from '@/lib/utils'

export default async function DashboardPage() {
  const user = await getAuthUser()
  if (!user) redirect('/login')

  const supabase = await createClient()

  const [
    { data: roadmaps },
    { data: streak },
    { data: recentProgress },
    { data: quizAttempts },
  ] = await Promise.all([
    supabase.from('roadmaps').select(`
      id, title, goal, experience_level, created_at,
      modules(id, is_locked, lessons(id, lesson_progress!left(completed_at, time_spent_seconds)))
    `).eq('user_id', user.id).order('created_at', { ascending: false }).limit(3),
    supabase.from('learning_streaks').select('*').eq('user_id', user.id).single(),
    supabase.from('lesson_progress').select('completed_at, time_spent_seconds').eq('user_id', user.id).not('completed_at', 'is', null),
    supabase.from('quiz_attempts').select('score').eq('user_id', user.id),
  ])

  const totalLessons = recentProgress?.length ?? 0
  const totalMinutes = Math.round((recentProgress ?? []).reduce((sum, p) => sum + (p.time_spent_seconds ?? 0), 0) / 60)
  const avgQuizScore = (quizAttempts ?? []).length > 0
    ? Math.round((quizAttempts ?? []).reduce((sum, q) => sum + q.score, 0) / (quizAttempts ?? []).length)
    : 0

  const hasRoadmaps = (roadmaps?.length ?? 0) > 0

  if (!hasRoadmaps) {
    redirect('/onboarding')
  }

  const stats = [
    { label: 'Day Streak', value: streak?.current_streak ?? 0, icon: Flame, color: 'text-orange-500', bg: 'bg-orange-50 dark:bg-orange-900/20' },
    { label: 'Lessons Done', value: totalLessons, icon: BookOpen, color: 'text-violet-500', bg: 'bg-violet-50 dark:bg-violet-900/20' },
    { label: 'Time Studied', value: formatMinutes(totalMinutes), icon: Clock, color: 'text-blue-500', bg: 'bg-blue-50 dark:bg-blue-900/20' },
    { label: 'Avg Quiz Score', value: avgQuizScore ? `${avgQuizScore}%` : '—', icon: TrendingUp, color: 'text-green-500', bg: 'bg-green-50 dark:bg-green-900/20' },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">Track your learning progress</p>
        </div>
        <Link href="/onboarding">
          <Button className="gap-2" variant="outline">
            <Plus className="w-4 h-4" /> New Roadmap
          </Button>
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {stats.map(({ label, value, icon: Icon, color, bg }) => (
          <Card key={label}>
            <CardContent className="p-5">
              <div className={`w-10 h-10 rounded-xl ${bg} flex items-center justify-center mb-3`}>
                <Icon className={`w-5 h-5 ${color}`} />
              </div>
              <div className="text-2xl font-bold">{value}</div>
              <div className="text-sm text-gray-500 dark:text-gray-400">{label}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Active roadmaps */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Your Learning Paths</h2>
        <Link href="/roadmaps" className="text-sm text-violet-600 hover:text-violet-700">
          View all
        </Link>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {(roadmaps ?? []).map(roadmap => {
          const modules = roadmap.modules ?? []
          const allLessons = modules.flatMap((m: { lessons: { lesson_progress: { completed_at: string | null }[] }[] }) => m.lessons ?? [])
          const completedLessons = allLessons.filter((l: { lesson_progress: { completed_at: string | null }[] }) =>
            l.lesson_progress?.some((p: { completed_at: string | null }) => p.completed_at)
          ).length
          const progress = allLessons.length > 0 ? Math.round((completedLessons / allLessons.length) * 100) : 0

          return (
            <Link key={roadmap.id} href={`/roadmaps/${roadmap.id}`}>
              <Card className="hover:border-violet-300 dark:hover:border-violet-700 transition-all cursor-pointer group">
                <CardContent className="p-5">
                  <div className="flex items-start justify-between gap-2 mb-3">
                    <h3 className="font-semibold text-sm leading-tight group-hover:text-violet-600 transition-colors">
                      {roadmap.title}
                    </h3>
                    <ChevronRight className="w-4 h-4 text-gray-400 group-hover:text-violet-500 shrink-0" />
                  </div>
                  <Badge variant="secondary" className="text-xs capitalize mb-3">{roadmap.experience_level}</Badge>
                  <div>
                    <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                      <span>{completedLessons}/{allLessons.length} lessons</span>
                      <span>{progress}%</span>
                    </div>
                    <Progress value={progress} className="h-1.5" />
                  </div>
                </CardContent>
              </Card>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
