-- Formwise Phase 5-A: Supabase schema + provenance foundation
-- Safe to apply after the existing profile-vault schema.
-- All user data tables are tenant-scoped by user_id and protected by RLS.

begin;

-- Security metadata is mandatory on every user-data table.
alter table public.profiles
  add column if not exists confidence numeric(5,4) not null default 0.0000,
  add column if not exists verification_status text not null default 'unverified';

alter table public.addresses
  add column if not exists confidence numeric(5,4) not null default 0.0000,
  add column if not exists verification_status text not null default 'unverified';

alter table public.education
  add column if not exists confidence numeric(5,4) not null default 0.0000,
  add column if not exists verification_status text not null default 'unverified';

alter table public.documents
  add column if not exists confidence numeric(5,4) not null default 1.0000,
  add column if not exists verification_status text not null default 'uploaded';

alter table public.audit_logs
  add column if not exists confidence numeric(5,4) not null default 1.0000,
  add column if not exists verification_status text not null default 'recorded';

create table if not exists public.document_extractions (
  id uuid primary key default gen_random_uuid(),
  user_id text not null references public.profiles(user_id) on delete cascade,
  document_id text not null references public.documents(id) on delete cascade,
  extractor_version text not null,
  raw_text text,
  extracted_fields jsonb not null default '{}'::jsonb,
  confidence numeric(5,4) not null default 0.0000,
  verification_status text not null default 'extracted',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint document_extractions_confidence_ck check (confidence between 0 and 1),
  constraint document_extractions_status_ck check (verification_status in ('processing','extracted','review_required','verified','revoked'))
);

create table if not exists public.field_provenance (
  id uuid primary key default gen_random_uuid(),
  user_id text not null references public.profiles(user_id) on delete cascade,
  field_name text not null,
  field_value text not null,
  source_type text not null,
  source_id text,
  source_locator text,
  extraction_id uuid references public.document_extractions(id) on delete set null,
  confidence numeric(5,4) not null default 0.0000,
  verification_status text not null default 'review_required',
  verified_at timestamptz,
  verified_by text,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint field_provenance_confidence_ck check (confidence between 0 and 1),
  constraint field_provenance_status_ck check (verification_status in ('unverified','review_required','verified','revoked'))
);

create table if not exists public.knowledge_chunks (
  id uuid primary key default gen_random_uuid(),
  user_id text not null references public.profiles(user_id) on delete cascade,
  source_type text not null,
  source_id text,
  chunk_index integer not null default 0,
  content text not null,
  content_hash text not null,
  confidence numeric(5,4) not null default 0.0000,
  verification_status text not null default 'unverified',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint knowledge_chunks_confidence_ck check (confidence between 0 and 1),
  constraint knowledge_chunks_status_ck check (verification_status in ('unverified','review_required','verified','revoked')),
  constraint knowledge_chunks_chunk_index_ck check (chunk_index >= 0)
);

create table if not exists public.verification_records (
  id uuid primary key default gen_random_uuid(),
  user_id text not null references public.profiles(user_id) on delete cascade,
  target_type text not null,
  target_id text not null,
  previous_status text,
  new_status text not null,
  confidence numeric(5,4) not null default 0.0000,
  verifier_type text not null default 'human',
  verifier_id text,
  reason text,
  evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint verification_records_confidence_ck check (confidence between 0 and 1),
  constraint verification_records_status_ck check (new_status in ('unverified','processing','extracted','review_required','verified','revoked'))
);

-- Every user-data table gets tenant and lookup indexes.
create index if not exists ix_document_extractions_user_id on public.document_extractions(user_id);
create index if not exists ix_document_extractions_document_id on public.document_extractions(document_id);
create index if not exists ix_field_provenance_user_field on public.field_provenance(user_id, field_name);
create index if not exists ix_field_provenance_user_status on public.field_provenance(user_id, verification_status);
create index if not exists ix_knowledge_chunks_user_id on public.knowledge_chunks(user_id);
create index if not exists ix_knowledge_chunks_user_source on public.knowledge_chunks(user_id, source_type, source_id);
create unique index if not exists ux_knowledge_chunks_user_hash on public.knowledge_chunks(user_id, content_hash);
create index if not exists ix_verification_records_user_target on public.verification_records(user_id, target_type, target_id);

-- Consistent metadata constraints on existing tables.
alter table public.profiles add constraint profiles_confidence_ck check (confidence between 0 and 1);
alter table public.addresses add constraint addresses_confidence_ck check (confidence between 0 and 1);
alter table public.education add constraint education_confidence_ck check (confidence between 0 and 1);
alter table public.documents add constraint documents_confidence_ck check (confidence between 0 and 1);
alter table public.audit_logs add constraint audit_logs_confidence_ck check (confidence between 0 and 1);

-- RLS is defense-in-depth. The application server may use a privileged/direct DB role,
-- but browser clients are never granted anon access to these tables.
alter table public.profiles enable row level security;
alter table public.addresses enable row level security;
alter table public.education enable row level security;
alter table public.documents enable row level security;
alter table public.audit_logs enable row level security;
alter table public.document_extractions enable row level security;
alter table public.field_provenance enable row level security;
alter table public.knowledge_chunks enable row level security;
alter table public.verification_records enable row level security;

-- Remove broad Data API exposure; authenticated users only see their own rows.
revoke all on table public.profiles, public.addresses, public.education, public.documents,
  public.audit_logs, public.document_extractions, public.field_provenance,
  public.knowledge_chunks, public.verification_records from anon;

grant select, insert, update, delete on table public.profiles, public.addresses, public.education,
  public.documents, public.audit_logs, public.document_extractions,
  public.field_provenance, public.knowledge_chunks, public.verification_records to authenticated;

-- Ownership policies. auth.uid() is compared as text because the existing Formwise
-- user_id contract is text; this remains compatible with Supabase Auth UUID subjects.
create policy profiles_owner_select on public.profiles for select to authenticated using ((select auth.uid())::text = user_id);
create policy profiles_owner_insert on public.profiles for insert to authenticated with check ((select auth.uid())::text = user_id);
create policy profiles_owner_update on public.profiles for update to authenticated using ((select auth.uid())::text = user_id) with check ((select auth.uid())::text = user_id);
create policy profiles_owner_delete on public.profiles for delete to authenticated using ((select auth.uid())::text = user_id);

create policy addresses_owner_all on public.addresses for all to authenticated using ((select auth.uid())::text = user_id) with check ((select auth.uid())::text = user_id);
create policy education_owner_all on public.education for all to authenticated using ((select auth.uid())::text = user_id) with check ((select auth.uid())::text = user_id);
create policy documents_owner_all on public.documents for all to authenticated using ((select auth.uid())::text = user_id) with check ((select auth.uid())::text = user_id);
create policy audit_owner_select on public.audit_logs for select to authenticated using ((select auth.uid())::text = user_id);
create policy extraction_owner_all on public.document_extractions for all to authenticated using ((select auth.uid())::text = user_id) with check ((select auth.uid())::text = user_id);
create policy provenance_owner_all on public.field_provenance for all to authenticated using ((select auth.uid())::text = user_id) with check ((select auth.uid())::text = user_id);
create policy chunks_owner_all on public.knowledge_chunks for all to authenticated using ((select auth.uid())::text = user_id) with check ((select auth.uid())::text = user_id);
create policy verification_owner_select on public.verification_records for select to authenticated using ((select auth.uid())::text = user_id);

commit;
