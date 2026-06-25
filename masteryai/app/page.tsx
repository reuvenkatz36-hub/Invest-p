import Link from 'next/link'
import { Sparkles, ArrowRight, BookOpen, MessageCircle, Network, TrendingUp, Zap, CheckCircle2, Star } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const features = [
  {
    icon: BookOpen,
    title: 'Personalized Roadmaps',
    desc: 'Enter any goal. AI builds a complete, structured learning path tailored to your level and schedule.',
    color: 'text-violet-500',
    bg: 'bg-violet-50 dark:bg-violet-900/20',
  },
  {
    icon: Sparkles,
    title: 'AI-Generated Lessons',
    desc: 'Each lesson includes 8 deep sections: concepts, examples, case studies, contrarian views, exercises, and more.',
    color: 'text-indigo-500',
    bg: 'bg-indigo-50 dark:bg-indigo-900/20',
  },
  {
    icon: MessageCircle,
    title: 'AI Coach',
    desc: 'A persistent coach that motivates, tracks your progress, answers questions, and adapts to your performance.',
    color: 'text-blue-500',
    bg: 'bg-blue-50 dark:bg-blue-900/20',
  },
  {
    icon: CheckCircle2,
    title: 'Quizzes & Assignments',
    desc: 'Test your understanding with quizzes and get AI-powered feedback on your practical assignments.',
    color: 'text-green-500',
    bg: 'bg-green-50 dark:bg-green-900/20',
  },
  {
    icon: Network,
    title: 'Knowledge Graph',
    desc: 'Visual map showing skill dependencies — see what you\'ve mastered and what to tackle next.',
    color: 'text-orange-500',
    bg: 'bg-orange-50 dark:bg-orange-900/20',
  },
  {
    icon: TrendingUp,
    title: 'Progress Analytics',
    desc: 'Track streaks, quiz scores, time studied, and overall progress with a beautiful dashboard.',
    color: 'text-pink-500',
    bg: 'bg-pink-50 dark:bg-pink-900/20',
  },
]

const goalExamples = [
  'Learn Investing', 'Start a Business', 'Become a Software Engineer',
  'Learn Psychology', 'Master Sales', 'Learn Digital Marketing',
  'Learn Artificial Intelligence', 'Learn Personal Finance',
]

