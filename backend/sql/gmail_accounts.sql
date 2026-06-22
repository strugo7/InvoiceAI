-- gmail_accounts: encrypted per-account Gmail OAuth credentials.
--
-- The `encrypted_token` column holds a Fernet ciphertext of the OAuth token
-- JSON (see backend/token_store.py). Plaintext tokens never touch this table.
--
-- Run once against your Supabase project (SQL editor or `psql`).

create table if not exists public.gmail_accounts (
    email           text primary key,
    encrypted_token text not null,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- Keep updated_at fresh on every upsert.
create or replace function public.set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_gmail_accounts_updated_at on public.gmail_accounts;
create trigger trg_gmail_accounts_updated_at
    before update on public.gmail_accounts
    for each row execute function public.set_updated_at();

-- Lock the table down: RLS on, no policies => only the service role
-- (used by the backend) can read/write it. The anon/public API keys cannot.
alter table public.gmail_accounts enable row level security;
