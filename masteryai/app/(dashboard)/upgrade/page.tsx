import { createClient, getAuthUser } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'
import { PricingTable } from '@/components/pricing/PricingTable'

export default async function UpgradePage() {
  const user = await getAuthUser()
  if (!user) redirect('/login')

  const supabase = await createClient()
  const { data: profile } = await supabase.from('profiles').select('plan').eq('user_id', user.id).single()

  return (
    <div className="max-w-4xl mx-auto">
      <div className="text-center mb-12">
        <h1 className="text-4xl font-bold mb-4 gradient-text">Upgrade to Premium</h1>
        <p className="text-xl text-gray-500 dark:text-gray-400 max-w-2xl mx-auto">
          Unlock unlimited roadmaps, all lessons, AI coaching, knowledge graphs, and advanced analytics.
        </p>
      </div>
      <PricingTable currentPlan={(profile?.plan as 'free' | 'premium') ?? 'free'} />
      <p className="text-center text-sm text-gray-400 mt-8">
        Cancel anytime. No contracts. Immediate access.
      </p>
    </div>
  )
}
