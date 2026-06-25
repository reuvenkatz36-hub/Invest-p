import { createClient, getAuthUser } from '@/lib/supabase/server'
import { redirect, notFound } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { QuizInterface } from '@/components/quiz/QuizInterface'
import { QuizQuestion } from '@/lib/types'

interface Props {
  params: Promise<{ id: string; moduleId: string; lessonId: string }>
}

async function getOrGenerateQuiz(lessonId: string) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_APP_URL}/api/quizzes/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lesson_id: lessonId }),
    cache: 'no-store',
  })
  if (!res.ok) return null
  return res.json()
}

export default async function QuizPage({ params }: Props) {
  const { id: roadmapId, moduleId, lessonId } = await params
  const user = await getAuthUser()
  if (!user) redirect('/login')

  const supabase = await createClient()

  const { data: lesson } = await supabase
    .from('lessons')
    .select('title, module:modules(roadmap:roadmaps(user_id)), lesson_progress!left(completed_at), quizzes(id, questions_json)')
    .eq('id', lessonId)
    .single()

  if (!lesson) notFound()
  const roadmap = ((lesson.module as unknown) as { roadmap: { user_id: string } }).roadmap
  if (roadmap.user_id !== user.id) redirect('/dashboard')

  // Must complete lesson first
  const isCompleted = lesson.lesson_progress?.some((p: { completed_at: string | null }) => p.completed_at)
  if (!isCompleted) {
    redirect(`/roadmaps/${roadmapId}/modules/${moduleId}/lessons/${lessonId}`)
  }

  const quizzes = lesson.quizzes as { id: string; questions_json: QuizQuestion[] }[]
  let quiz = quizzes?.[0]

  if (!quiz) {
    // Generate quiz server-side
    const supabaseCheck = await supabase
      .from('quizzes')
      .select('id, questions_json')
      .eq('lesson_id', lessonId)
      .single()
    quiz = supabaseCheck.data as { id: string; questions_json: QuizQuestion[] }
  }

  if (!quiz) {
    return (
      <div className="max-w-2xl mx-auto text-center py-24">
        <p className="text-gray-500">Quiz not available. Please complete the lesson first.</p>
        <Link href={`/roadmaps/${roadmapId}/modules/${moduleId}/lessons/${lessonId}`}>
          <Button variant="outline" className="mt-4">Back to Lesson</Button>
        </Link>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center gap-2 mb-6 text-sm text-gray-500">
        <Link href={`/roadmaps/${roadmapId}/modules/${moduleId}/lessons/${lessonId}`} className="hover:text-violet-600 flex items-center gap-1">
          <ArrowLeft className="w-3 h-3" /> {lesson.title}
        </Link>
        <span>/</span>
        <span className="text-gray-900 dark:text-gray-100 font-medium">Quiz</span>
      </div>

      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">Knowledge Check</h1>
        <p className="text-gray-500 dark:text-gray-400">Test your understanding of {lesson.title}. You need 60% to pass.</p>
      </div>

      <QuizInterface
        quizId={quiz.id}
        questions={quiz.questions_json}
        roadmapId={roadmapId}
        moduleId={moduleId}
        lessonId={lessonId}
      />
    </div>
  )
}
