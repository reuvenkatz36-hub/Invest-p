-- MasteryAI Database Schema
create extension if not exists "uuid-ossp";

-- ============================================================
-- PROFILES
-- ============================================================
create table public.profiles (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  plan text not null default 'free' check (plan in ('free', 'premium')),
  stripe_customer_id text,
  stripe_subscription_id text,
  created_at timestamptz not null default now()
);
alter table public.profiles enable row level security;
create policy "Users can view own profile" on public.profiles
  for select using (auth.uid() = user_id);
create policy "Users can update own profile" on public.profiles
  for update using (auth.uid() = user_id);

-- Auto-create profile when user signs up
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (user_id) values (new.id);
  return new;
end;
$$;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ============================================================
-- ROADMAPS
-- ============================================================
create table public.roadmaps (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users(id) on delete cascade,
  goal text not null,
  experience_level text not null check (experience_level in ('beginner', 'intermediate', 'advanced')),
  hours_per_week int not null,
  title text not null,
  description text,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.roadmaps enable row level security;
create policy "Users own their roadmaps" on public.roadmaps
  for all using (auth.uid() = user_id);

-- ============================================================
-- MODULES
-- ============================================================
create table public.modules (
  id uuid primary key default uuid_generate_v4(),
  roadmap_id uuid not null references public.roadmaps(id) on delete cascade,
  title text not null,
  description text,
  order_index int not null,
  is_locked boolean not null default false
);
alter table public.modules enable row level security;
create policy "Users access modules via roadmap" on public.modules
  for all using (
    exists (select 1 from public.roadmaps r where r.id = roadmap_id and r.user_id = auth.uid())
  );

-- ============================================================
-- LESSONS
-- ============================================================
create table public.lessons (
  id uuid primary key default uuid_generate_v4(),
  module_id uuid not null references public.modules(id) on delete cascade,
  title text not null,
  content_json jsonb,
  order_index int not null,
  is_generated boolean not null default false,
  created_at timestamptz not null default now()
);
alter table public.lessons enable row level security;
create policy "Users access lessons via module" on public.lessons
  for all using (
    exists (
      select 1 from public.modules m
      join public.roadmaps r on r.id = m.roadmap_id
      where m.id = module_id and r.user_id = auth.uid()
    )
  );

-- ============================================================
-- LESSON PROGRESS
-- ============================================================
create table public.lesson_progress (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users(id) on delete cascade,
  lesson_id uuid not null references public.lessons(id) on delete cascade,
  started_at timestamptz default now(),
  completed_at timestamptz,
  time_spent_seconds int default 0,
  unique(user_id, lesson_id)
);
alter table public.lesson_progress enable row level security;
create policy "Users own their progress" on public.lesson_progress
  for all using (auth.uid() = user_id);

-- ============================================================
-- QUIZZES
-- ============================================================
create table public.quizzes (
  id uuid primary key default uuid_generate_v4(),
  lesson_id uuid not null unique references public.lessons(id) on delete cascade,
  questions_json jsonb not null
);
alter table public.quizzes enable row level security;
create policy "Users access quiz via lesson" on public.quizzes
  for all using (
    exists (
      select 1 from public.lessons l
      join public.modules m on m.id = l.module_id
      join public.roadmaps r on r.id = m.roadmap_id
      where l.id = lesson_id and r.user_id = auth.uid()
    )
  );

-- ============================================================
-- QUIZ ATTEMPTS
-- ============================================================
create table public.quiz_attempts (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users(id) on delete cascade,
  quiz_id uuid not null references public.quizzes(id) on delete cascade,
  answers_json jsonb not null,
  score numeric(5,2) not null,
  completed_at timestamptz not null default now()
);
alter table public.quiz_attempts enable row level security;
create policy "Users own their quiz attempts" on public.quiz_attempts
  for all using (auth.uid() = user_id);

-- ============================================================
-- ASSIGNMENTS
-- ============================================================
create table public.assignments (
  id uuid primary key default uuid_generate_v4(),
  lesson_id uuid not null references public.lessons(id) on delete cascade,
  prompt text not null,
  type text not null check (type in ('project', 'reflection'))
);
alter table public.assignments enable row level security;
create policy "Users access assignments via lesson" on public.assignments
  for all using (
    exists (
      select 1 from public.lessons l
      join public.modules m on m.id = l.module_id
      join public.roadmaps r on r.id = m.roadmap_id
      where l.id = lesson_id and r.user_id = auth.uid()
    )
  );

-- ============================================================
-- ASSIGNMENT SUBMISSIONS
-- ============================================================
create table public.assignment_submissions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users(id) on delete cascade,
  assignment_id uuid not null references public.assignments(id) on delete cascade,
  response_text text not null,
  ai_feedback text,
  score numeric(5,2),
  submitted_at timestamptz not null default now(),
  unique(user_id, assignment_id)
);
alter table public.assignment_submissions enable row level security;
create policy "Users own their submissions" on public.assignment_submissions
  for all using (auth.uid() = user_id);

-- ============================================================
-- COACH MESSAGES
-- ============================================================
create table public.coach_messages (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  created_at timestamptz not null default now()
);
alter table public.coach_messages enable row level security;
create policy "Users own their coach messages" on public.coach_messages
  for all using (auth.uid() = user_id);
create index idx_coach_messages_user_created on public.coach_messages(user_id, created_at desc);

-- ============================================================
-- LEARNING STREAKS
-- ============================================================
create table public.learning_streaks (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  current_streak int not null default 0,
  longest_streak int not null default 0,
  last_activity_date date
);
alter table public.learning_streaks enable row level security;
create policy "Users own their streaks" on public.learning_streaks
  for all using (auth.uid() = user_id);

-- ============================================================
-- KNOWLEDGE NODES
-- ============================================================
create table public.knowledge_nodes (
  id uuid primary key default uuid_generate_v4(),
  roadmap_id uuid not null references public.roadmaps(id) on delete cascade,
  skill_name text not null,
  is_completed boolean not null default false,
  dependencies jsonb default '[]'::jsonb
);
alter table public.knowledge_nodes enable row level security;
create policy "Users access nodes via roadmap" on public.knowledge_nodes
  for all using (
    exists (select 1 from public.roadmaps r where r.id = roadmap_id and r.user_id = auth.uid())
  );
