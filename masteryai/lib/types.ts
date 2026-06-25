export type ExperienceLevel = 'beginner' | 'intermediate' | 'advanced'
export type CoachRole = 'user' | 'assistant'
export type AssignmentType = 'project' | 'reflection'

export interface Profile {
  id: string
  user_id: string
  created_at: string
}

export interface Roadmap {
  id: string
  user_id: string
  goal: string
  experience_level: ExperienceLevel
  hours_per_week: number
  title: string
  description: string | null
  is_active: boolean
  created_at: string
  modules?: Module[]
}

export interface Module {
  id: string
  roadmap_id: string
  title: string
  description: string | null
  order_index: number
  is_locked: boolean
  lessons?: Lesson[]
}

export interface LessonSection {
  section: string
  title: string
  content: string
}

export interface Lesson {
  id: string
  module_id: string
  title: string
  content_json: LessonSection[] | null
  order_index: number
  is_generated: boolean
  created_at: string
  progress?: LessonProgress
}

export interface LessonProgress {
  id: string
  user_id: string
  lesson_id: string
  started_at: string | null
  completed_at: string | null
  time_spent_seconds: number
}

export interface QuizQuestion {
  question: string
  options: string[]
  correct_index: number
  explanation: string
}

export interface Quiz {
  id: string
  lesson_id: string
  questions_json: QuizQuestion[]
}

export interface QuizAttempt {
  id: string
  user_id: string
  quiz_id: string
  answers_json: number[]
  score: number
  completed_at: string
}

export interface Assignment {
  id: string
  lesson_id: string
  prompt: string
  type: AssignmentType
}

export interface AssignmentSubmission {
  id: string
  user_id: string
  assignment_id: string
  response_text: string
  ai_feedback: string | null
  score: number | null
  submitted_at: string
}

export interface CoachMessage {
  id: string
  user_id: string
  role: CoachRole
  content: string
  created_at: string
}

export interface LearningStreak {
  id: string
  user_id: string
  current_streak: number
  longest_streak: number
  last_activity_date: string | null
}

export interface KnowledgeNode {
  id: string
  roadmap_id: string
  skill_name: string
  is_completed: boolean
  dependencies: string[]
}

export interface ProgressStats {
  lessons_completed: number
  lessons_total: number
  quiz_average: number
  time_studied_minutes: number
  current_streak: number
  longest_streak: number
  recent_quiz_scores: { date: string; score: number; lesson: string }[]
  activity_by_date: Record<string, number>
}
