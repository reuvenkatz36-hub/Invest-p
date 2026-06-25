'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2, CheckCircle2, XCircle, ChevronRight, Trophy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { QuizQuestion } from '@/lib/types'
import { cn } from '@/lib/utils'

interface QuizResult {
  question: string
  selected: number
  correct_index: number
  is_correct: boolean
  explanation: string
}

interface Props {
  quizId: string
  questions: QuizQuestion[]
  roadmapId: string
  moduleId: string
  lessonId: string
}

export function QuizInterface({ quizId, questions, roadmapId, moduleId, lessonId }: Props) {
  const [currentQ, setCurrentQ] = useState(0)
  const [answers, setAnswers] = useState<number[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const [results, setResults] = useState<{ score: number; correct: number; total: number; results: QuizResult[] } | null>(null)
  const [loading, setLoading] = useState(false)
  const router = useRouter()

  function selectAnswer(index: number) {
    if (selected !== null) return
    setSelected(index)
  }

  function nextQuestion() {
    const newAnswers = [...answers, selected!]
    setAnswers(newAnswers)
    setSelected(null)

    if (currentQ < questions.length - 1) {
      setCurrentQ(q => q + 1)
    } else {
      submitQuiz(newAnswers)
    }
  }

  async function submitQuiz(finalAnswers: number[]) {
    setLoading(true)
    try {
      const res = await fetch(`/api/quizzes/${quizId}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: finalAnswers }),
      })
      const data = await res.json()
      setResults(data)
      setSubmitted(true)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4">
        <Loader2 className="w-10 h-10 animate-spin text-violet-500" />
        <p className="text-gray-500">Scoring your quiz...</p>
      </div>
    )
  }

  if (submitted && results) {
    const pct = results.score
    const passed = pct >= 60

    return (
      <div className="max-w-2xl mx-auto">
        {/* Score card */}
        <div className={cn(
          'rounded-2xl p-8 text-center mb-8 border',
          passed
            ? 'bg-gradient-to-br from-green-50 to-emerald-50 dark:from-green-900/20 dark:to-emerald-900/20 border-green-200 dark:border-green-800'
            : 'bg-gradient-to-br from-orange-50 to-red-50 dark:from-orange-900/20 dark:to-red-900/20 border-orange-200 dark:border-orange-800'
        )}>
          <Trophy className={cn('w-12 h-12 mx-auto mb-3', passed ? 'text-green-500' : 'text-orange-400')} />
          <div className="text-5xl font-bold mb-2">{pct}%</div>
          <p className="text-lg font-semibold mb-1">{passed ? 'Great job!' : 'Keep practicing!'}</p>
          <p className="text-gray-500 text-sm">{results.correct}/{results.total} questions correct</p>
        </div>

        {/* Question review */}
        <div className="space-y-4 mb-8">
          {results.results.map((r, i) => (
            <Card key={i} className={cn(
              'border-l-4',
              r.is_correct ? 'border-l-green-500' : 'border-l-red-400'
            )}>
              <CardContent className="pt-4">
                <div className="flex items-start gap-2 mb-3">
                  {r.is_correct ? (
                    <CheckCircle2 className="w-5 h-5 text-green-500 shrink-0 mt-0.5" />
                  ) : (
                    <XCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                  )}
                  <p className="font-medium text-sm">{r.question}</p>
                </div>
                {!r.is_correct && (
                  <div className="ml-7 space-y-1.5 mb-3">
                    <p className="text-xs text-red-500">Your answer: {questions[i]?.options[r.selected]}</p>
                    <p className="text-xs text-green-600">Correct: {questions[i]?.options[r.correct_index]}</p>
                  </div>
                )}
                <p className="ml-7 text-xs text-gray-500 bg-gray-50 dark:bg-gray-800 rounded-lg p-2">{r.explanation}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="flex gap-3">
          <Button
            variant="outline"
            onClick={() => router.push(`/roadmaps/${roadmapId}/modules/${moduleId}/lessons/${lessonId}`)}
            className="gap-2"
          >
            Back to Lesson
          </Button>
          <Button
            onClick={() => router.push(`/roadmaps/${roadmapId}/modules/${moduleId}/lessons/${lessonId}/assignment`)}
            className="gap-2 flex-1"
          >
            Continue to Assignment <ChevronRight className="w-4 h-4" />
          </Button>
        </div>
      </div>
    )
  }

  const question = questions[currentQ]

  return (
    <div className="max-w-2xl mx-auto">
      {/* Progress */}
      <div className="flex items-center justify-between mb-6">
        <p className="text-sm text-gray-500">Question {currentQ + 1} of {questions.length}</p>
        <div className="flex gap-1">
          {questions.map((_, i) => (
            <div
              key={i}
              className={cn(
                'w-6 h-1.5 rounded-full transition-all',
                i < currentQ ? 'bg-violet-500' :
                i === currentQ ? 'bg-violet-300' :
                'bg-gray-200 dark:bg-gray-700'
              )}
            />
          ))}
        </div>
      </div>

      {/* Question */}
      <div className="mb-6">
        <h3 className="text-lg font-semibold mb-4">{question.question}</h3>
        <div className="space-y-3">
          {question.options.map((option, i) => (
            <button
              key={i}
              onClick={() => selectAnswer(i)}
              className={cn(
                'w-full text-left p-4 rounded-xl border-2 transition-all text-sm',
                selected === null
                  ? 'border-gray-200 dark:border-gray-700 hover:border-violet-300 hover:bg-violet-50 dark:hover:bg-violet-900/10'
                  : selected === i
                    ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20'
                    : 'border-gray-200 dark:border-gray-700 opacity-50'
              )}
            >
              <span className="inline-flex items-center gap-2">
                <span className={cn(
                  'w-6 h-6 rounded-full border-2 flex items-center justify-center text-xs font-bold',
                  selected === i
                    ? 'border-violet-500 bg-violet-500 text-white'
                    : 'border-gray-300 dark:border-gray-600'
                )}>
                  {String.fromCharCode(65 + i)}
                </span>
                {option}
              </span>
            </button>
          ))}
        </div>
      </div>

      <Button
        onClick={nextQuestion}
        disabled={selected === null}
        className="w-full gap-2"
        size="lg"
      >
        {currentQ === questions.length - 1 ? 'Submit Quiz' : 'Next Question'}
        <ChevronRight className="w-4 h-4" />
      </Button>
    </div>
  )
}
