import { createClient, getAuthUser } from '@/lib/supabase/server'
import { redirect, notFound } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AssignmentForm } from '@/components/assignment/AssignmentForm'
import { anthropic, MODEL, assignmentPrompt } from '@/lib/anthropic'
import { extractJSON } from '@/lib/utils'
import { Assignment } from '@/lib/types'

interface Props {
  params: Promise<{ id: string; moduleId: string; lessonId: string }>
}

export default async function AssignmentPage({ params }: Props) {
  const { id: roadmapId, moduleId, lessonId } = await params
  const user = await getAuthUser()
  if (!user) redirect('/login')

  const supabase = await createClient()

  const { data: lesson } = await supabase
    .from('lessons')
    .select(`
      title,
      module:modules(title, roadmap:roadmaps(goal, user_id)),
      lesson_progress!left(completed_at),
      assignments(*)
    `)
    .eq('id', lessonId)
    .single()

  if (!lesson) notFound()
  const module_ = (lesson.module as unknown) as { title: string; roadmap: { goal: string; user_id: string } }
  if (module_.roadmap.user_id !== user.id) redirect('/dashboard')

  const isCompleted = lesson.lesson_progress?.some((p: { completed_at: string | null }) => p.completed_at)
  if (!isCompleted) {
    redirect(`/roadmaps/${roadmapId}/modules/${moduleId}/lessons/${lessonId}`)
  }

  let assignment = (lesson.assignments as Assignment[])?.[0]

  // Generate assignment if not exists
  if (!assignment) {
    const prompts = assignmentPrompt(module_.title, lesson.title, module_.roadmap.goal)
    const message = await anthropic.messages.create({
      model: MODEL,
      max_tokens: 1024,
      system: prompts.system,
      messages: [{ role: 'user', content: prompts.user }],
    })

    const rawText = (message.content[0] as { type: string; text: string }).text
    let parsed: { project_prompt: string; reflection_questions: string[] }
    try {
      parsed = JSON.parse(extractJSON(rawText))
    } catch {
      parsed = { project_prompt: rawText, reflection_questions: [] }
    }

    const { data: newAssignment } = await supabase
      .from('assignments')
      .insert({ lesson_id: lessonId, prompt: parsed.project_prompt, type: 'project' })
      .select()
      .single()

    assignment = newAssignment as Assignment
  }

  // Get existing submission
  const { data: submission } = await supabase
    .from('assignment_submissions')
    .select('*')
    .eq('user_id', user.id)
    .eq('assignment_id', assignment?.id)
    .single()

  if (!assignment) {
    return (
      <div className="text-center py-24">
        <p className="text-gray-500">Assignment not available. Please try again.</p>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center gap-2 mb-6 text-sm text-gray-500">
        <Link href={`/roadmaps/${roadmapId}/modules/${moduleId}/lessons/${lessonId}/quiz`} className="hover:text-violet-600 flex items-center gap-1">
          <ArrowLeft className="w-3 h-3" /> Quiz
        </Link>
        <span>/</span>
        <span className="text-gray-900 dark:text-gray-100 font-medium">Assignment</span>
      </div>

      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">Your Assignment</h1>
        <p className="text-gray-500 dark:text-gray-400">
          Complete this assignment to unlock the next lesson. You'll receive AI-powered feedback.
        </p>
      </div>

      <AssignmentForm
        assignment={assignment}
        existingSubmission={submission ?? null}
        roadmapId={roadmapId}
        moduleId={moduleId}
        lessonId={lessonId}
      />
    </div>
  )
}
