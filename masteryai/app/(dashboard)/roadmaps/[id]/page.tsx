import { createClient, getAuthUser } from '@/lib/supabase/server'
import { redirect, notFound } from 'next/navigation'
import Link from 'next/link'
import { Lock, CheckCircle2, Circle, ChevronRight, Network, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

export default async function RoadmapPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const user = await getAuthUser()
  if (!user) redirect('/login')

  const supabase = await createClient()
  const { data: roadmap } = await supabase
    .from('roadmaps')
    .select(`
      *,
      modules (
        *,
        lessons (
          id, title, order_index,
          lesson_progress!left ( completed_at )
        )
      )
    `)
    .eq('id', id)
    .eq('user_id', user.id)
    .single()

  if (!roadmap) notFound()

  const modules = (roadmap.modules ?? []).sort((a: { order_index: number }, b: { order_index: number }) => a.order_index - b.order_index)
  const allLessons = modules.flatMap((m: { lessons: unknown[] }) => m.lessons ?? [])
  const completedCount = (allLessons as { lesson_progress: { completed_at: string | null }[] }[]).filter(
    l => l.lesson_progress?.some(p => p.completed_at)
  ).length
  const progress = allLessons.length > 0 ? Math.round((completedCount / allLessons.length) * 100) : 0

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <Link href="/roadmaps">
          <Button variant="ghost" size="sm" className="gap-2 mb-4 text-gray-500">
            <ArrowLeft className="w-4 h-4" /> All Roadmaps
          </Button>
        </Link>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-3xl font-bold mb-2">{roadmap.title}</h1>
            <p className="text-gray-500 dark:text-gray-400">{roadmap.description}</p>
            <div className="flex flex-wrap gap-2 mt-3">
              <Badge variant="secondary" className="capitalize">{roadmap.experience_level}</Badge>
              <Badge variant="outline">{roadmap.hours_per_week}h/week</Badge>
              <Badge variant="outline">{modules.length} modules</Badge>
            </div>
          </div>
          <Link href={`/knowledge-graph/${id}`}>
            <Button variant="outline" className="gap-2 shrink-0">
              <Network className="w-4 h-4" /> Knowledge Graph
            </Button>
          </Link>
        </div>

        {/* Progress bar */}
        <div className="mt-6 p-4 bg-gradient-to-r from-violet-50 to-indigo-50 dark:from-violet-900/10 dark:to-indigo-900/10 rounded-xl border border-violet-100 dark:border-violet-800">
          <div className="flex justify-between text-sm mb-2">
            <span className="font-medium text-violet-700 dark:text-violet-300">Overall Progress</span>
            <span className="text-violet-600 dark:text-violet-400 font-bold">{progress}%</span>
          </div>
          <Progress value={progress} className="h-2" />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">{completedCount} of {allLessons.length} lessons completed</p>
        </div>
      </div>

      {/* Modules */}
      <div className="space-y-4">
        {modules.map((module: {
          id: string
          title: string
          description: string | null
          order_index: number
          is_locked: boolean
          lessons: { id: string; title: string; order_index: number; lesson_progress: { completed_at: string | null }[] }[]
        }, moduleIndex: number) => {
          const lessons = (module.lessons ?? []).sort((a, b) => a.order_index - b.order_index)
          const moduleDone = lessons.filter(l => l.lesson_progress?.some(p => p.completed_at)).length
          const moduleProgress = lessons.length > 0 ? Math.round((moduleDone / lessons.length) * 100) : 0

          return (
            <div
              key={module.id}
              className={cn(
                'rounded-xl border transition-all',
                module.is_locked
                  ? 'border-gray-200 dark:border-gray-800 opacity-60'
                  : 'border-gray-200 dark:border-gray-800 hover:border-violet-200 dark:hover:border-violet-800'
              )}
            >
              {/* Module header */}
              <div className="p-5 flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <div className={cn(
                    'w-9 h-9 rounded-lg flex items-center justify-center text-sm font-bold shrink-0',
                    module.is_locked
                      ? 'bg-gray-100 dark:bg-gray-800 text-gray-400'
                      : moduleProgress === 100
                        ? 'bg-green-100 dark:bg-green-900/30 text-green-600'
                        : 'bg-violet-100 dark:bg-violet-900/30 text-violet-600'
                  )}>
                    {module.is_locked ? <Lock className="w-4 h-4" /> : moduleIndex + 1}
                  </div>
                  <div>
                    <h3 className="font-semibold text-base">{module.title}</h3>
                    {module.description && (
                      <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{module.description}</p>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-xs text-gray-400">{moduleDone}/{lessons.length}</p>
                  {moduleProgress === 100 && (
                    <Badge variant="success" className="mt-1 text-xs">Complete</Badge>
                  )}
                </div>
              </div>

              {/* Lessons list */}
              {!module.is_locked && (
                <div className="border-t border-gray-100 dark:border-gray-800">
                  {lessons.map((lesson) => {
                    const isDone = lesson.lesson_progress?.some(p => p.completed_at)
                    return (
                      <Link
                        key={lesson.id}
                        href={`/roadmaps/${id}/modules/${module.id}/lessons/${lesson.id}`}
                        className="flex items-center gap-3 px-5 py-3 hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors border-b border-gray-50 dark:border-gray-900 last:border-0"
                      >
                        {isDone ? (
                          <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
                        ) : (
                          <Circle className="w-4 h-4 text-gray-300 shrink-0" />
                        )}
                        <span className={cn(
                          'text-sm flex-1',
                          isDone ? 'text-gray-400 line-through' : 'text-gray-700 dark:text-gray-300'
                        )}>
                          {lesson.title}
                        </span>
                        <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-violet-500" />
                      </Link>
                    )
                  })}
                </div>
              )}

              {module.is_locked && (
                <div className="border-t border-gray-100 dark:border-gray-800 px-5 py-3">
                  <p className="text-xs text-gray-400 flex items-center gap-1.5">
                    <Lock className="w-3 h-3" />
                    Complete the previous module to unlock
                  </p>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