const testimonials = [
  { quote: 'MasteryAI gave me a complete investing curriculum in 30 seconds. I\'ve learned more in 2 weeks than in 2 years of random YouTube videos.', name: 'Sarah K.', role: 'First-time investor' },
  { quote: 'The AI coach is like having a mentor available 24/7. It knows exactly where I\'m stuck and gives me targeted advice.', name: 'Marcus T.', role: 'Aspiring entrepreneur' },
  { quote: 'The knowledge graph helped me see how everything connects. It completely changed how I approach learning.', name: 'Priya M.', role: 'Software engineer' },
]

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Nav */}
      <nav className="border-b border-gray-800 sticky top-0 z-50 bg-gray-950/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-bold bg-gradient-to-r from-violet-400 to-indigo-400 bg-clip-text text-transparent">
              MasteryAI
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/login">
              <Button variant="ghost" className="text-gray-400 hover:text-white" size="sm">Sign in</Button>
            </Link>
            <Link href="/signup">
              <Button size="sm" className="bg-gradient-to-r from-violet-600 to-indigo-600">Get Started Free</Button>
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-24 pb-20 px-4 text-center relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-violet-900/20 via-transparent to-transparent pointer-events-none" />
        <div className="absolute top-20 left-1/2 -translate-x-1/2 w-[600px] h-[600px] bg-violet-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="relative max-w-4xl mx-auto">
          <Badge className="mb-6 bg-violet-900/50 text-violet-300 border border-violet-700 text-sm px-4 py-1.5">
            AI-Powered Learning Platform
          </Badge>
          <h1 className="text-5xl sm:text-6xl lg:text-7xl font-bold leading-tight mb-6">
            Master anything with
            <br />
            <span className="bg-gradient-to-r from-violet-400 via-indigo-400 to-blue-400 bg-clip-text text-transparent">
              AI as your guide
            </span>
          </h1>
          <p className="text-xl text-gray-400 mb-10 max-w-2xl mx-auto leading-relaxed">
            Enter a goal. Get a complete personalized roadmap, AI-generated lessons, quizzes, assignments, and a 24/7 AI coach to keep you on track.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link href="/signup">
              <Button size="xl" className="bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-700 hover:to-indigo-700 gap-2 shadow-lg shadow-violet-900/50 text-lg px-8">
                Start for free <ArrowRight className="w-5 h-5" />
              </Button>
            </Link>
            <Link href="/login">
              <Button variant="outline" size="xl" className="border-gray-700 text-gray-300 hover:bg-gray-900">
                Sign in
              </Button>
            </Link>
          </div>
          <p className="text-sm text-gray-500 mt-4">No credit card required · Free forever plan available</p>
        </div>
      </section>

      {/* Goal examples marquee */}
      <section className="py-8 border-y border-gray-800 bg-gray-900/50 overflow-hidden">
        <div className="flex gap-4 animate-marquee" style={{ width: 'max-content' }}>
          {[...goalExamples, ...goalExamples].map((goal, i) => (
            <div key={i} className="flex items-center gap-2 px-5 py-2.5 rounded-full border border-gray-700 bg-gray-800/50 text-sm text-gray-300 whitespace-nowrap">
              <Sparkles className="w-3.5 h-3.5 text-violet-400" />
              {goal}
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="py-24 px-4 max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-4xl font-bold mb-4">Everything you need to master any skill</h2>
          <p className="text-gray-400 text-lg max-w-2xl mx-auto">
            MasteryAI combines AI curriculum design, expert content generation, interactive assessment, and personalized coaching in one platform.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map(({ icon: Icon, title, desc, color, bg }) => (
            <Card key={title} className="bg-gray-900 border-gray-800 hover:border-gray-700 transition-colors">
              <CardContent className="p-6">
                <div className={`w-12 h-12 rounded-xl ${bg} flex items-center justify-center mb-4`}>
                  <Icon className={`w-6 h-6 ${color}`} />
                </div>
                <h3 className="font-bold text-lg mb-2 text-white">{title}</h3>
                <p className="text-gray-400 text-sm leading-relaxed">{desc}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="py-24 px-4 bg-gray-900/50 border-y border-gray-800">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold mb-4">How MasteryAI works</h2>
          </div>
          <div className="grid md:grid-cols-4 gap-8">
            {[
              { step: '01', title: 'Set Your Goal', desc: 'Tell us what you want to achieve and your current experience level.' },
              { step: '02', title: 'Get Your Roadmap', desc: 'AI generates a complete, personalized curriculum with modules and lessons.' },
              { step: '03', title: 'Learn & Practice', desc: 'Work through lessons, take quizzes, and complete hands-on assignments.' },
              { step: '04', title: 'Achieve Mastery', desc: 'Your AI Coach keeps you accountable and adapts to your progress.' },
            ].map(({ step, title, desc }) => (
              <div key={step} className="text-center">
                <div className="text-5xl font-bold text-violet-900 mb-3">{step}</div>
                <h3 className="font-bold text-lg mb-2 text-white">{title}</h3>
                <p className="text-gray-400 text-sm">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Testimonials */}
      <section className="py-24 px-4 max-w-7xl mx-auto">
        <h2 className="text-4xl font-bold text-center mb-16">Loved by learners</h2>
        <div className="grid md:grid-cols-3 gap-6">
          {testimonials.map(({ quote, name, role }) => (
            <Card key={name} className="bg-gray-900 border-gray-800">
              <CardContent className="p-6">
                <div className="flex gap-1 mb-4">
                  {[1,2,3,4,5].map(s => <Star key={s} className="w-4 h-4 text-yellow-400 fill-yellow-400" />)}
                </div>
                <p className="text-gray-300 text-sm leading-relaxed mb-4">&ldquo;{quote}&rdquo;</p>
                <div>
                  <p className="font-semibold text-sm text-white">{name}</p>
                  <p className="text-xs text-gray-500">{role}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Pricing CTA */}
      <section className="py-24 px-4 text-center">
        <div className="max-w-2xl mx-auto">
          <h2 className="text-4xl font-bold mb-4">Start mastering today</h2>
          <p className="text-gray-400 text-lg mb-10">
            Free forever for 1 roadmap. Upgrade to Premium for unlimited access.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link href="/signup">
              <Button size="xl" className="bg-gradient-to-r from-violet-600 to-indigo-600 gap-2 text-lg px-8">
                <Zap className="w-5 h-5" /> Start Free
              </Button>
            </Link>
            <Link href="/upgrade">
              <Button variant="outline" size="xl" className="border-gray-700 text-gray-300 hover:bg-gray-900">
                View Pricing
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-800 py-8 px-4 text-center text-sm text-gray-500">
        <div className="flex items-center justify-center gap-2 mb-4">
          <div className="w-6 h-6 rounded bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
            <Sparkles className="w-3 h-3 text-white" />
          </div>
          <span className="font-semibold text-gray-400">MasteryAI</span>
        </div>
        <p>© 2025 MasteryAI. AI-powered mastery learning.</p>
      </footer>

    </div>
  )
}
