import { createClient } from '@/lib/supabase/server'
import { getAuthUser } from '@/lib/supabase/server'
import Link from 'next/link'
import { redirect } from 'next/navigation'
import { Plus, BookOpen, ChevronRight, Lock, Unlock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { formatDate } from '@/lib/utils'

export default async function RoadmapsPage() {
  const user = await getAuthUser()
  if (!user) redirect('/login')

  const supabase = await createClient()
  const { data: roadmaps } = await supabase
    .from('roadmaps')
    .select('*, modules(id, is_locked, lessons(id, lesson_progress(completed_at)))')
    .eq('user_id', user.id)
    .order('created_at', { ascending: false })

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Your Roadmaps</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">Continue learning or start a new journey</p>
        </div>
        <Link href="/onboarding">
          <Button className="gap-2">
            <Plus className="w-4 h-4" /> New Roadmap
          </Button>
        </Link>
      </div>

      {(!roadmaps || roadmaps.length === 0) ? (
        <div className="text-center py-24">
          <div className="w-20 h-20 rounded-2xl bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center mx-auto mb-4">
            <BookOpen className="w-10 h-10 text-violet-400" />
          </div>
          <h2 className="text-xl font-semibold mb-2">No roadmaps yet</h2>
          <p className="text-gray-500 dark:text-gray-400 mb-6">Create your first AI-powered learning roadmap to get started</p>
          <Link href="/onboarding">
            <Button size="lg" className="gap-2">
              <Plus className="w-5 h-5" /> Create your first roadmap
            </Button>
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {roadmaps.map(roadmap => {
            const modules = roadmap.modules ?? []
            const allLessons = modules.flatMap((m: { lessons: { lesson_progress: { completed_at: string | null }[] }[] }) => m.lessons ?? [])
            const completedLessons = allLessons.filter((l: { lesson_progress: { completed_at: string | null }[] }) =>
              l.lesson_progress?.some((p: { completed_at: string | null }) => p.completed_at)
            ).length
            const progress = allLessons.length > 0
              ? Math.round((completedLessons / allLessons.length) * 100)
              : 0

            return (
              <Link key={roadmap.id} href={`/roadmaps/${roadmap.id}`}>
                <Card className="hover:border-violet-300 dark:hover:border-violet-700 transition-all cursor-pointer group h-full">
                  <CardHeader>
                    <div className="flex items-start justify-between gap-2">
                      <CardTitle className="text-base leading-tight group-hover:text-violet-600 transition-colors">
                        {roadmap.title}
                      </CardTitle>
                      <ChevronRight className="w-4 h-4 text-gray-400 group-hover:text-violet-500 shrink-0 mt-0.5" />
                    </div>
                    <CardDescription className="line-clamp-2">{roadmap.description}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center gap-2 mb-3 flex-wrap">
                      <Badge variant="secondary" className="text-xs capitalize">{roadmap.experience_level}</Badge>
                      <Badge variant="outline" className="text-xs">{roadmap.hours_per_week}h/week</Badge>
                      <Badge variant="outline" className="text-xs">{modules.length} modules</Badge>
                    </div>
                    <div>
                      <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                        <span>{completedLessons}/{allLessons.length} lessons</span>
                        <span>{progress}%</span>
                      </div>
                      <div className="h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-violet-500 to-indigo-500 rounded-full transition-all"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                    </div>
                    <p className="text-xs text-gray-400 mt-3">{formatDate(roadmap.created_at)}</p>
                  </CardContent>
                </Card>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
