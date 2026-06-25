import { NextRequest, NextResponse } from 'next/server'
import { getAuthUser, createClient } from '@/lib/supabase/server'
import { QuizQuestion } from '@/lib/types'

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { id: quizId } = await params
  const { answers } = await req.json()
  const supabase = await createClient()

  const { data: quiz } = await supabase
    .from('quizzes')
    .select('questions_json')
    .eq('id', quizId)
    .single()

  if (!quiz) return NextResponse.json({ error: 'Quiz not found' }, { status: 404 })

  const questions = quiz.questions_json as QuizQuestion[]
  let correct = 0
  const results = questions.map((q, i) => {
    const isCorrect = answers[i] === q.correct_index
    if (isCorrect) correct++
    return {
      question: q.question,
      selected: answers[i],
      correct_index: q.correct_index,
      is_correct: isCorrect,
      explanation: q.explanation,
    }
  })

  const score = Math.round((correct / questions.length) * 100)

  await supabase.from('quiz_attempts').insert({
    user_id: user.id,
    quiz_id: quizId,
    answers_json: answers,
    score,
  })

  return NextResponse.json({ score, correct, total: questions.length, results })
}
