-- Formwise Phase 1-B: Multi-cloud object storage registry.
-- The registry is intentionally configuration-neutral: administrators create
-- and activate real nodes only after credentials are provisioned.

alter table public.multi_cloud_storage_nodes
  rename column node_id to id;

alter table public.multi_cloud_storage_nodes
  rename column provider to provider_name;

alter table public.multi_cloud_storage_nodes
  rename column priority_order to priority;

alter table public.multi_cloud_storage_nodes
  add column if not exists credentials jsonb not null default '{}'::jsonb;

update public.multi_cloud_storage_nodes
set status = 'UP'
where status = 'ACTIVE';

alter table public.multi_cloud_storage_nodes
  drop constraint if exists multi_cloud_provider_check;

alter table public.multi_cloud_storage_nodes
  drop constraint if exists multi_cloud_status_check;

alter table public.multi_cloud_storage_nodes
  add constraint multi_cloud_provider_name_check
    check (provider_name in (
      'oracle_cloud',
      'ibm_cos',
      'cloudflare_r2',
      'backblaze_b2',
      'supabase_storage'
    )),
  add constraint multi_cloud_status_check
    check (status in ('UP', 'DOWN')),
  add constraint multi_cloud_priority_check
    check (priority > 0),
  add constraint multi_cloud_credentials_object_check
    check (jsonb_typeof(credentials) = 'object');

create unique index if not exists ux_multi_cloud_storage_nodes_priority
  on public.multi_cloud_storage_nodes(priority);

create index if not exists ix_multi_cloud_storage_nodes_status_priority
  on public.multi_cloud_storage_nodes(status, priority);

comment on column public.multi_cloud_storage_nodes.credentials is
  'Provider configuration. Store secrets encrypted at application layer; never log this JSONB value.';
