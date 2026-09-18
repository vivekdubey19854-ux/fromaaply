-- Operational heartbeat only. Supabase Free-project pausing is platform-level;
-- this job is NOT a guaranteed anti-pause bypass. Current Supabase guidance says
-- sufficient user database activity prevents pausing, while paid projects are
-- the guaranteed no-pause option.
create extension if not exists pg_cron;

create or replace function public.formwise_daily_db_heartbeat()
returns void language sql security definer
set search_path = public, pg_catalog
as $$
  select count(*)::bigint from public.dynamic_banners;
$$;
revoke all on function public.formwise_daily_db_heartbeat() from public;

do $$
begin
  if exists (select 1 from cron.job where jobname = 'formwise-daily-db-heartbeat') then
    perform cron.unschedule('formwise-daily-db-heartbeat');
  end if;
  perform cron.schedule(
    'formwise-daily-db-heartbeat',
    '0 2 * * *',
    $$select public.formwise_daily_db_heartbeat()$$
  );
exception when undefined_table then
  raise notice 'pg_cron is not available; enable Supabase Cron before scheduling heartbeat';
end
$$;
