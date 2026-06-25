import { OnboardingWizard } from '@/components/onboarding/OnboardingWizard'

export default function OnboardingPage() {
  return (
    <div className="min-h-[80vh] flex flex-col justify-center py-12">
      <div className="text-center mb-10">
        <h1 className="text-4xl font-bold mb-3 gradient-text">Let's build your roadmap</h1>
        <p className="text-gray-500 dark:text-gray-400 text-lg max-w-xl mx-auto">
          Answer 3 quick questions and AI will create a complete personalized learning roadmap just for you.
        </p>
      </div>
      <OnboardingWizard />
    </div>
  )
}
