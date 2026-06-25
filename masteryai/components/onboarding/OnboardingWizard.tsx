'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2, ArrowRight, ArrowLeft, Sparkles, BookOpen, Clock, Target } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

const EXAMPLE_GOALS = [
  'Learn investing', 'Start a business', 'Become a software engineer',
  'Learn psychology', 'Master sales', 'Learn digital marketing', 'Learn AI & ML',
  'Learn personal finance', 'Improve public speaking',
]

const LEVELS = [
  { value: 'beginner', label: 'Beginner', desc: 'Little to no experience with this topic', emoji: '🌱' },
  { value: 'intermediate', label: 'Intermediate', desc: 'Some knowledge, ready to go deeper', emoji: '🌿' },
  { value: 'advanced', label: 'Advanced', desc: 'Strong foundation, seeking mastery', emoji: '🌳' },
]

const HOURS_OPTIONS = [
  { value: 2, label: '2 hrs/week', desc: 'Light pace — great for busy schedules' },
  { value: 5, label: '5 hrs/week', desc: 'Steady progress — recommended' },
  { value: 10, label: '10 hrs/week', desc: 'Fast track — accelerated learning' },
  { value: 20, label: '20+ hrs/week', desc: 'Intensive — total immersion' },
]

export function OnboardingWizard() {
  const [step, setStep] = useState(0)
  const [goal, setGoal] = useState('')
  const [level, setLevel] = useState('')
  const [hours, setHours] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const router = useRouter()

  const steps = ['Your Goal', 'Your Level', 'Your Time']
  const canNext = [goal.trim().length > 3, level !== '', hours !== null]

  async function handleGenerate() {
    if (!goal || !level || !hours) return
    setLoading(true)
    setError('')

    try {
      const res = await fetch('/api/roadmaps/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal, experience_level: level, hours_per_week: hours }),
      })

      const data = await res.json()
      if (!res.ok) {
        setError(data.message || 'Failed to generate roadmap. Please try again.')
        setLoading(false)
        return
      }

      router.push(`/roadmaps/${data.roadmap_id}`)
    } catch {
      setError('Something went wrong. Please try again.')
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      {/* Step indicator */}
      <div className="flex items-center justify-center gap-3 mb-10">
        {steps.map((s, i) => (
          <div key={s} className="flex items-center gap-3">
            <div className={cn(
              'flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-medium transition-all',
              i === step ? 'bg-violet-600 text-white' :
              i < step ? 'bg-violet-100 dark:bg-violet-900/30 text-violet-600' :
              'bg-gray-100 dark:bg-gray-800 text-gray-400'
            )}>
              <span className="w-5 h-5 rounded-full bg-white/20 flex items-center justify-center text-xs font-bold">
                {i < step ? '✓' : i + 1}
              </span>
              {s}
            </div>
            {i < steps.length - 1 && (
              <div className={cn('h-px w-8', i < step ? 'bg-violet-400' : 'bg-gray-200 dark:bg-gray-700')} />
            )}
          </div>
        ))}
      </div>

      {/* Step 0: Goal */}
      {step === 0 && (
        <div className="space-y-6">
          <div className="text-center">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center mx-auto mb-4">
              <Target className="w-7 h-7 text-white" />
            </div>
            <h2 className="text-3xl font-bold mb-2">What do you want to achieve?</h2>
            <p className="text-gray-500 dark:text-gray-400">Be specific — the more detail, the better your roadmap will be.</p>
          </div>
          <div className="space-y-3">
            <Input
              value={goal}
              onChange={e => setGoal(e.target.value)}
              placeholder="e.g. Learn investing, Start a business, Become a software engineer..."
              className="h-14 text-base"
              onKeyDown={e => e.key === 'Enter' && canNext[0] && setStep(1)}
              autoFocus
            />
            <div className="flex flex-wrap gap-2">
              {EXAMPLE_GOALS.map(g => (
                <button
                  key={g}
                  onClick={() => setGoal(g)}
                  className={cn(
                    'px-3 py-1.5 rounded-full text-sm border transition-all',
                    goal === g
                      ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20 text-violet-600'
                      : 'border-gray-200 dark:border-gray-700 hover:border-violet-300 text-gray-600 dark:text-gray-400'
                  )}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Step 1: Level */}
      {step === 1 && (
        <div className="space-y-6">
          <div className="text-center">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center mx-auto mb-4">
              <BookOpen className="w-7 h-7 text-white" />
            </div>
            <h2 className="text-3xl font-bold mb-2">What's your experience level?</h2>
            <p className="text-gray-500 dark:text-gray-400">Your roadmap will be tailored to where you are right now.</p>
          </div>
          <div className="grid gap-3">
            {LEVELS.map(l => (
              <button
                key={l.value}
                onClick={() => setLevel(l.value)}
                className={cn(
                  'flex items-center gap-4 p-4 rounded-xl border-2 transition-all text-left',
                  level === l.value
                    ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20'
                    : 'border-gray-200 dark:border-gray-700 hover:border-violet-200'
                )}
              >
                <span className="text-3xl">{l.emoji}</span>
                <div>
                  <p className="font-semibold">{l.label}</p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">{l.desc}</p>
                </div>
                <div className={cn(
                  'ml-auto w-5 h-5 rounded-full border-2 transition-all',
                  level === l.value ? 'border-violet-500 bg-violet-500' : 'border-gray-300'
                )} />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Step 2: Hours */}
      {step === 2 && (
        <div className="space-y-6">
          <div className="text-center">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center mx-auto mb-4">
              <Clock className="w-7 h-7 text-white" />
            </div>
            <h2 className="text-3xl font-bold mb-2">How much time can you commit?</h2>
            <p className="text-gray-500 dark:text-gray-400">We'll pace your roadmap to fit your schedule.</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {HOURS_OPTIONS.map(h => (
              <button
                key={h.value}
                onClick={() => setHours(h.value)}
                className={cn(
                  'p-4 rounded-xl border-2 transition-all text-left',
                  hours === h.value
                    ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20'
                    : 'border-gray-200 dark:border-gray-700 hover:border-violet-200'
                )}
              >
                <p className="font-bold text-lg">{h.label}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{h.desc}</p>
              </button>
            ))}
          </div>
          {error && (
            <div className="text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3">
              {error}
            </div>
          )}
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between mt-8">
        <Button
          variant="ghost"
          onClick={() => setStep(s => s - 1)}
          disabled={step === 0}
          className="gap-2"
        >
          <ArrowLeft className="w-4 h-4" /> Back
        </Button>

        {step < 2 ? (
          <Button
            onClick={() => setStep(s => s + 1)}
            disabled={!canNext[step]}
            className="gap-2"
            size="lg"
          >
            Next <ArrowRight className="w-4 h-4" />
          </Button>
        ) : (
          <Button
            onClick={handleGenerate}
            disabled={loading || !canNext[2]}
            size="lg"
            className="gap-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-700 hover:to-indigo-700"
          >
            {loading ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Generating your roadmap...</>
            ) : (
              <><Sparkles className="w-4 h-4" /> Generate My Roadmap</>
            )}
          </Button>
        )}
      </div>
    </div>
  )
}
