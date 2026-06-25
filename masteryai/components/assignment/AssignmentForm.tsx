'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2, Send, CheckCircle2, Star } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Assignment, AssignmentSubmission } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Props {
  assignment: Assignment
  existingSubmission?: AssignmentSubmission | null
  roadmapId: string
  moduleId: string
  lessonId: string
}

export function AssignmentForm({ assignment, existingSubmission, roadmapId, moduleId, lessonId }: Props) {
  const [response, setResponse] = useState(existingSubmission?.response_text ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<{ feedback: string; score: number; key_takeaways: string[] } | null>(
    existingSubmission ? {
      feedback: existingSubmission.ai_feedback ?? '',
      score: existingSubmission.score ?? 0,
      key_takeaways: [],
    } : null
  )
  const router = useRouter()

  async function handleSubmit() {
    if (!response.trim() || submitting) return
    setSubmitting(true)

    try {
      const res = await fetch(`/api/assignments/${assignment.id}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response_text: response }),
      })
      const data = await res.json()
      setResult(data)
    } catch {
      console.error('Submit error')
    } finally {
      setSubmitting(false)
    }
  }

  const scoreColor = result
    ? result.score >= 80 ? 'text-green-500' : result.score >= 60 ? 'text-yellow-500' : 'text-red-400'
    : ''

  return (
    <div className="space-y-6">
      {/* Assignment prompt */}
      <Card className="border-violet-200 dark:border-violet-800 bg-violet-50 dark:bg-violet-900/10">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Badge variant="default" className="text-xs">
              {assignment.type === 'project' ? '🛠 Project' : '💭 Reflection'}
            </Badge>
          </div>
          <CardTitle className="text-base font-medium mt-2">{assignment.prompt}</CardTitle>
        </CardHeader>
      </Card>

      {/* Response input */}
      {!result ? (
        <div>
          <Textarea
            value={response}
            onChange={e => setResponse(e.target.value)}
            placeholder="Write your response here. Be thorough — the AI will give you specific feedback based on your answer..."
            className="min-h-[200px] text-sm"
          />
          <div className="flex items-center justify-between mt-3">
            <p className="text-xs text-gray-400">{response.length} characters</p>
            <Button
              onClick={handleSubmit}
              disabled={submitting || response.trim().length < 50}
              className="gap-2"
            >
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              {submitting ? 'Getting AI Feedback...' : 'Submit for AI Feedback'}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Score */}
          <div className="flex items-center gap-4 p-4 bg-gray-50 dark:bg-gray-800 rounded-xl">
            <div className="text-center">
              <div className={cn('text-4xl font-bold', scoreColor)}>{result.score}</div>
              <div className="text-xs text-gray-500">/ 100</div>
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-1 mb-1">
                {[1, 2, 3, 4, 5].map(s => (
                  <Star
                    key={s}
                    className={cn(
                      'w-4 h-4',
                      s <= Math.round(result.score / 20) ? 'text-yellow-400 fill-yellow-400' : 'text-gray-300'
                    )}
                  />
                ))}
              </div>
              <p className="text-sm font-medium">
                {result.score >= 80 ? 'Excellent work!' : result.score >= 60 ? 'Good effort!' : 'Keep practicing!'}
              </p>
            </div>
          </div>

          {/* AI Feedback */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-semibold text-violet-600">AI Coach Feedback</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap">
                {result.feedback}
              </div>
            </CardContent>
          </Card>

          {/* Key takeaways */}
          {result.key_takeaways?.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-semibold">Key Takeaways</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {result.key_takeaways.map((t, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm">
                      <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0 mt-0.5" />
                      {t}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          <Button
            onClick={() => router.push(`/roadmaps/${roadmapId}`)}
            className="w-full gap-2"
            size="lg"
          >
            <CheckCircle2 className="w-5 h-5" />
            Continue to Next Lesson
          </Button>
        </div>
      )}
    </div>
  )
}
