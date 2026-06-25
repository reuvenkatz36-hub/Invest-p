'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Loader2, CheckCircle2, BookOpen, Lightbulb, Globe, FileText, AlertTriangle, Scale, Dumbbell, List } from 'lucide-react'
import { LessonSection } from '@/lib/types'
import { cn } from '@/lib/utils'

const SECTION_ICONS: Record<string, React.ElementType> = {
  overview: BookOpen,
  key_concepts: Lightbulb,
  real_world_examples: Globe,
  case_studies: FileText,
  common_mistakes: AlertTriangle,
  contrarian_viewpoints: Scale,
  actionable_exercises: Dumbbell,
  summary: List,
}

interface Props {
  lessonId: string
  lessonTitle: string
  roadmapId: string
  moduleId: string
  cachedContent?: LessonSection[] | null
  isCompleted?: boolean
}

function renderMarkdown(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/^### (.*$)/gm, '<h3>$1</h3>')
    .replace(/^## (.*$)/gm, '<h2>$1</h2>')
    .replace(/^# (.*$)/gm, '<h1>$1</h1>')
    .replace(/^- (.*$)/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, match => `<ul>${match}</ul>`)
    .replace(/\n\n/g, '</p><p>')
    .replace(/<p><\/p>/g, '')
    .replace(/<p>(<[hulo])/g, '$1')
}

export function LessonContent({ lessonId, lessonTitle, roadmapId, moduleId, cachedContent, isCompleted }: Props) {
  const [sections, setSections] = useState<LessonSection[]>(cachedContent ?? [])
  const [loading, setLoading] = useState(!cachedContent || cachedContent.length === 0)
  const [activeTab, setActiveTab] = useState('overview')
  const [completing, setCompleting] = useState(false)
  const [completed, setCompleted] = useState(isCompleted ?? false)
  const startTime = useRef(Date.now())
  const router = useRouter()

  useEffect(() => {
    if (cachedContent && cachedContent.length > 0) return

    async function fetchLesson() {
      setLoading(true)
      try {
        const res = await fetch('/api/lessons/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ lesson_id: lessonId }),
        })

        if (!res.ok) {
          throw new Error('Failed to generate lesson')
        }

        const reader = res.body?.getReader()
        if (!reader) return

        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            if (!line.trim()) continue
            try {
              const section = JSON.parse(line) as LessonSection
              setSections(prev => {
                if (prev.find(s => s.section === section.section)) return prev
                return [...prev, section]
              })
            } catch {}
          }
        }
      } catch (err) {
        console.error('Lesson load error:', err)
      } finally {
        setLoading(false)
      }
    }

    fetchLesson()
  }, [lessonId, cachedContent])

  async function completeLesson() {
    setCompleting(true)
    const timeSpent = Math.round((Date.now() - startTime.current) / 1000)

    await fetch(`/api/lessons/${lessonId}/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ time_spent_seconds: timeSpent }),
    })

    setCompleted(true)
    setCompleting(false)
    router.push(`/roadmaps/${roadmapId}/modules/${moduleId}/lessons/${lessonId}/quiz`)
  }

  const sectionOrder = ['overview', 'key_concepts', 'real_world_examples', 'case_studies', 'common_mistakes', 'contrarian_viewpoints', 'actionable_exercises', 'summary']
  const availableSections = sectionOrder.filter(s => sections.find(sec => sec.section === s))
  const loadedCount = availableSections.length

  return (
    <div>
      {/* Progress indicator while loading */}
      {loading && loadedCount < 8 && (
        <div className="mb-4 flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="w-4 h-4 animate-spin text-violet-500" />
          <span>Generating lesson... ({loadedCount}/8 sections)</span>
          <div className="flex-1 h-1 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-violet-500 rounded-full transition-all duration-500"
              style={{ width: `${(loadedCount / 8) * 100}%` }}
            />
          </div>
        </div>
      )}

      {sections.length === 0 && loading ? (
        <div className="space-y-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="mb-6 gap-1 flex-wrap h-auto">
            {sectionOrder.map(sectionKey => {
              const section = sections.find(s => s.section === sectionKey)
              const Icon = SECTION_ICONS[sectionKey] ?? BookOpen
              const isAvailable = !!section

              return (
                <TabsTrigger
                  key={sectionKey}
                  value={sectionKey}
                  disabled={!isAvailable}
                  className={cn(
                    'gap-1.5 text-xs',
                    !isAvailable && 'opacity-30'
                  )}
                >
                  <Icon className="w-3 h-3" />
                  {section?.title ?? sectionKey.replace(/_/g, ' ')}
                </TabsTrigger>
              )
            })}
          </TabsList>

          {sectionOrder.map(sectionKey => {
            const section = sections.find(s => s.section === sectionKey)
            return (
              <TabsContent key={sectionKey} value={sectionKey}>
                {section ? (
                  <div className="prose-container">
                    <div
                      className="lesson-prose"
                      dangerouslySetInnerHTML={{ __html: renderMarkdown(section.content) }}
                    />
                  </div>
                ) : (
                  <div className="space-y-3">
                    <Skeleton className="h-5 w-3/4" />
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-5/6" />
                  </div>
                )}
              </TabsContent>
            )
          })}
        </Tabs>
      )}

      {/* Complete button */}
      {!loading && sections.length > 0 && (
        <div className="mt-8 pt-6 border-t border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <p className="text-sm text-gray-500">
            Read all sections before proceeding to the quiz
          </p>
          {completed ? (
            <Badge variant="success" className="gap-1.5 px-4 py-2">
              <CheckCircle2 className="w-4 h-4" /> Completed
            </Badge>
          ) : (
            <Button onClick={completeLesson} disabled={completing} className="gap-2">
              {completing ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
              Complete & Take Quiz
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
