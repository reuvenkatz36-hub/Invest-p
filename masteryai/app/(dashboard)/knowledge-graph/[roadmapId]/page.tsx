import { createClient, getAuthUser } from '@/lib/supabase/server'
import { redirect, notFound } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { KnowledgeGraph } from '@/components/knowledge-graph/KnowledgeGraph'

interface Props {
  params: Promise<{ roadmapId: string }>
}

export default async function KnowledgeGraphPage({ params }: Props) {
  const { roadmapId } = await params
  const user = await getAuthUser()
  if (!user) redirect('/login')

  const supabase = await createClient()

  const { data: roadmap } = await supabase
    .from('roadmaps')
    .select('title, user_id')
    .eq('id', roadmapId)
    .single()

  if (!roadmap || roadmap.user_id !== user.id) notFound()

  const { data: nodes } = await supabase
    .from('knowledge_nodes')
    .select('*')
    .eq('roadmap_id', roadmapId)

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Link href={`/roadmaps/${roadmapId}`}>
          <Button variant="ghost" size="sm" className="gap-2 text-gray-500">
            <ArrowLeft className="w-4 h-4" /> Back to Roadmap
          </Button>
        </Link>
      </div>

      <div className="mb-6">
        <h1 className="text-3xl font-bold mb-2">Knowledge Graph</h1>
        <p className="text-gray-500 dark:text-gray-400">
          Visual map of your skills for <strong className="text-gray-700 dark:text-gray-300">{roadmap.title}</strong>.
          Green nodes = completed, purple = in progress.
        </p>
      </div>

      {/* Legend */}
      <div className="flex gap-4 mb-4 text-sm">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-gradient-to-br from-green-500 to-green-600" />
          <span className="text-gray-600 dark:text-gray-400">Completed</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-gradient-to-br from-violet-600 to-indigo-600" />
          <span className="text-gray-600 dark:text-gray-400">In Progress / Locked</span>
        </div>
      </div>

      <KnowledgeGraph nodes={nodes ?? []} />
    </div>
  )
}
