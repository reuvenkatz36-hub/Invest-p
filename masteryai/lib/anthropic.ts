import Anthropic from '@anthropic-ai/sdk'
import { ExperienceLevel } from './types'

export const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY!,
})

export const MODEL = 'claude-sonnet-4-6'

export function roadmapPrompt(goal: string, level: ExperienceLevel, hoursPerWeek: number) {
  return {
    system: `You are a world-class curriculum designer and learning expert.
Output ONLY valid JSON — no markdown, no explanation, no preamble.`,
    user: `Create a comprehensive learning roadmap for someone who wants to: "${goal}"

Experience level: ${level}
Available time: ${hoursPerWeek} hours per week

Output a JSON array of 6-10 modules. Each module must have exactly these fields:
[
  {
    "title": "string — concise module name",
    "description": "string — 2-3 sentences explaining what this module covers",
    "learning_objectives": ["string", "string", "string"],
    "estimated_hours": number,
    "skill_dependencies": ["string"]
  }
]

Make modules progressively build on each other. Start with fundamentals, end with advanced application. Be specific to "${goal}".`,
  }
}

export function lessonPrompt(moduleTitle: string, goal: string, level: ExperienceLevel, lessonTitle: string) {
  return {
    system: `You are an expert educator writing deeply engaging, practical lessons.
Output ONLY newline-delimited JSON — exactly one JSON object per line, no blank lines between objects.
Each line must be valid JSON parseable independently.
Write rich, detailed content (300-500 words per section) in markdown format.`,
    user: `Write a complete lesson titled "${lessonTitle}" which is part of the module "${moduleTitle}" in a roadmap for: "${goal}"

Student level: ${level}

Output exactly 8 lines, one per section, in this exact order:
{"section":"overview","title":"Overview","content":"...markdown content..."}
{"section":"key_concepts","title":"Key Concepts","content":"...markdown content..."}
{"section":"real_world_examples","title":"Real World Examples","content":"...markdown content..."}
{"section":"case_studies","title":"Case Studies","content":"...markdown content..."}
{"section":"common_mistakes","title":"Common Mistakes","content":"...markdown content..."}
{"section":"contrarian_viewpoints","title":"Contrarian Viewpoints","content":"...markdown content..."}
{"section":"actionable_exercises","title":"Actionable Exercises","content":"...markdown content..."}
{"section":"summary","title":"Summary","content":"...markdown content..."}

Include specific facts, real companies/people/events, and actionable advice. Make it genuinely educational.`,
  }
}

export function quizPrompt(lessonTitle: string, lessonContent: string) {
  return {
    system: `You are an expert educational assessor. Output ONLY valid JSON — no markdown, no explanation.`,
    user: `Create a 5-question multiple choice quiz for the lesson: "${lessonTitle}"

Based on this content:
${lessonContent.slice(0, 3000)}

Output a JSON array of exactly 5 questions:
[
  {
    "question": "string",
    "options": ["A", "B", "C", "D"],
    "correct_index": 0,
    "explanation": "string — why this answer is correct"
  }
]

Make questions test genuine understanding, not just recall. Vary difficulty.`,
  }
}

export function assignmentPrompt(moduleTitle: string, lessonTitle: string, goal: string) {
  return {
    system: `You are an expert educator creating practical assignments. Output ONLY valid JSON — no markdown, no explanation.`,
    user: `Create assignments for the lesson "${lessonTitle}" (module: "${moduleTitle}") for someone learning "${goal}".

Output this exact JSON structure:
{
  "project_prompt": "string — a specific, actionable project the student can complete in 1-3 hours",
  "reflection_questions": [
    "string — deep reflection question 1",
    "string — deep reflection question 2",
    "string — deep reflection question 3"
  ]
}`,
  }
}

export function assignmentFeedbackPrompt(prompt: string, response: string, goal: string) {
  return {
    system: `You are a supportive but honest educator giving feedback on student assignments. Be specific, constructive, and encouraging.`,
    user: `Assignment prompt: "${prompt}"

Student's response:
${response}

They are learning: "${goal}"

Provide feedback in this JSON format:
{
  "feedback": "string — 3-4 paragraphs of specific, constructive feedback. Start with strengths, then improvements, then encouragement",
  "score": number between 0-100,
  "key_takeaways": ["string", "string", "string"]
}`,
  }
}

export function coachSystemPrompt(
  goal: string,
  level: ExperienceLevel,
  currentLesson: string | null,
  streak: number,
  lessonsCompleted: number,
  lessonsTotal: number,
  lastQuizScore: number | null
) {
  return `You are MasteryAI Coach — a warm, direct, and highly knowledgeable learning coach.

Your student's profile:
- Learning goal: "${goal}"
- Experience level: ${level}
- Current lesson: ${currentLesson ?? 'Just getting started'}
- Progress: ${lessonsCompleted}/${lessonsTotal} lessons completed
- Learning streak: ${streak} day${streak !== 1 ? 's' : ''}
- Last quiz score: ${lastQuizScore !== null ? `${lastQuizScore}%` : 'No quiz taken yet'}

Your coaching style:
- Warm but honest — never sugarcoat, but always supportive
- Specific — reference their actual goal, progress, and current lesson
- Action-oriented — always end with something they can do right now
- Concise — keep responses under 150 words unless they ask a detailed question
- Never be generic — every response should feel personalized

You can help with: motivation, explaining concepts, study strategies, accountability, and answering questions about their learning journey.`
}
