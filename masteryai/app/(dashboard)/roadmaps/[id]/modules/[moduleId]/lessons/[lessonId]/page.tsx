import { createClient, getAuthUser } from '@/lib/supabase/server'
import { redirect, notFound } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, ClipboardList, Pencil } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LessonContent } from '@/components/lesson/LessonContent'
import { LessonSection } from '@/lib/types'

interface Props {
  params: Promise<{ id: string; moduleId: string; lessonId: string }>
}

export default async function LessonPage({ params }: Props) {
  const { id: roadmapId, moduleId, lessonId } = await params
  const user = await getAuthUser()
  if (!user) redirect('/login')

  const supabase = await createClient()

  const { data: lesson } = await supabase
    .from('lessons')
    .select(`
      *,
      module:modules ( title, roadmap:roadmaps ( goal, user_id ) ),
      lesson_progress!left ( completed_at ),
      quizzes ( id ),
      assignments ( id )
    `)
    .eq('id', lessonId)
    .single()

  if (!lesson) notFound()
  const roadmap = (lesson.module as { roadmap: { user_id: string } }).roadmap
  if (roadmap.user_id !== user.id) redirect('/dashboard')

  const isCompleted = lesson.lesson_progress?.some((p: { completed_at: string | null }) => p.completed_at) ?? false
  const hasQuiz = (lesson.quizzes as { id: string }[])?.length > 0
  const hasAssignment = (lesson.assignments as { id: string }[])?.length > 0

  return (
    <div className="max-w-4xl mx-auto">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 mb-6 text-sm text-gray-500">
        <Link href={`/roadmaps/${roadmapId}`} className="hover:text-violet-600 flex items-center gap-1">
          <ArrowLeft className="w-3 h-3" />
          {(lesson.module as { title: string }).title}
        </Link>
        <span>/</span>
        <span className="text-gray-900 dark:text-gray-100 font-medium truncate">{lesson.title}</span>
      </div>

      {/* Lesson header */}
      <div className="mb-8">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <h1 className="text-3xl font-bold flex-1">{lesson.title}</h1>
          <div className="flex gap-2 flex-wrap">
            {isCompleted && (
              <Link href={`/roadmaps/${roadmapId}/modules/${moduleId}/lessons/${lessonId}/quiz`}>
                <Button variant="outline" size="sm" className="gap-2">
                  <ClipboardList className="w-4 h-4" /> Quiz
                </Button>
              </Link>
            )}
            {isCompleted && (
              <Link href={`/roadmaps/${roadmapId}/modules/${moduleId}/lessons/${lessonId}/assignment`}>
                <Button variant="outline" size="sm" className="gap-2">
                  <Pencil className="w-4 h-4" /> Assignment
                </Button>
              </Link>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 mt-3">
          <Badge variant={isCompleted ? 'success' : 'outline'}>
            {isCompleted ? '✓ Completed' : 'In Progress'}
          </Badge>
        </div>
      </div>

      {/* Lesson content */}
      <LessonContent
        lessonId={lessonId}
        lessonTitle={lesson.title}
        roadmapId={roadmapId}
        moduleId={moduleId}
        cachedContent={lesson.content_json as LessonSection[] | null}
        isCompleted={isCompleted}
      />
    </div>
  )
}
