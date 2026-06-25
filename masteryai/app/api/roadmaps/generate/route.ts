import { NextRequest, NextResponse } from 'next/server'
import { getAuthUser, createClient, getUserPlan } from '@/lib/supabase/server'
import { anthropic, MODEL, roadmapPrompt } from '@/lib/anthropic'
import { ExperienceLevel } from '@/lib/types'
import { extractJSON } from '@/lib/utils'

export async function POST(req: NextRequest) {
  const user = await getAuthUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { goal, experience_level, hours_per_week } = await req.json()
  if (!goal || !experience_level || !hours_per_week) {
    return NextResponse.json({ error: 'Missing fields' }, { status: 400 })
  }

  const supabase = await createClient()
  const plan = await getUserPlan(user.id)

  // Free tier: only 1 roadmap allowed
  if (plan === 'free') {
    const { count } = await supabase.from('roadmaps').select('id', { count: 'exact' }).eq('user_id', user.id)
    if ((count ?? 0) >= 1) {
      return NextResponse.json({ error: 'upgrade_required', message: 'Free plan allows 1 roadmap. Upgrade to Premium for unlimited roadmaps.' }, { status: 403 })
    }
  }

  const prompts = roadmapPrompt(goal, experience_level as ExperienceLevel, hours_per_week)

  const message = await anthropic.messages.create({
    model: MODEL,
    max_tokens: 2048,
    system: prompts.system,
    messages: [{ role: 'user', content: prompts.user }],
  })

  const rawText = (message.content[0] as { type: string; text: string }).text
  let modules: Array<{ title: string; description: string; learning_objectives: string[]; estimated_hours: number; skill_dependencies: string[] }>

  try {
    modules = JSON.parse(extractJSON(rawText))
  } catch {
    return NextResponse.json({ error: 'Failed to parse AI response' }, { status: 500 })
  }

  // Save roadmap to DB
  const { data: roadmap, error: roadmapError } = await supabase.from('roadmaps').insert({
    user_id: user.id,
    goal,
    experience_level,
    hours_per_week,
    title: `${goal} Mastery Roadmap`,
    description: `A personalized ${experience_level} roadmap to master ${goal}, designed for ${hours_per_week} hours/week.`,
  }).select().single()

  if (roadmapError || !roadmap) {
    return NextResponse.json({ error: 'Failed to save roadmap' }, { status: 500 })
  }

  // Save modules
  const moduleRows = modules.map((m, i) => ({
    roadmap_id: roadmap.id,
    title: m.title,
    description: m.description,
    order_index: i,
    is_locked: i > 0, // first module unlocked, rest locked
  }))

  const { data: savedModules, error: moduleError } = await supabase
    .from('modules')
    .insert(moduleRows)
    .select()

  if (moduleError || !savedModules) {
    return NextResponse.json({ error: 'Failed to save modules' }, { status: 500 })
  }

  // Create placeholder lessons for each module (3 lessons per module)
  const lessonRows: Array<{ module_id: string; title: string; order_index: number; is_generated: boolean }> = []
  for (const module of savedModules) {
    const moduleData = modules[savedModules.indexOf(module)]
    const objectives = moduleData.learning_objectives || []
    for (let i = 0; i < Math.max(3, objectives.length); i++) {
      lessonRows.push({
        module_id: module.id,
        title: objectives[i] || `${module.title} — Part ${i + 1}`,
        order_index: i,
        is_generated: false,
      })
    }
  }

  await supabase.from('lessons').insert(lessonRows)

  // Create knowledge nodes
  const nodeRows = modules.map((m, i) => ({
    roadmap_id: roadmap.id,
    skill_name: m.title,
    is_completed: false,
    dependencies: m.skill_dependencies || [],
  }))
  await supabase.from('knowledge_nodes').insert(nodeRows)

  // Initialize streak record
  await supabase.from('learning_streaks').upsert({
    user_id: user.id,
    current_streak: 0,
    longest_streak: 0,
  }, { onConflict: 'user_id' })

  return NextResponse.json({ roadmap_id: roadmap.id, title: roadmap.title })
}
