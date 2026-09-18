-- Formwise Phase 2-C commercial payment infrastructure.
-- Razorpay order/payment identifiers are persisted server-side and webhook delivery is idempotent.

alter table public.transactions
  add column if not exists razorpay_order_id varchar(80),
  add column if not exists razorpay_payment_id varchar(80),
  add column if not exists user_email varchar(320),
  add column if not exists receipt_sent_at timestamptz,
  add column if not exists updated_at timestamptz not null default now();

-- Preserve legacy SUCCESS/FAILED rows while adding explicit in-flight states.
alter table public.transactions drop constraint if exists transactions_status_check;
alter table public.transactions
  add constraint transactions_status_check
  check (status in ('PENDING','PROCESSING','SUCCESS','FAILED'));

alter table public.transactions
  add constraint transactions_amount_positive_for_payment
  check ((status = 'PENDING' and amount_paid > 0) or (status <> 'PENDING' and amount_paid >= 0));

create unique index if not exists ux_transactions_razorpay_order_id
  on public.transactions (razorpay_order_id)
  where razorpay_order_id is not null;

create unique index if not exists ux_transactions_razorpay_payment_id
  on public.transactions (razorpay_payment_id)
  where razorpay_payment_id is not null;

create index if not exists ix_transactions_user_status_created
  on public.transactions (user_id, status, created_at desc);

create table if not exists public.processed_webhooks (
  webhook_id uuid primary key default gen_random_uuid(),
  event_id varchar(160) not null,
  razorpay_payment_id varchar(80),
  event_name varchar(120) not null,
  payload_sha256 char(64) not null,
  status varchar(20) not null default 'PROCESSING',
  first_received_at timestamptz not null default now(),
  processed_at timestamptz,
  last_error text,
  constraint processed_webhooks_event_id_unique unique (event_id),
  constraint processed_webhooks_status_check check (status in ('PROCESSING','PROCESSED','FAILED')),
  constraint processed_webhooks_hash_check check (length(payload_sha256) = 64)
);

create unique index if not exists ux_processed_webhooks_payment_id
  on public.processed_webhooks (razorpay_payment_id)
  where razorpay_payment_id is not null;
create index if not exists ix_processed_webhooks_status_received
  on public.processed_webhooks (status, first_received_at desc);

alter table public.processed_webhooks enable row level security;
alter table public.processed_webhooks force row level security;
revoke all on public.processed_webhooks from anon, authenticated;

comment on table public.processed_webhooks is 'Server-side Razorpay webhook idempotency ledger. Access is service-layer only.';
comment on column public.transactions.status is 'PENDING -> PROCESSING -> SUCCESS or FAILED. SUCCESS is the canonical durable paid state used by the Phase 2-B referral engine.';
